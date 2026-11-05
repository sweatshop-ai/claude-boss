#!/usr/bin/env python3
"""boss-efficiency core — where the time and the tokens of the boss tracks go.

The audit of 2026-11-04 turned into a routine: it reads the Claude transcripts
under `$CLAUDE_CONFIG_DIR/projects`, attributes every worker session to a track
through the boss's socket, and reports per track the share of wall time by
state, the token cost by phase, the questions to the owner per day and the CI
waits. It says something only when a track's share moves.

No LLM anywhere: every number is arithmetic on timestamps and `usage` fields.

Workers are found through the boss's socket. A dispatch is worded in many ways
and matching the text missed about half of the worker messages, but every
message a boss sends carries `<cross-session-message from="uds:...sock">`. A
socket is tied to a track by the explicit dispatches it sent (or, for a message
whose socket is unknown, by the dispatch wording), and the tie is kept in state
so a boss that changes its name or socket is picked up from its new dispatches.

A worker the boss never dispatched by a recognised message is found by name:
a session carries the name it started with ("Your name in this session is X"),
and the boss either sent to that name or heard from it (`from-name` is the name
the session started with, not the one the boss claims it under). The session
counts for the track in the boss's window, where it was alive. A track whose
goal was last marked met ends at that mark or at its last "done" commit,
whichever is later: the boss session left open after that is not the track.

Reports and state are written outside the plugin, under the config dir:
transcripts name clients, and the plugin repo is public. `write_outputs` refuses
a directory inside the plugin.

The measures are functions of one track and one window, so a later ticket (05,
the concierge) can call `measure_track` on its own tracks.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent            # <plugin>/routines
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "skills" / "boss"))
import boss_store  # noqa: E402

# ------------------------------------------------------------- thresholds
# What a "move" is. Chosen from four weekly windows of real data (see
# boss-efficiency.md, "Where the thresholds come from"); changing them changes
# what the routine says, so they live here and not in the shell.
END_SLACK_S = 1             # windows are half-open; this keeps a session's last record inside its own
ADJACENT_S = 3 * 86400      # a late or manual run still finds the week before it
COVER_GRACE_S = 600         # a worker message counts as covered within this of tracked activity
FLOOR_TOKENS = 100e6        # a track below this in either week is too small to compare (about 10% of a week)
SPEND_PP = 0.20             # a phase's share of the track's tokens, or of its worker time in CI, moved by this much
ASKS_RATIO = 3.0            # questions per 100 M tokens rose to this many times last week's...
ASKS_RISE = 1.0             # ...and by at least this many per 100 M
# A total socket-lookup failure gives a high share, not 0 messages: Index counts every message of a boss
# session whose socket is not tied, and no worker is there to cover it. 0 messages means the boss sessions
# sent none at all, which judge() fails on its own.
FAIL_UNCOVERED = 0.90       # above this the socket lookup found no ties: the week is not a measurement
MAX_TOKENS = 1e18           # a token count above this is corrupt: too big to cost without an OverflowError
MIN_MESSAGES = 10           # fewer worker messages than this cannot show a failed lookup: a quiet week is not a failure
MAX_UNCOVERED = 0.40        # not a trigger: shown beside the numbers of a track above 20% and in the header
COVER_NOTE = 0.20           # a track with this share of its worker messages outside tracked activity is marked
HISTORY_WEEKS = 8           # weeks kept in state for the trailing mean
PARK_S = 4 * 3600           # a background task older than this is parked, not working
NAME_SLACK_S = 120          # a message to or from a name reaches a session starting or ending this close to it
CUT_GRACE_S = 60            # a finished track keeps this much after its last mark, for the reply to the command
COST_WEIGHT = dict(i=1.0, cw=1.25, cr=0.1, o=5.0)           # cost units per token kind
PHASES = ("build", "fix", "sub_rev", "sub_oth", "boss")
STATES = ("work", "fix", "test", "review", "ci", "bg_other", "ask", "bossact", "parked", "nobody")

GUARD_REFUSAL = "Send it to your concierge"          # boss-guard.py's deny reason
ASK_MSG = re.compile(r"\s*ASK \S+:")
FROM = re.compile(r'<cross-session-message from="([^"]+)"')
DISP = re.compile(r"Boss dispatch from ([^,\n]+), track [`'\"]?([A-Za-z0-9._-]+)")
NOTIF = re.compile(r"<tool-use-id>(toolu_\w+)</tool-use-id>")
FROM_NAME = re.compile(r'<cross-session-message[^>]*? from-name="([^"]*)"')
OWN_REF = re.compile(r"This session is ([A-Za-z0-9_][A-Za-z0-9._-]*) \[([0-9a-f]+)\]")
SESSION_NAME = re.compile(r"Your name in this session is ([A-Za-z0-9_][A-Za-z0-9._-]*?)\.(?:\s|$)")
GOAL_STATUS = re.compile(r"boss-goal\s+status\s+([a-z0-9._-]+)\s+(open|paused|met)\b")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _command_starts(cmd):
    """Offsets where a command word begins, outside quotes, comments and heredoc bodies."""
    starts, i, n, fresh, quote = set(), 0, len(cmd), True, None
    pending = []                                  # heredoc delimiters waiting for the next line
    while i < n:
        ch = cmd[i]
        if quote:
            if ch == "\\" and quote == '"': i += 1
            elif ch == quote: quote = None
        elif ch in "'\"": quote, fresh = ch, False
        elif ch == "\\": i += 1; fresh = False
        elif ch == "#" and (i == 0 or cmd[i - 1] in " \t\n;&|("):
            while i < n and cmd[i] != "\n": i += 1
            continue
        elif ch == "\n":
            fresh = True
            for d in pending:
                m = re.compile(r"^[ \t]*" + re.escape(d) + r"[ \t]*$", re.M).search(cmd, i + 1)
                i = m.end() if m else n
            pending = []
        elif ch in ";&|(": fresh = True
        elif ch in " \t": pass
        else:
            if fresh: starts.add(i)
            fresh = False
            h = _HEREDOC.match(cmd, i) if ch == "<" else None
            if h: pending.append(h.group(2)); i = h.end(); continue
        i += 1
    return starts


def _recipient(to):
    """A SendMessage target -> (name, ref or None); the ref is the `[ref]` that tells two sessions of a name apart."""
    m = re.fullmatch(r"(.*?)\s*\[([^\]]*)\]", to)
    return (m.group(1), m.group(2)) if m else (to, None)


def _runs(cmd, m):
    """True when the match is a command that runs, not text in a quote, comment, heredoc or argument."""
    j = m.start()
    while j > 0 and not cmd[j - 1].isspace() and cmd[j - 1] not in ";&|(": j -= 1      # a path before the name
    return j in _command_starts(cmd)


GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
DONE_WORD = re.compile(r"\bdone\b", re.I)
BOSSREG = re.compile(r"boss-marker\s+register(?:\s+([a-z0-9._-]+))?")
REV_AGENT = re.compile(r"review|audit|second opinion|verif|adversar|lens|standards|spec check|critic|finding", re.I)


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# --------------------------------------------------------- classification
def cat_bash(c):
    if re.search(r"\bcodex\b.*\b(exec|review)\b|codex-review|run-codex|codex_review|\.codex-", c): return "review_codex"
    if re.search(r"gh (run (watch|view|list|rerun|cancel)|pr checks)|check-runs|check-suites|ci_state|actions/runs|statusCheckRollup", c): return "ci_wait"
    if re.search(r"pytest|npm (run )?test|vitest|playwright|jest\b|go test|cargo test|tox\b|bun test|node --test|make test", c): return "test_local"
    if re.search(r"\bssh\b|\bscp\b|\brsync\b|apply\.sh|preflight", c): return "remote_ops"
    if re.search(r"gh pr (merge|create|edit|comment|ready|review)|gh api .*(comments|reviews|merge)|git push|gh issue", c): return "pr_git_ops"
    if re.search(r"\bgit\b|\bgh\b", c): return "git_read"
    if re.search(r"npm (run|i\b|install|ci)|docker|\bmake\b|uv (sync|pip|run)|pip install|tsc\b|ruff|mypy|eslint", c): return "build_lint"
    if re.search(r"^\s*(sleep|until|while)\b|;\s*sleep\b", c): return "sleep_poll"
    if re.search(r"boss-|frontier\.py|team-line|paste ", c): return "boss_tools"
    return "bash_other"


def cat_tool(name, inp):
    if name == "Bash": return cat_bash(inp.get("command", "") or "")
    if name in ("Agent", "Task"):
        t = (inp.get("description", "") or "") + " " + (inp.get("subagent_type", "") or "")
        return "subagent_review" if REV_AGENT.search(t) else "subagent_other"
    if name == "Skill":
        return "review_skill" if "review" in (inp.get("skill", "") or "") else "skill_other"
    if name == "Monitor":
        t = (inp.get("description", "") or "") + " " + (inp.get("command", "") or "")
        k = cat_bash(t)
        if k in ("review_codex", "ci_wait", "test_local"): return k
        if "codex" in t.lower(): return "review_codex"
        return "ci_wait" if re.search(r"\bCI\b|checks?|runner", t) else "monitor_other"
    if name == "AskUserQuestion": return "ask_owner"
    if name in ("SendMessage", "ListAgents"): return "messaging"
    if name in ("Read", "Grep", "Glob", "ToolSearch", "LS"): return "file_read"
    if name in ("Edit", "Write", "NotebookEdit", "MultiEdit"): return "file_edit"
    if name.startswith("mcp__"): return "mcp"
    return "tool_other"


PRIO = ["ask_owner", "review_codex", "review_skill", "subagent_review", "ci_wait", "test_local", "remote_ops",
        "build_lint", "subagent_other", "pr_git_ops", "monitor_other", "sleep_poll", "skill_other", "bash_other",
        "mcp", "git_read", "file_edit", "file_read", "messaging", "boss_tools", "tool_other"]
PR = {c: i for i, c in enumerate(PRIO)}


def usage(u):
    def n(k):
        v = u.get(k, 0)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < MAX_TOKENS   # NaN and inf fail the compare
        return v if ok else 0
    return dict(i=n("input_tokens"), cw=n("cache_creation_input_tokens"),
                cr=n("cache_read_input_tokens"), o=n("output_tokens"))


def cost(u):
    return sum(u[k] * COST_WEIGHT[k] for k in COST_WEIGHT)


def text_of(m):
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, str): return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


# ------------------------------------------------------------------- scan
def scan_session(path, tracks=()):
    """One transcript -> a record: timed segments, per-message cost, boss messages, asks.

    Segments are (start, end, category); `llm` is the model thinking, `idle` is
    nobody working, `bg:<cat>` a background task running with no foreground
    tool. A foreground tool with no result is capped at 10 minutes, a background
    one with no completion notice at 30.
    """
    path = str(path)
    recs, tools, notif, msgs = [], {}, {}, {}
    out = dict(sid=os.path.basename(path)[:-6], boss_regs=[], asks=[], xmsgs=[], dispatches=[], subs=[],
               name=None, refs=[], sends=[], heard=[], done_commits=[], goal_status=[], concierge=False)
    ask_at = {}                                   # AskUserQuestion tool_use id -> time, dropped if the call fails
    pending_marks = {}                            # tool_use id -> goal marks, kept once the command succeeds
    tracks = set(tracks)
    alt = "|".join(re.escape(t) for t in sorted(tracks, key=len, reverse=True))
    disp3 = re.compile(r"pm/(" + alt + r")\.(?:dispatch|md|goal)") if alt else None
    skipped = 0

    def take(d, line):
        t = d.get("timestamp")
        if out["name"] is None and d.get("type") == "attachment" and "Your name in this session" in line:
            m = SESSION_NAME.search(json.dumps(d.get("attachment")))
            if m: out["name"] = m.group(1)
        if "This session is " in line:            # a ListAgents result names the session and its ref
            for nm, ref in OWN_REF.findall(line):
                if nm == out["name"]: out["refs"].append(ref)
        if "<task-notification>" in line and t:
            for m in NOTIF.findall(line): notif.setdefault(m, ts(t))
        if d.get("type") not in ("user", "assistant") or not t or d.get("isSidechain"): return
        T, m = ts(t), d.get("message") or {}
        content = m.get("content")
        if d["type"] == "assistant":
            if m.get("id"): msgs[m["id"]] = (T, usage(m.get("usage") or {}), m.get("model"))
            if isinstance(content, list):
                for b in content:
                    if b.get("type") != "tool_use": continue
                    inp = b.get("input") or {}
                    tools[b["id"]] = dict(s=T, e=None, cat=cat_tool(b["name"], inp), name=b["name"],
                                          bg=bool(inp.get("run_in_background")) or b["name"] == "Monitor",
                                          cmd=(inp.get("command") or "")[:260])
                    if b["name"] == "AskUserQuestion": out["asks"].append(T); ask_at[b["id"]] = T
                    if b["name"] == "SendMessage" and isinstance(inp.get("to"), str): out["sends"].append((T, *_recipient(inp["to"])))
                    if b["name"] == "Bash":
                        c = inp.get("command", "") or ""
                        r = BOSSREG.search(c)
                        plain = not c.lstrip().startswith(("grep", "rg", "cat", "sed"))
                        if r and plain:
                            out["boss_regs"].append((T, r.group(1)))
                        found = [(T, g.group(1), g.group(2)) for g in GOAL_STATUS.finditer(c) if _runs(c, g)]
                        if found: pending_marks[b["id"]] = found
                        if DONE_WORD.search(c) and any(_runs(c, gc) for gc in GIT_COMMIT.finditer(c)):
                            out["done_commits"].append(T)
            recs.append((T, "a"))
            return
        is_result = False
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    is_result = True
                    if b.get("tool_use_id") in ask_at and GUARD_REFUSAL in json.dumps(b.get("content")):
                        out["asks"].remove(ask_at.pop(b["tool_use_id"]))      # refused by the guard: the owner never saw it
                    if b.get("tool_use_id") in pending_marks and not b.get("is_error"):
                        out["goal_status"].extend(pending_marks.pop(b["tool_use_id"]))     # a failed command marks nothing
                    x = tools.get(b.get("tool_use_id"))
                    if x and x["e"] is None:
                        x["e"] = T
                        tx = json.dumps(b.get("content"))[:300]
                        if "Async agent launched" in tx or "running in background" in tx or "Monitor started" in tx:
                            x["bg"] = True
        if not is_result:
            tx = text_of(m)
            f = FROM.search(tx[:400])
            if f:
                body = tx[tx.find(">", f.end()) + 1:tx.find(">", f.end()) + 900]
                if ASK_MSG.match(body): out["concierge"] = True       # the boss sends it `ASK <id>:`
                g = DISP.search(body)
                g3 = None if g else (disp3.search(body) if disp3 else None)
                trk = (g.group(2).rstrip(".`") if g else g3.group(1) if g3 else None)
                if trk and g and trk not in tracks: trk, g = None, None
                out["xmsgs"].append((T, f.group(1), trk, bool(g)))
                n = FROM_NAME.search(tx[:400])
                if n: out["heard"].append((T, n.group(1), None))
        recs.append((T, "r" if is_result else "u"))

    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                take(json.loads(line), line)
            except (ValueError, TypeError, AttributeError, KeyError):
                skipped += 1              # one odd line in 5 GB must not stop the week
    out["skipped"] = skipped
    if not recs: return None
    recs.sort()
    out["start"], out["end"] = recs[0][0], recs[-1][0]
    last = recs[-1][0]
    fg, bg = [], []
    for tid, x in tools.items():
        if x["bg"]:
            e = notif.get(tid)
            if e is None: e = min(x["s"] + 1800, last)
            bg.append((x["s"], max(e, x["s"]), x["cat"]))
        else:
            e = x["e"] if x["e"] else min(x["s"] + 600, last)
            fg.append((x["s"], max(e, x["s"]), x["cat"]))
    out["segs"] = _segments(recs, fg, bg)
    rev = [x["s"] for x in tools.values() if x["cat"] in ("review_codex", "review_skill", "subagent_review")]
    out["first_review"] = min(rev) if rev else None
    ed = [x["s"] for x in tools.values() if x["name"] in ("Edit", "Write", "MultiEdit")]
    out["first_edit"] = min(ed) if ed else None
    out["review_starts"] = sorted(rev)
    out["ci_waits"] = [(round(x["s"]), round((notif.get(tid) if x["bg"] else x["e"]) or x["s"]))
                       for tid, x in tools.items() if x["cat"] == "ci_wait"
                       and ((notif.get(tid) if x["bg"] else x["e"]) or x["s"]) - x["s"] >= 60]
    out["msgs"] = sorted((round(T, 1), round(cost(u))) for T, u, _ in msgs.values())
    base = path[:-6] + "/subagents"
    if os.path.isdir(base):
        for j in sorted(Path(base).glob("*.jsonl")):
            meta = {}
            mp = j.with_suffix(".meta.json")
            if mp.exists():
                try: meta = json.loads(mp.read_text())
                except Exception: pass
            seen, s0 = {}, None
            for line in open(j, errors="replace"):
                try:
                    d = json.loads(line)
                    if d.get("type") == "assistant":
                        mm = d.get("message") or {}
                        if mm.get("id"): seen[mm["id"]] = usage(mm.get("usage") or {})
                        if d.get("timestamp") and s0 is None: s0 = ts(d["timestamp"])
                except (ValueError, TypeError, AttributeError, KeyError):
                    skipped += 1
            out["subs"].append(dict(s=s0, cost=round(sum(cost(u) for u in seen.values())),
                                    review=bool(REV_AGENT.search(meta.get("description", "") or ""))))
    out["skipped"] = skipped
    return out


def _segments(recs, fg, bg):
    rt = [r[0] for r in recs]
    bounds = sorted(set(rt + [a for i in fg + bg for a in i[:2]]))
    fg.sort(); bg.sort()
    segs, fi, bi, afg, abg = [], 0, 0, [], []
    for a, b in zip(bounds, bounds[1:]):
        while fi < len(fg) and fg[fi][0] <= a: afg.append(fg[fi]); fi += 1
        while bi < len(bg) and bg[bi][0] <= a: abg.append(bg[bi]); bi += 1
        afg = [x for x in afg if x[1] > a]; abg = [x for x in abg if x[1] > a]
        if afg: c = min((x[2] for x in afg), key=lambda k: PR.get(k, 99))
        else:
            j = bisect.bisect_right(rt, a)
            nxt = recs[j][1] if j < len(recs) else None
            if nxt == "a": c = "llm"
            elif abg: c = "bg:" + min((x[2] for x in abg), key=lambda k: PR.get(k, 99))
            else: c = "idle"
        if segs and segs[-1][2] == c and segs[-1][1] == a: segs[-1][1] = b
        else: segs.append([a, b, c])
    return [(round(a, 1), round(b, 1), "llm_stall" if c == "llm" and b - a > 600 else c) for a, b, c in segs]


# ------------------------------------------------------------ attribution
def session_end(s):
    """The end of a session as a window bound: the last record falls inside it."""
    return s["end"] + END_SLACK_S


def boss_windows(s, marker_track=None):
    """[(track, start, end)] a boss session spent on each track."""
    regs = [r for r in s["boss_regs"] if r[1]]
    if not regs and marker_track: return [(marker_track, s["start"], session_end(s))]
    return [(tr, s["start"] if i == 0 else t, regs[i + 1][0] if i + 1 < len(regs) else session_end(s))
            for i, (t, tr) in enumerate(regs)]


def resolve_sockets(sessions, saved=None):
    """socket -> track. Explicit dispatches vote; a track needs 2 votes and 60%.

    A saved tie survives until new votes replace it, so a boss that was quiet
    this week keeps its socket; a boss with a new socket gets one from its
    first two dispatches.
    """
    votes = collections.defaultdict(collections.Counter)
    for s in sessions:
        for _, sock, trk, explicit in s["xmsgs"]:
            if trk and explicit: votes[sock][trk] += 1
    socks = dict(saved or {})
    for sock, c in votes.items():
        trk, n = c.most_common(1)[0]
        if n >= 2 and n / sum(c.values()) >= 0.6: socks[sock] = trk
    return socks


def _subtract(a, b, taken):
    """[a, b) minus the intervals in `taken`, as a list of intervals."""
    out, x = [], a
    for ta, tb in sorted(taken):
        if tb <= x or ta >= b: continue
        if ta > x: out.append((x, ta))
        x = max(x, tb)
    if x < b: out.append((x, b))
    return out


class Index:
    """Everything a measure needs, built once per scan."""

    def __init__(self, sessions, markers, socks):
        self.socks = socks
        self.workers = collections.defaultdict(list)   # track -> [(session, start, end)]
        self.bosses = collections.defaultdict(list)    # track -> [(session, start, end)]
        self.worker_msgs = collections.defaultdict(list)   # track -> [T] messages arriving at its boss
        self.cut = {}                                   # track -> where a finished track ends
        boss_sids = set()
        windows = {}
        for s in sessions:
            bw = boss_windows(s, markers.get(s["sid"]))
            windows[s["sid"]] = bw
            if bw: boss_sids.add(s["sid"])
            for tr, a, b in bw: self.bosses[tr].append((s, a, b))
        taken = collections.defaultdict(list)          # sid -> intervals already given to a track
        for s in sessions:
            if s["sid"] in boss_sids:
                for T, sock, _, _ in s["xmsgs"]:
                    if sock in socks: continue                # another boss, not a worker
                    for tr, a, b in windows[s["sid"]]:
                        if a <= T <= b: self.worker_msgs[tr].append(T)
                continue
            ev = [(T, socks.get(sock) or trk) for T, sock, trk, _ in s["xmsgs"] if socks.get(sock) or trk]
            for i, (T, tr) in enumerate(ev):
                end = ev[i + 1][0] if i + 1 < len(ev) else session_end(s)
                self.workers[tr].append((s, T, end))
                taken[s["sid"]].append((T, end))
        self._attribute_by_name(sessions, boss_sids, windows, taken)
        self._cut_finished(sessions, boss_sids)

    def _attribute_by_name(self, sessions, boss_sids, windows, taken):
        """A worker the boss sent to or heard from by name counts in the boss's window.

        The session must have been alive at the message (a name is reused by
        later sessions). Time already given to a track by a dispatch or a
        socket stays with that track.
        """
        by_name = collections.defaultdict(list)
        for s in sessions:
            if s["sid"] not in boss_sids and s.get("name"): by_name[s["name"]].append(s)
        for b in sessions:
            if b["sid"] not in boss_sids: continue
            for T, name, ref in b.get("sends", []) + b.get("heard", []):
                for tr, a, z in windows[b["sid"]]:
                    if not a <= T <= z: continue
                    near = [s for s in by_name.get(name, ())
                            if s["start"] - NAME_SLACK_S <= T <= session_end(s) + NAME_SLACK_S]
                    # a reused name inside the slack: only the session alive at T, else the nearest
                    near.sort(key=lambda s: (max(s["start"] - T, T - session_end(s), 0), -s["start"]))
                    if ref:
                        # a session that knows another ref is not the one addressed; among sessions sharing the name, only a holder is
                        live = [s for s in near if s["start"] <= T <= session_end(s)]
                        near, shared = live or near, len(live or near) > 1
                        near = [s for s in near if not s["refs"] or ref in s["refs"]]
                        if shared: near = [s for s in near if ref in s["refs"]]
                    for s in near[:1]:
                        lo, hi = max(a, s["start"]), min(z, session_end(s))
                        if hi <= lo: continue
                        for x, y in _subtract(lo, hi, taken[s["sid"]]):
                            self.workers[tr].append((s, x, y))
                            taken[s["sid"]].append((x, y))

    def _cut_finished(self, sessions, boss_sids):
        """A track whose goal was last marked met ends at that mark or its last done commit."""
        last = {}
        for s in sessions:
            if s["sid"] not in boss_sids: continue
            for T, tr, value in s.get("goal_status", []):
                if tr not in last or T >= last[tr][0]: last[tr] = (T, value)
        for tr, (T, value) in last.items():
            if value != "met": continue
            done = [c for src in (self.workers.get(tr, []), self.bosses.get(tr, []))
                    for s, a, b in src for c in s.get("done_commits", []) if a <= c < b]
            self.cut[tr] = max([T] + done) + CUT_GRACE_S

    def clip_end(self, track, end):
        """A window's end, or where the track finished if that is sooner."""
        return min(end, self.cut.get(track, end))

    def tracks(self):
        return sorted(set(self.workers) | set(self.bosses))


# ---------------------------------------------------------------- measures
def _clip(segs, a, b):
    for x, y, c in segs:
        x2, y2 = max(x, a), min(y, b)
        if y2 > x2: yield x2, y2, c


def _group(c, dur):
    bg = c.startswith("bg:")
    k = c.replace("bg:", "")
    if bg and dur > PARK_S: return "parked"
    if k in ("review_codex", "review_skill", "subagent_review"): return "review"
    return {"ci_wait": "ci", "test_local": "test", "llm": "llm", "llm_stall": "stall", "idle": "idle",
            "ask_owner": "ask", "remote_ops": "remote", "subagent_other": "sub_other"}.get(k, "bg_other" if bg else "tools")


def _boundary(s):
    """First moment of review after the first edit: later work is a fix."""
    fe, fr = s.get("first_edit"), s.get("first_review")
    if fr and fe and fr > fe: return fr
    if fe is None: return fr
    later = [t for t in s["review_starts"] if t > fe]
    return min(later) if later else None


def measure_track(index, track, start, end):
    """One track in one window: seconds by state, tokens by phase, asks, CI waits."""
    days = (end - start) / 86400          # a rate stays per day of the window, not of the shortened track
    end = index.clip_end(track, end)
    ev, wh, tok = [], collections.Counter(), collections.Counter()
    asks = 0
    spans = []
    ci_waits = 0
    for s, a, b in index.workers.get(track, []):
        a, b = max(a, start), min(b, end)
        if b <= a: continue
        spans.append((a, b))
        bd = _boundary(s)
        for x, y, c in _clip(s["segs"], a, b):
            g = _group(c, y - x)
            wh[g] += y - x
            if g == "idle": continue
            ev.append((x, y, ("fix" if bd and x >= bd else "work") if g in ("llm", "tools", "remote", "sub_other", "stall") else g))
        for T, cst in s["msgs"]:
            if a <= T < b: tok["fix" if bd and T >= bd else "build"] += cst
        for sub in s["subs"]:
            if sub["s"] and a <= sub["s"] < b: tok["sub_rev" if sub["review"] else "sub_oth"] += sub["cost"]
        ci_waits += sum(1 for x, y in s["ci_waits"] if a <= x < b)
        if s["concierge"]: asks += sum(1 for T in s["asks"] if a <= T < b)   # it asks the owner for the boss
    for s, a, b in index.bosses.get(track, []):
        a, b = max(a, start), min(b, end)
        if b <= a: continue
        spans.append((a, b))
        for x, y, c in _clip(s["segs"], a, b):
            g = _group(c, y - x)
            if g == "ask": ev.append((x, y, "ask"))
            elif g in ("llm", "tools"): ev.append((x, y, "bossact"))
        for T, cst in s["msgs"]:
            if a <= T < b: tok["boss"] += cst
        asks += sum(1 for T in s["asks"] if a <= T < b)
    states = _states(ev)
    wall = (max(y for _, y in spans) - min(x for x, _ in spans)) if spans else 0
    states["nobody"] = max(0, wall - sum(states.values()))
    return dict(track=track, wall_s=round(wall), states={k: round(states.get(k, 0)) for k in STATES},
                worker_s={k: round(v) for k, v in wh.items()},
                tokens={k: tok.get(k, 0) for k in PHASES}, total_tokens=sum(tok.values()),
                asks=asks, asks_per_day=round(asks / days, 2) if days else 0,
                ci_s=round(states.get("ci", 0)), ci_waits=ci_waits)


def _states(ev):
    """Seconds per state; where states overlap, the first in the order wins."""
    order = ["work", "fix", "test", "review", "ci", "bg_other", "ask", "bossact", "parked"]
    pts = sorted({p for e in ev for p in e[:2]})
    ev.sort()
    i, act, out = 0, [], collections.Counter()
    for a, b in zip(pts, pts[1:]):
        while i < len(ev) and ev[i][0] <= a: act.append(ev[i]); i += 1
        act = [e for e in act if e[1] > a]
        g = {e[2] for e in act}
        for k in order:
            if k in g: out[k] += b - a; break
    return out


def coverage(index, track, start, end):
    """Worker messages to this track's boss, and how many fall outside tracked activity.

    A message is covered when a tracked worker session of the track was doing
    something within COVER_GRACE_S of it. Uncovered ones come from workers this
    routine did not attribute.
    """
    end = index.clip_end(track, end)
    live = []
    for s, a, b in index.workers.get(track, []):
        b = min(b, end)
        if b <= a: continue
        live += [(x - COVER_GRACE_S, y + COVER_GRACE_S) for x, y, c in _clip(s["segs"], a, b) if c != "idle"]
    live.sort()
    merged = []                       # disjoint union, so one bisect finds the cover
    for x, y in live:
        if merged and x <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], y)
        else: merged.append([x, y])
    starts = [x for x, _ in merged]
    n = out = 0
    for T in index.worker_msgs.get(track, []):
        if not start <= T < end: continue
        n += 1
        j = bisect.bisect_right(starts, T)
        if not (j and merged[j - 1][1] >= T): out += 1
    return dict(messages=n, outside=out)


def measure_window(index, start, end):
    tracks = {}
    for tr in index.tracks():
        m = measure_track(index, tr, start, end)
        if m["wall_s"] == 0 and not m["total_tokens"]: continue
        m["coverage"] = coverage(index, tr, start, end)
        tracks[tr] = m
    total = sum(m["total_tokens"] for m in tracks.values())
    for m in tracks.values(): m["budget_share"] = round(m["total_tokens"] / total, 4) if total else 0
    msgs = sum(m["coverage"]["messages"] for m in tracks.values())
    outside = sum(m["coverage"]["outside"] for m in tracks.values())
    return dict(start=start, end=end, total_tokens=total, tracks=tracks,
                coverage=dict(messages=msgs, outside=outside, share=round(outside / msgs, 4) if msgs else None))


# ----------------------------------------------------------------- verdict
def spend(m):
    """How one track spends: tokens by phase, CI share of worker time, questions per 100 M tokens."""
    t = m["total_tokens"]
    active = sum(v for k, v in m["worker_s"].items() if k != "idle")
    d = {k: (v / t if t else 0) for k, v in m["tokens"].items()}
    d["ci_wait"] = m["worker_s"].get("ci", 0) / active if active else 0
    d["asks_per_100M"] = m["asks"] / (t / 1e8) if t else 0
    return d


def judge(week, previous):
    """(failures, anomalies) for a measured week against the week before it.

    A failure is the routine not working: no sessions, or nothing to check the
    coverage on. Silence is never reported for those. An anomaly is a change in
    how a track spends, for a track live in both weeks with tokens at or above
    FLOOR_TOKENS in each. A track's share of the fleet is information only: it
    moves every week because tracks start and end, and says who was running.
    Numbers and track names only.
    """
    fails, flags = [], []
    if not week["tracks"]:
        fails.append("no tracked sessions found in the window")
    if week["coverage"]["messages"] == 0:
        fails.append("coverage check ran on 0 worker messages")
    elif week["coverage"]["messages"] >= MIN_MESSAGES and week["coverage"]["share"] > FAIL_UNCOVERED:
        fails.append("%.0f%% of worker messages are outside tracked activity: the socket lookup found no workers"
                     % (100 * week["coverage"]["share"]))
    if not previous or abs(previous["end"] - week["start"]) > ADJACENT_S:
        return fails, flags                # no adjacent week to compare with
    for tr, m in sorted(week["tracks"].items()):
        p = previous["tracks"].get(tr)
        if not p or min(m["total_tokens"], p["total_tokens"]) < FLOOR_TOKENS: continue
        now, was = spend(m), spend(p)
        found = ["%s %.0f%% against %.0f%%" % (k.replace("_", " "), 100 * now[k], 100 * was[k])
                 for k in (*PHASES, "ci_wait") if abs(now[k] - was[k]) >= SPEND_PP]
        if now["asks_per_100M"] - was["asks_per_100M"] >= ASKS_RISE and now["asks_per_100M"] >= ASKS_RATIO * was["asks_per_100M"]:
            found.append("questions %.1f against %.1f per 100 M tokens" % (now["asks_per_100M"], was["asks_per_100M"]))
        if found:
            flags.append("%s: %s%s" % (tr, "; ".join(found), coverage_note(m)))
    return fails, flags


def pick_previous(history, week):
    """The earlier week whose end is nearest this week's start, or None."""
    near = [h for h in history if h["end"] <= week["end"] - 86400]
    return min(near, key=lambda h: abs(h["end"] - week["start"]), default=None)


def coverage_note(m):
    c = m["coverage"]
    if c["messages"] and c["outside"] / c["messages"] >= COVER_NOTE:
        return " (low coverage: %d of %d of its worker messages outside tracked activity)" % (c["outside"], c["messages"])
    return ""


# ------------------------------------------------------------------ report
def hours(s): return "%.1f" % (s / 3600)


def render(week, label, fails, flags):
    out = ["# Boss efficiency, week ending %s" % label, ""]
    c = week["coverage"]
    out.append("Token budget %.0f M cost units. Coverage: %s of %d worker messages outside tracked activity."
               % (week["total_tokens"] / 1e6, "n/a" if c["share"] is None else "%.0f%%" % (100 * c["share"]), c["messages"]))
    if c["share"] is not None and c["share"] > MAX_UNCOVERED:
        out.append("Numbers of tracks with many messages outside tracked activity rest on less than they show: see the Outside column.")
    for f in fails: out.append("**FAILED:** " + f)
    for f in flags: out.append("**Moved:** " + f)
    out += ["", "| Track | Budget | Wall h | " + " | ".join(STATES) + " | " + " | ".join("tok " + p for p in PHASES)
            + " | Asks/day | CI waits | CI h | Outside |", "|" + "---|" * (len(STATES) + len(PHASES) + 7)]
    for tr, m in sorted(week["tracks"].items(), key=lambda kv: -kv[1]["total_tokens"]):
        cv = m["coverage"]
        out.append("| %s | %.0f%% | %s | %s | %s | %s | %s | %.1f | %s |" % (
            tr, 100 * m["budget_share"], hours(m["wall_s"]), " | ".join(hours(m["states"][k]) for k in STATES),
            " | ".join("%.1f" % (m["tokens"][k] / 1e6) for k in PHASES), m["asks_per_day"], m["ci_waits"], m["ci_s"] / 3600,
            "%d/%d" % (cv["outside"], cv["messages"])))
    return "\n".join(out) + "\n"


def write_outputs(cfg, label, week, text, state):
    """Reports and state go under the config dir, never into the plugin."""
    root = Path(cfg).resolve() / "routines"
    if PLUGIN in root.parents or root == PLUGIN:
        raise SystemExit("refusing to write reports inside the plugin: %s" % root)
    rep = root / "reports"
    st = root / "state"
    rep.mkdir(parents=True, exist_ok=True); st.mkdir(parents=True, exist_ok=True)
    (rep / ("boss-efficiency-%s.md" % label)).write_text(text)
    for path, data in ((rep / ("boss-efficiency-%s.json" % label), week), (st / "boss-efficiency.json", state)):
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        with os.fdopen(fd, "w") as f: json.dump(data, f)
        os.replace(tmp, path)


def alert(text, dry):
    """Slack #claude-ops. `text` is numbers and track names, never transcript text.

    boss-alert is for blockers (every message starts "blocked"), so this posts
    itself with the credentials boss-alert reads. Returns whether it was sent.
    """
    if dry:
        print("DRY_RUN: would alert:\n" + text)
        return True
    envf = Path(os.environ.get("BOSS_SLACK_ENV") or Path.home() / ".config" / "tiroir" / "slack.env")
    try:
        creds = {}
        for l in envf.read_text().splitlines():
            l = l.strip().removeprefix("export ").strip()
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1)
                creds[k.strip()] = v.strip().strip("\"'")
        api = os.environ.get("BOSS_SLACK_API", "https://slack.com/api/chat.postMessage")
        body = urllib.parse.urlencode({"channel": creds["SLACK_CHANNEL_ID"], "text": ":bar_chart: " + text}).encode()
        req = urllib.request.Request(api, body, {"Authorization": "Bearer " + creds["SLACK_BOT_TOKEN"]})
        ok = json.load(urllib.request.urlopen(req, timeout=15)).get("ok")
    except (OSError, KeyError, ValueError) as e:
        print("boss-efficiency: alert not sent: %s" % type(e).__name__, file=sys.stderr)
        return False
    if not ok: print("boss-efficiency: Slack refused the alert", file=sys.stderr)
    return bool(ok)


# -------------------------------------------------------------------- main
def discover(cfg, since):
    root = Path(cfg) / "projects"
    found = []
    for p in root.glob("*/*.jsonl"):
        try:
            if p.stat().st_mtime >= since: found.append(p)
        except OSError:
            pass                          # gone between the glob and the stat
    return found


def known_tracks(cfg, state):
    pm = boss_store.pm_dir(cfg)
    return sorted({p.name[:-len(".goal.md")] for p in pm.glob("*.goal.md")} | set(state.get("tracks", [])))


def markers(cfg):
    d = boss_store.markers_dir(cfg)
    out = {}
    if d.is_dir():
        for p in d.iterdir():
            t = boss_store.track_of(p.name, cfg)
            if t: out[p.name] = t
    return out


def run(cfg, end, weeks, dry):
    cfg = Path(cfg)
    st_path = cfg / "routines" / "state" / "boss-efficiency.json"
    state = json.loads(st_path.read_text()) if st_path.exists() else {}
    first = end - weeks * 7 * 86400
    known = sorted(set(known_tracks(cfg, state)) | set(markers(cfg).values()))
    sessions, unreadable = [], 0
    for p in discover(cfg, first):
        try:
            r = scan_session(p, known)
        except OSError:
            unreadable += 1
            continue
        if r: sessions.append(r)
    if unreadable: print("boss-efficiency: %d transcript(s) unreadable" % unreadable, file=sys.stderr)
    odd = sum(r["skipped"] for r in sessions)
    if odd: print("boss-efficiency: %d malformed transcript line(s) skipped (in sessions with records)" % odd, file=sys.stderr)
    socks = resolve_sockets(sessions, state.get("socks"))
    idx = Index(sessions, markers(cfg), socks)
    history = state.get("weeks", [])
    problems = failed = 0
    unsent = []                             # alerts Slack did not take: kept, and tried again with the next run
    for item in state.get("unsent", []):
        if dry or alert("(delayed) " + item["text"], dry): continue
        unsent.append(item)
        failed += 1
    for w in range(weeks):
        wend = end - (weeks - 1 - w) * 7 * 86400
        week = measure_window(idx, wend - 7 * 86400, wend)
        label = dt.datetime.fromtimestamp(wend).strftime("%Y-%m-%d")
        fails, flags = judge(week, pick_previous(history, week))
        text = render(week, label, fails, flags)
        if not fails:                       # a week that could not be measured is no baseline
            # a rerun of the same week replaces it, whatever second it ran at (a day's slack covers DST)
            history = [h for h in history if abs(h["end"] - wend) >= 86400] + [week]
            history = sorted(history, key=lambda h: h["end"])[-HISTORY_WEEKS:]
        if fails or flags:
            problems += 1
            failed += bool(fails)
            said = "boss-efficiency week ending %s: %s" % (label, "; ".join(["FAILED " + f for f in fails] + flags))
            if not alert(said, dry) and not dry:
                failed += 1
                unsent = [u for u in unsent if u["label"] != label] + [dict(label=label, text=said)]
        if not dry:
            state = dict(socks=socks, tracks=sorted(set(idx.tracks()) | set(state.get("tracks", []))), weeks=history,
                         unsent=unsent)
            write_outputs(cfg, label, week, text, state)
        else:
            print(text)
    return (2 if failed else 0), problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--end", help="end of the last window, ISO date (default: now)")
    ap.add_argument("--weeks", type=int, default=1, help="how many weekly windows, oldest first (backfill)")
    ap.add_argument("--alert", metavar="TEXT", help="only post TEXT to Slack (the body uses it when it cannot run); exit 3 if not sent")
    a = ap.parse_args(argv)
    if a.alert is not None:
        return 0 if alert(a.alert, os.environ.get("DRY_RUN") == "1") else 3
    end = dt.datetime.fromisoformat(a.end).timestamp() if a.end else dt.datetime.now().timestamp()
    rc, problems = run(boss_store.config_dir(), end, a.weeks, os.environ.get("DRY_RUN") == "1")
    print("boss-efficiency: %d window(s) with something to say" % problems)
    return rc


if __name__ == "__main__":
    sys.exit(main())
