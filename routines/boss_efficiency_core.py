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
COVER_GRACE_S = 600         # a worker message counts as covered within this of tracked activity
FLOOR_TOKENS = 100e6        # a track below this in either week is too small to compare (about 10% of a week)
SPEND_PP = 0.20             # a phase's share of the track's tokens, or of its worker time in CI, moved by this much
ASKS_RATIO = 3.0            # questions per 100 M tokens rose to this many times last week's...
ASKS_RISE = 1.0             # ...and by at least this many per 100 M
MAX_UNCOVERED = 0.40        # not a trigger: shown beside the numbers of a track above 20% and in the header
COVER_NOTE = 0.20           # a track with this share of its worker messages outside tracked activity is marked
HISTORY_WEEKS = 8           # weeks kept in state for the trailing mean
PARK_S = 4 * 3600           # a background task older than this is parked, not working
COST_WEIGHT = dict(i=1.0, cw=1.25, cr=0.1, o=5.0)           # cost units per token kind
PHASES = ("build", "fix", "sub_rev", "sub_oth", "boss")
STATES = ("work", "fix", "test", "review", "ci", "bg_other", "ask", "bossact", "parked", "nobody")

FROM = re.compile(r'<cross-session-message from="([^"]+)"')
DISP = re.compile(r"Boss dispatch from ([^,\n]+), track [`'\"]?([A-Za-z0-9._-]+)")
NOTIF = re.compile(r"<tool-use-id>(toolu_\w+)</tool-use-id>")
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
    return dict(i=u.get("input_tokens", 0) or 0, cw=u.get("cache_creation_input_tokens", 0) or 0,
                cr=u.get("cache_read_input_tokens", 0) or 0, o=u.get("output_tokens", 0) or 0)


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
    out = dict(sid=os.path.basename(path)[:-6], boss_regs=[], asks=[], xmsgs=[], dispatches=[], subs=[])
    tracks = set(tracks)
    alt = "|".join(re.escape(t) for t in sorted(tracks, key=len, reverse=True))
    disp3 = re.compile(r"pm/(" + alt + r")\.(?:dispatch|md|goal)") if alt else None
    with open(path, errors="replace") as fh:
        for line in fh:
            try: d = json.loads(line)
            except Exception: continue
            t = d.get("timestamp")
            if "<task-notification>" in line and t:
                for m in NOTIF.findall(line): notif.setdefault(m, ts(t))
            if d.get("type") not in ("user", "assistant") or not t or d.get("isSidechain"): continue
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
                        if b["name"] == "AskUserQuestion": out["asks"].append(T)
                        if b["name"] == "Bash":
                            c = inp.get("command", "") or ""
                            r = BOSSREG.search(c)
                            if r and not c.lstrip().startswith(("grep", "rg", "cat", "sed")):
                                out["boss_regs"].append((T, r.group(1)))
                recs.append((T, "a"))
                continue
            is_result = False
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        is_result = True
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
                    body = tx[tx.find(">") + 1:tx.find(">") + 900]
                    g = DISP.search(body)
                    g3 = None if g else (disp3.search(body) if disp3 else None)
                    trk = (g.group(2).rstrip(".`") if g else g3.group(1) if g3 else None)
                    if trk and g and trk not in tracks: trk, g = None, None
                    out["xmsgs"].append((T, f.group(1), trk, bool(g)))
            recs.append((T, "r" if is_result else "u"))
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
                try: d = json.loads(line)
                except Exception: continue
                if d.get("type") == "assistant":
                    mm = d.get("message") or {}
                    if mm.get("id"): seen[mm["id"]] = usage(mm.get("usage") or {})
                    if d.get("timestamp") and s0 is None: s0 = ts(d["timestamp"])
            out["subs"].append(dict(s=s0, cost=round(sum(cost(u) for u in seen.values())),
                                    review=bool(REV_AGENT.search(meta.get("description", "") or ""))))
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
def boss_windows(s, marker_track=None):
    """[(track, start, end)] a boss session spent on each track."""
    regs = [r for r in s["boss_regs"] if r[1]]
    if not regs and marker_track: return [(marker_track, s["start"], s["end"])]
    return [(tr, s["start"] if i == 0 else t, regs[i + 1][0] if i + 1 < len(regs) else s["end"])
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


class Index:
    """Everything a measure needs, built once per scan."""

    def __init__(self, sessions, markers, socks):
        self.socks = socks
        self.workers = collections.defaultdict(list)   # track -> [(session, start, end)]
        self.bosses = collections.defaultdict(list)    # track -> [(session, start, end)]
        self.worker_msgs = collections.defaultdict(list)   # track -> [T] messages arriving at its boss
        boss_sids = set()
        for s in sessions:
            bw = boss_windows(s, markers.get(s["sid"]))
            if bw: boss_sids.add(s["sid"])
            for tr, a, b in bw: self.bosses[tr].append((s, a, b))
        for s in sessions:
            if s["sid"] in boss_sids:
                for T, sock, _, _ in s["xmsgs"]:
                    if sock in socks: continue                # another boss, not a worker
                    for tr, a, b in boss_windows(s, markers.get(s["sid"])):
                        if a <= T <= b: self.worker_msgs[tr].append(T)
                continue
            ev = [(T, socks.get(sock) or trk) for T, sock, trk, _ in s["xmsgs"] if socks.get(sock) or trk]
            for i, (T, tr) in enumerate(ev):
                self.workers[tr].append((s, T, ev[i + 1][0] if i + 1 < len(ev) else s["end"]))

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
    ev, wh, tok = [], collections.Counter(), collections.Counter()
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
    asks = 0
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
    days = (end - start) / 86400
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
    live = []
    for s, a, b in index.workers.get(track, []):
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
    if not previous or abs(previous["end"] - week["start"]) > 86400:
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
        creds = dict(l.strip().split("=", 1) for l in envf.read_text().splitlines() if "=" in l and not l.startswith("#"))
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
    return [p for p in root.glob("*/*.jsonl") if p.stat().st_mtime >= since]


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
    sessions = [r for p in discover(cfg, first) if (r := scan_session(p, known))]
    socks = resolve_sockets(sessions, state.get("socks"))
    idx = Index(sessions, markers(cfg), socks)
    history = state.get("weeks", [])
    problems = failed = 0
    for w in range(weeks):
        wend = end - (weeks - 1 - w) * 7 * 86400
        week = measure_window(idx, wend - 7 * 86400, wend)
        label = dt.datetime.fromtimestamp(wend).strftime("%Y-%m-%d")
        prior = [h for h in history if h["end"] < wend]
        fails, flags = judge(week, prior[-1] if prior else None)
        text = render(week, label, fails, flags)
        if not fails:                       # a week that could not be measured is no baseline
            history = [h for h in history if h["end"] != wend] + [week]
            history = sorted(history, key=lambda h: h["end"])[-HISTORY_WEEKS:]
        if not dry:
            state = dict(socks=socks, tracks=sorted(set(idx.tracks()) | set(state.get("tracks", []))), weeks=history)
            write_outputs(cfg, label, week, text, state)
        else:
            print(text)
        if fails or flags:
            problems += 1
            failed += bool(fails)
            sent = alert("boss-efficiency week ending %s: %s" % (label, "; ".join(
                ["FAILED " + f for f in fails] + flags)), dry)
            failed += (not sent) and not dry
    return (2 if failed else 0), problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--end", help="end of the last window, ISO date (default: now)")
    ap.add_argument("--weeks", type=int, default=1, help="how many weekly windows, oldest first (backfill)")
    a = ap.parse_args(argv)
    end = dt.datetime.fromisoformat(a.end).timestamp() if a.end else dt.datetime.now().timestamp()
    rc, problems = run(boss_store.config_dir(), end, a.weeks, os.environ.get("DRY_RUN") == "1")
    print("boss-efficiency: %d window(s) with something to say" % problems)
    return rc


if __name__ == "__main__":
    sys.exit(main())
