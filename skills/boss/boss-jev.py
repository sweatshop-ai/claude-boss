#!/usr/bin/env python3
"""boss-jev: keep a /boss session asleep for worker events that need nothing (#77).

A boss turn costs its whole context whether it reads a full report or one line
(the owner, 2026-09-18), so the saving is in turns that never start. This is a
UserPromptSubmit hook, active only in sessions registered as a boss with a
track. For a cross-session message or idle notice from one of the boss's own
workers it decides, before the boss's turn starts:

  ABSORB    the event needs nothing: archive it and block the turn
  ESCALATE  the worker is blocked on the owner: tracker line with a ladder marker,
            pane emoji, boss-alert 0, then wake the boss to name the action
  WAKE      everything else, with one judgment line, and a restart proposal
            when a finished worker passes every restart gate

Idle notices are decided by code alone. Worker messages are judged by Jev on the
three questions #76 measured (task_complete, needs_owner, redirected); code
decides the rest. Every failure prints nothing, which lets the prompt through
and wakes the boss.

Plan and evidence: ~/.claude/plans/2026-09-18-boss-jev-hook.md (revision 5).

Files, under ~/.claude/pm/.pulse/ unless noted:
  jev.mode          advisory (default: logs what it would do, changes nothing) | armed
  jev.egress        "on" lets worker messages go to TypeSafe. the owner's switch.
  jev-<sid>.json    state: dispatch and worker memory, escalations, counters (0600)
  jev.log           one line per decision (0600)
  ~/.claude/pm/<track>.jev-archive.md   every judged event with its body (0600)

Usage:
  boss-jev.py hook                            the hook (payload on stdin)
  boss-jev.py install-hook [--print]          add the hook to settings.json
  boss-jev.py footer --task N [--repos A,B]   the handoff footer for this session
  boss-jev.py stats [--days N]                counters per day
  boss-jev.py --selftest                      run test_boss_jev.py

Test overrides: CLAUDE_CONFIG_DIR, JEV_MODE, JEV_EGRESS, FAKE_JEV=<json>, DRY_RUN=1.
"""
import datetime
import fcntl
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import traceback
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
PM = CFG / "pm"
PULSE = PM / ".pulse"
MARKERS = PM / ".boss-sessions"
SESSIONS = CFG / "sessions"
PROJECTS = CFG / "projects"
SETTINGS = CFG / "settings.json"
MODE_FILE = PULSE / "jev.mode"
EGRESS_FILE = PULSE / "jev.egress"
LOG_FILE = PULSE / "jev.log"
SCORE_FILE = Path(os.environ.get("BOSS_JEV_SCORE", str(PULSE / "jev-score.json")))
COLORS = Path(os.environ.get("BOSS_COLORS", str(CFG / "skills" / "afk" / "colors.json")))
BOSS_ALERT = HERE / "bin" / "boss-alert"
BEJ_PATH = Path(os.environ.get("BOSS_EVENT_JEV",
                               str(HERE.parent.parent / "tools" / "boss-event-jev.py")))
PANES_PATH = HERE / "boss-panes.py"
KEY_FILE = Path(os.environ.get("BOSS_TYPESAFE_ENV",
                               str(Path.home() / ".config" / "tiroir" / "typesafe.env")))

DEADLINE_S = 4.0          # settings timeout is 8 s; this leaves half of it spare
HI, LO = 0.85, 0.15       # "decided" means at or beyond one of these
ARM_ACC = 0.95            # arming: accuracy at conf >= 0.85 on the two gate questions
CTX_MIN, COST_MIN = 400_000, 90_000
MAX_SCAN = 2 * 1024 * 1024
TAIL = 4 * 1024 * 1024
LATE_CHILD_S = 120
PROPOSAL_COOLDOWN_S = 3600
QIDS = ("task_complete", "needs_owner", "redirected")
W_IN, W_CACHE_WRITE, W_CACHE_READ, W_OUT = 1.0, 1.25, 0.10, 5.0   # as boss-panes.py


class Refused(Exception):
    """A decision to pass the prompt through, with the reason for the log."""


class LockHeld(Refused):
    """Another run of the hook holds this boss's state. The event passes through
    unjudged, and in armed mode says so, so it is not taken for a handled one."""


_AFTER_OUTPUT = []


def finish_delivery():
    """Mark escalation reports as reported, after the output carrying them has
    been written and flushed. A run that dies before this leaves them pending,
    and the next run reports them again: repeated, never lost."""
    while _AFTER_OUTPUT:
        lock_path, state_path, keys = _AFTER_OUTPUT.pop(0)
        try:
            with open(lock_path, "a") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                st = json.loads(Path(state_path).read_text(encoding="utf-8"))
                for k in keys:
                    if k in st.get("escalations", {}):
                        st["escalations"][k]["reported"] = True
                        st["escalations"][k]["reports"] = st["escalations"][k].get("reports", 0) + 1
                write_private(state_path, json.dumps(st, ensure_ascii=False))
        except (OSError, ValueError):
            pass


# ------------------------------------------------------------------ small tools

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_bej = None


def bej():
    """tools/boss-event-jev.py: the measured questions, redact() and leaks()."""
    global _bej
    if _bej is None:
        _bej = _load("boss_event_jev", BEJ_PATH)
    return _bej


def panes_mod():
    return _load("boss_panes", PANES_PATH)


def stamp(t=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def iso_epoch(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def write_private(path, text):
    path = Path(path)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(str(tmp), str(path))
    os.chmod(str(path), 0o600)


def append_private(path, text):
    """One O_APPEND write; the file is 0600, tightened if it was found wider."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise OSError("%s is not a regular file of this user" % path)
        if st.st_mode & 0o077:
            os.fchmod(fd, 0o600)
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def log(msg):
    try:
        PULSE.mkdir(parents=True, exist_ok=True)
        append_private(LOG_FILE, "%s %s\n" % (stamp(), msg.replace("\n", " ")[:600]))
    except OSError:
        pass


def first_word(path):
    try:
        return Path(path).read_text(encoding="utf-8").split()[0].strip().lower()
    except (OSError, IndexError):
        return ""


def dry():
    return os.environ.get("DRY_RUN") == "1"


# --------------------------------------------------------------- mode, arming

def arming():
    """(ok, why): the #76 score passes >= 0.95 at conf >= 0.85 on both gates."""
    try:
        d = json.loads(SCORE_FILE.read_text(encoding="utf-8").splitlines()[0])
        why = []
        for q in ("task_complete", "needs_owner"):
            s = d["questions"][q]
            acc = s.get("accuracy_conf_ge_0.85")
            if acc is None or acc < ARM_ACC or not s.get("n_conf_ge_0.85"):
                why.append("%s %s" % (q, acc))
        return (not why), ("score below %.2f: %s" % (ARM_ACC, ", ".join(why)) if why else "score passes")
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        return False, "no readable score file (%s)" % type(e).__name__


def effective_mode():
    m = (os.environ.get("JEV_MODE") or first_word(MODE_FILE) or "advisory").lower()
    if m != "armed":
        return "advisory", "mode %s" % m
    ok, why = arming()
    return ("armed", why) if ok else ("advisory", "armed refused: " + why)


def egress_on():
    return (os.environ.get("JEV_EGRESS") or first_word(EGRESS_FILE)) == "on"


# ------------------------------------------------------------------- sessions

def proc_start(pid):
    try:
        data = Path("/proc/%d/stat" % int(pid)).read_bytes()
        return data[data.rindex(b")") + 2:].split()[19].decode()
    except (OSError, ValueError, IndexError):
        return None


def session_by_pid(pid):
    """The live session record of a pid, or None. procStart must match, so a
    reused pid never inherits a dead worker's identity."""
    try:
        rec = json.loads((SESSIONS / ("%d.json" % int(pid))).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    start = proc_start(pid)
    if start is None or not rec.get("procStart") or str(rec["procStart"]) != start:
        return None                          # no procStart, no identity (plan R10.3)
    return rec


def live_sessions():
    out = []
    if not SESSIONS.is_dir():
        return out
    for p in SESSIONS.glob("*.json"):
        try:
            pid = int(p.stem)
        except ValueError:
            continue
        rec = session_by_pid(pid)
        if rec:
            out.append(rec)
    return out


def pane_of(rec):
    tm = (rec or {}).get("tmux") or ""
    return tm.rsplit(".", 1)[-1] if "%" in tm else ""


def tmux(args, timeout=1.0):
    if dry() and args and args[0] == "set-option":
        log("(dry run) tmux " + " ".join(args))
        return ""
    try:
        r = subprocess.run(["tmux"] + args, capture_output=True, text=True, timeout=max(0.2, timeout))
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def pane_info(pane, timeout=1.0):
    """(owner, coordinate) of a pane, or (None, None)."""
    out = tmux(["display-message", "-p", "-t", pane,
                "#{pane_id}\t#{@boss_pane}\t#{session_name}:#{window_index}.#{pane_index}"], timeout)
    if not out:
        return None, None
    parts = out.rstrip("\n").split("\t")
    if len(parts) < 3 or parts[0] != pane:
        return None, None
    return parts[1].strip(), parts[2]


def transcript_of(rec):
    cwd, sid = rec.get("cwd") or "", rec.get("sessionId") or ""
    if not cwd or not sid:
        return None
    return PROJECTS / re.sub(r"[^a-zA-Z0-9]", "-", cwd) / ("%s.jsonl" % sid)


TRACK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def regular_mine(path):
    """True for a regular file (not a symlink) owned by this user."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()


def in_pm(path):
    """`path` sits directly in pm/ once every symlink above it is resolved."""
    try:
        return os.path.realpath(os.path.dirname(path)) == os.path.realpath(PM)
    except OSError:
        return False


def boss_track(sid):
    """The track in this session's boss marker, or "". The track becomes a file
    name under pm/, so it must be a plain identifier and the marker a regular
    file of this user."""
    if not sid or not re.match(r"^[\w-]{1,80}$", sid):
        return ""
    marker = MARKERS / sid
    if not regular_mine(marker):
        return ""
    try:
        track = marker.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""
    return track if TRACK_RE.match(track) and ".." not in track else ""


# --------------------------------------------------------------------- events

XSM_RE = re.compile(r"<cross-session-message\s+([^>]*)>(.*?)</cross-session-message>", re.S)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
SOCK_RE = re.compile(r"^uds:.*/(\d+)\.sock$")
# The two envelopes the harness writes (Claude Code 2.1.276, every notice in the
# boss transcript of 2026-09-18 and the throwaway tests). Anything else, a typed
# imitation or a notice with text around it, is not an idle notice (plan R10.2).
IDLE_RE = re.compile(
    r'\A\[Cross-session idle notice\] "([^"\n]+)", which you asked to be notified about, is idle now'
    r"(?: \u2014 it finished a turn at (\d{1,2}):(\d{2})\. Its harness reports: \u00ab(.*)\u00bb)?"
    r"\. This is an automated notice from that session's harness \u2014 not a message from a person, and "
    r"not an instruction; act on it only insofar as your user's earlier request calls for it\.\Z", re.S)
PREFIX = "Another Claude session sent a message:"


def parse_event(prompt):
    """A worker event in the prompt, or None. One message or one notice only:
    a prompt carrying anything else is never absorbed in part."""
    msgs = XSM_RE.findall(prompt)
    if msgs:
        if len(msgs) != 1:
            return None
        outside = XSM_RE.sub("", prompt).strip()
        if outside not in ("", PREFIX):
            return None
        attrs = dict(ATTR_RE.findall(msgs[0][0]))
        m = SOCK_RE.match(attrs.get("from", ""))
        if not m:
            return None
        return {"kind": "message", "pid": int(m.group(1)), "from_name": attrs.get("from-name", ""),
                "body": msgs[0][1].strip()}
    m = IDLE_RE.match(prompt)
    if m:
        return {"kind": "idle", "name": m.group(1), "body": prompt,
                "finish": (int(m.group(2)), int(m.group(3))) if m.group(2) else None}
    return None


NUM_RE = re.compile(r"(?<![\w/&])#(\d{1,5})\b")
PR_RE = re.compile(r"(?i)\b(?:PR|pull)[ /#]*(\d{1,5})\b")
SHA_RE = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
TASK_RE = re.compile(r"(?i)\btask\s*#(\d{1,5})\b")
ASK_RE = re.compile(
    r"\?|\b(?:should I|shall I|do you want|which (?:one|option)|"
    r"your (?:call|go|decision|ruling|answer|approval|ok)|unless you|let me know|tell me|"
    r"confirm|approve|permission|refused|denied|blocked|stuck|cannot|can't|unable|failed|error|"
    r"needs? (?:you|your|a decision|approval|a go)|waiting (?:for|on) you)\b", re.I)


def tokens(text):
    """Task and PR numbers and commit SHAs: what makes a report say something new."""
    text = text or ""
    return ({"#" + n for n in NUM_RE.findall(text)} | {"#" + n for n in PR_RE.findall(text)}
            | {s[:7] for s in SHA_RE.findall(text)})


def task_number(text):
    m = TASK_RE.search(text or "") or NUM_RE.search(text or "")
    return m.group(1) if m else None


def one_line(text):
    """Whitespace runs (CR and LF included) to one space, other control
    characters removed: nothing written into the tracker can start a line."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", "", re.sub(r"\s+", " ", text or "")).strip()


def first_sentence(text, limit=160):
    s = re.split(r"(?<=[.!?])\s", one_line(text), maxsplit=1)[0]
    return re.sub(r'[\[\]"]', "", s)[:limit]


REPORT_MAX, REPORT_WINDOW_S = 6, 7200


def ladder_ack(track, rec):
    """True when the boss has acted on the escalation's ladder line: its ask= is
    no longer the placeholder, it carries cleared=, or the hook wrote it and it
    is gone. A line the hook could not write counts as acted on once the boss
    has added it with the action named. This is the only acknowledgement there
    is: written output is not delivered output (plan R9.2, R10.1)."""
    try:
        body = (PM / ("%s.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return False
    line = next((l for l in body.splitlines() if "[ladder id=%s " % rec.get("id") in l), None)
    if line is None:
        step = str((rec.get("steps") or {}).get("tracker", ""))
        return step.startswith("done") and "dry run" not in step
    return "cleared=" in line or 'ask="(boss names it)"' not in line


# ------------------------------------------------------------------ decisions

def decide_idle(mem, finish_epoch, status):
    """(action, reason) for an idle notice. Code only."""
    if status == "busy":
        return "absorb", "worker busy again, the notice is stale"
    if mem.get("reported"):
        return "absorb", "report already delivered since the last dispatch"
    d = mem.get("dispatch_ts") or 0
    if finish_epoch and d and d > finish_epoch + 59:
        return "absorb", "finished before the last dispatch, stale"
    return "wake", "idle with no report since the last dispatch"


def decide_message(p, mem, report, ctx, cost):
    """(action, reason) for a worker message from Jev's three probabilities.
    action: escalate | finished | wake. A message is never absorbed in this
    release (plan R5.1: no word list proves a report needs no reply, and the
    sample holds no case to validate one). The rule that would absorb it is
    still evaluated and tagged `absorb-candidate` in the reason, so a later
    sample can measure it before it is switched on."""
    po, pt, pr = p["needs_owner"], p["task_complete"], p["redirected"]
    if po >= HI:
        return "escalate", "needs_owner %.2f" % po
    if pr >= 0.5:
        return "wake", "redirected %.2f: the worker says OWNER gave it a new instruction" % pr
    decided = (pt >= HI or pt <= LO) and po <= LO and pr <= LO
    ask = ASK_RE.search(report or "")
    new = sorted(tokens(report) - set(mem.get("known") or []))
    heavy = ctx >= CTX_MIN or cost >= COST_MIN
    cand = decided and not ask and not new and not heavy and (pt <= LO or bool(mem.get("finished")))
    tag = " [absorb-candidate]" if cand else ""
    if pt >= HI:
        return "finished", "task_complete %.2f%s" % (pt, tag)
    if cand:
        return "wake", "interim, nothing new" + tag
    why = []
    if not decided:
        why.append("undecided")
    if ask:
        why.append("asks or reports a block (%r)" % ask.group(0))
    if new:
        why.append("new " + ",".join(new[:6]))
    if heavy:
        why.append("CTX %dk" % (ctx // 1000))
    return "wake", "; ".join(why) or "first finished report"


def absorb_ready(mem, scan_complete):
    if not scan_complete:
        return False, "dispatch memory incomplete (first run, rescan or catch-up)"
    if not mem.get("dispatch_ts"):
        return False, "no known dispatch to this worker"
    return True, ""


def remember(mem, report, p):
    mem.setdefault("known", [])
    mem["known"] = sorted(set(mem["known"]) | tokens(report))[-300:]
    mem["reported"] = True
    if p and p.get("task_complete", 0) >= HI:
        mem["finished"] = True


# --------------------------------------------------------- transcript reading

def tail_records(path, nbytes=TAIL):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - nbytes))
            data = fh.read()
    except (OSError, TypeError):
        return []
    lines = data.split(b"\n")
    if size > nbytes:
        lines = lines[1:]
    out = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def usage(records):
    """(context tokens of the last turn, priced cost per turn over the last 200)."""
    rows = []
    for d in records:
        u = (d.get("message") or {}).get("usage") if isinstance(d.get("message"), dict) else None
        if u:
            rows.append((u.get("input_tokens", 0), u.get("cache_creation_input_tokens", 0),
                         u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0)))
    if not rows:
        return 0, 0
    last = rows[-1]
    tail = rows[-200:]
    cost = sum(r[0] * W_IN + r[1] * W_CACHE_WRITE + r[2] * W_CACHE_READ + r[3] * W_OUT
               for r in tail) / len(tail)
    return last[0] + last[1] + last[2], cost


def send_messages(d):
    """SendMessage tool_uses in an assistant record: [(to, message)]."""
    if d.get("type") != "assistant":
        return []
    out = []
    for c in (d.get("message") or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "SendMessage":
            inp = c.get("input") or {}
            msg = inp.get("message")
            if isinstance(msg, str) and msg.strip():
                out.append((str(inp.get("to") or ""), msg))
    return out


def subscriptions(d):
    """`to` of every SendMessage in an assistant record that asked for an idle notice."""
    if d.get("type") != "assistant":
        return []
    return [str((c.get("input") or {}).get("to") or "")
            for c in (d.get("message") or {}).get("content") or []
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "SendMessage"
            and (c.get("input") or {}).get("notify_when_idle")]


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def report_turn(records, body):
    """(index of the record whose SendMessage carries this report, its epoch)."""
    key = norm(body)[:200]
    if not key:
        return None, 0
    for i in range(len(records) - 1, -1, -1):
        for _, msg in send_messages(records[i]):
            if norm(msg)[:200] == key:
                return i, iso_epoch(records[i].get("timestamp"))
    return None, 0


def is_input(d):
    """A record that brought the worker something new to do."""
    t = d.get("type")
    if t == "attachment":
        return (d.get("attachment") or {}).get("type") == "queued_command"
    if t != "user":
        return False
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    if isinstance(c, list):
        return any(isinstance(x, dict) and x.get("type") == "text" for x in c)
    return False


def pin_of(records):
    last = None
    for d in records:
        t = d.get("type")
        if t in ("user", "assistant") or (
                t == "attachment" and (d.get("attachment") or {}).get("type") == "queued_command"):
            last = d.get("uuid") or last
    return last


# ------------------------------------------------------------------ the hook

class Hook:
    def __init__(self, payload, sid, track, deadline):
        self.payload, self.sid, self.track, self.deadline = payload, sid, track, deadline
        self.prompt = payload.get("prompt") or ""
        # One id per occurrence. The payload has nothing per occurrence (a message
        # attached mid-turn even shares the turn's prompt_id), and no re-delivery
        # was seen in testing, so every run is its own event (plan R8.1/R9.1).
        self.digest = uuid.uuid4().hex
        self.id8 = self.digest[:12]               # shown, and the ladder id
        self.state_path = PULSE / ("jev-%s.json" % sid)
        self.lock_path = PULSE / ("jev-%s.lock" % sid)
        self.archive_path = PM / ("%s.jev-archive.md" % track)
        self.st = None
        self.mode = "advisory"
        self._live = None
        self.delivered = []          # escalation digests whose report is in this run's output

    # -- time and state

    def remaining(self):
        return self.deadline - time.monotonic()

    def live(self):
        if self._live is None:
            self._live = live_sessions()
        return self._live

    def load_state(self):
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(st, dict):
                raise ValueError("not an object")
        except FileNotFoundError:
            st = {}
        except (OSError, ValueError) as e:
            log("state %s unreadable (%s): rebuilt from the end of the transcript" % (self.state_path.name, e))
            st = {}
        for k in ("dispatch", "workers", "escalations", "counters", "proposals"):
            if not isinstance(st.get(k), dict):
                st[k] = {}
        return st

    def save_state(self):
        write_private(self.state_path, json.dumps(self.st, ensure_ascii=False))

    def count(self, key):
        day = time.strftime("%Y-%m-%d")
        c = self.st["counters"].setdefault(day, {})
        c[key] = c.get(key, 0) + 1
        for old in sorted(self.st["counters"])[:-30]:
            del self.st["counters"][old]

    # -- the boss transcript: dispatch memory

    def scan_boss(self):
        """Read the boss transcript from the saved offset. True when this run
        started from a known position and reached the end of the file."""
        path = self.payload.get("transcript_path") or ""
        t = self.st.setdefault("scan", {})
        try:
            s = os.stat(path)
        except OSError:
            return False
        fresh = t.get("path") != path or t.get("ino") != s.st_ino or t.get("dev") != s.st_dev \
            or s.st_size < t.get("offset", 0)
        if fresh:
            first = t.get("path") != path
            start = max(0, s.st_size - MAX_SCAN) if first else 0
            t.clear()
            t.update(path=path, ino=s.st_ino, dev=s.st_dev, offset=start)
        off = t["offset"]
        with open(path, "rb") as fh:
            fh.seek(off)
            data = fh.read(MAX_SCAN)
        if not data:
            return (not fresh) and off >= s.st_size
        cut = data.rfind(b"\n")
        if cut < 0:
            t["offset"] = off + len(data) if len(data) >= MAX_SCAN else off
            return False
        lines = data[:cut].split(b"\n")
        if off > 0 and fresh:
            lines = lines[1:]                     # seeded from the middle of a line
        for raw in lines:
            if b"SendMessage" not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            ts = iso_epoch(d.get("timestamp"))
            for to, msg in send_messages(d):
                self.note_dispatch(to, msg, ts)
            for to in subscriptions(d):
                self.note_subscription(to, ts)
        t["offset"] = off + cut + 1
        if len(self.st["dispatch"]) > 300:
            for k in sorted(self.st["dispatch"], key=lambda k: self.st["dispatch"][k]["ts"])[:-300]:
                del self.st["dispatch"][k]
        return (not fresh) and t["offset"] >= s.st_size

    def bind(self, to, ts):
        """The session id a SendMessage `to` meant at time `ts`, or None.

        Read later than it was sent, a name may since belong to another session:
        a restart keeps the name. So a name binds only to the one live session
        that already had it and was already running at `ts`; a socket address
        binds to its pid's live session if that session started before `ts`.
        Anything else stays unbound and is never attributed later."""
        to = to.split(" [")[0].strip()
        m = SOCK_RE.match(to)
        if m:
            recs = [session_by_pid(int(m.group(1)))]
        else:
            recs = [r for r in self.live() if (r.get("name") or "").casefold() == to.casefold()]
        ok = [r for r in recs if r and ts and (r.get("startedAt") or 0) / 1000.0 <= ts
              and (r.get("nameSince") or r.get("startedAt") or 0) / 1000.0 <= ts]
        return ok[0].get("sessionId") if len(ok) == 1 and len(recs) == 1 else None

    def note_dispatch(self, to, msg, ts):
        sid = self.bind(to, ts)
        if not sid:
            return
        self.st["dispatch"][sid] = {"ts": ts, "task": task_number(msg), "text": msg[:4000],
                                    "tokens": sorted(tokens(msg))}

    def note_subscription(self, to, ts):
        sid = self.bind(to, ts)
        if sid:
            self.st.setdefault("subs", {})[sid] = ts

    def dispatch_for(self, w):
        return self.st["dispatch"].get(w["sid"])

    def worker_mem(self, w):
        disp = self.dispatch_for(w)
        mem = self.st["workers"].get(w["sid"]) or {}
        if disp and disp["ts"] != mem.get("dispatch_ts"):
            mem = {"dispatch_ts": disp["ts"], "task": disp["task"], "known": list(disp["tokens"]),
                   "reported": False, "finished": False}
        mem["name"], mem["seen"] = w["name"], time.time()
        self.st["workers"][w["sid"]] = mem
        if len(self.st["workers"]) > 100:
            for k in sorted(self.st["workers"], key=lambda k: self.st["workers"][k].get("seen", 0))[:-100]:
                del self.st["workers"][k]
        return mem, disp

    # -- who

    def boss_pane(self):
        me = [r for r in self.live() if r.get("sessionId") == self.sid]
        return pane_of(me[0]) if len(me) == 1 else ""

    def worker(self, ev, boss_pane):
        if ev["kind"] == "message":
            rec = session_by_pid(ev["pid"])
            cands = [rec] if rec else []
        else:
            cands = [r for r in self.live() if (r.get("name") or "") == ev["name"]]
            if len(cands) != 1 or self.st.get("subs", {}).get(cands[0].get("sessionId")) is None:
                return None                       # renamed, reused or never subscribed: wake
        mine = []
        for rec in cands:
            pane = pane_of(rec)
            if not pane or pane == boss_pane or rec.get("sessionId") == self.sid:
                continue
            owner, coord = pane_info(pane, min(1.0, self.remaining() - 2.0))
            if owner == boss_pane:
                mine.append((rec, pane, coord))
        if len(mine) != 1:
            return None
        rec, pane, coord = mine[0]
        return {"pid": int(rec["pid"]), "procStart": rec.get("procStart"), "sid": rec.get("sessionId") or "",
                "name": one_line(re.sub(r"[^\w .-]", "", rec.get("name") or "worker"))[:40] or "worker",
                "pane": pane, "coord": re.sub(r"[^\w:.%-]", "", coord or pane), "cwd": rec.get("cwd") or "",
                "status": rec.get("status") or "", "transcript": transcript_of(rec)}

    # -- Jev

    def roster_row(self, name):
        try:
            for line in (PM / ("%s.md" % self.track)).read_text(encoding="utf-8").splitlines():
                if line.startswith("| ") and line[2:].lower().startswith(name.lower()):
                    return line[:600]
        except OSError:
            pass
        return ""

    def request(self, w, ev, disp, ctx, handoff):
        """The Jev request. The worker's own names (session name and from-name)
        become the word `worker` everywhere, not just in the name field: reports
        usually start with them. Other names are left to redact()'s list."""
        b = bej()
        names = {n for n in (w.get("name"), ev.get("from_name")) if n and n.lower() != "worker"}
        anon = lambda t: re.sub(r"(?i)\b(?:%s)\b" % "|".join(re.escape(n) for n in names), "worker", t or "") \
            if names else (t or "")
        row = {"worker": "worker", "kind": "message", "state": {
            "dispatch": anon((disp or {}).get("text")), "report": anon(ev["body"]),
            "tracker_note": anon(self.roster_row(w["name"])), "worker_context_tokens": ctx or None,
            "handoff_on_disk": handoff}}
        state = redact_all(b.build_state(row))
        req = {"model": b.MODEL, "state": state, "questions": {q: b.QUESTIONS[q] for q in QIDS}}
        found = b.leaks(req)
        if found:
            raise Refused("leak check: " + ",".join(sorted({n for n, _ in found})))
        return req

    def ask_jev(self, req):
        timeout = min(2.0, self.remaining() - 1.0)
        if timeout < 0.3:
            raise Refused("no time left for Jev")
        fake = os.environ.get("FAKE_JEV")
        answers = fake_jev(fake, req, timeout) if fake else post_jev(req, timeout)
        p = {}
        for q in QIDS:
            v = float((answers.get(q) or {}).get("noul"))
            if not 0.0 <= v <= 1.0:
                raise Refused("Jev answer out of range for " + q)
            p[q] = v
        return p

    # -- effects

    def archive(self, w, ev, action, reason, p):
        if not in_pm(self.archive_path) or (self.archive_path.exists() or self.archive_path.is_symlink()) \
                and not regular_mine(self.archive_path):
            raise OSError("archive is not a regular file of this user in pm/")
        nums = "tc %.2f · owner %.2f · redir %.2f" % (p["task_complete"], p["needs_owner"], p["redirected"]) \
            if p else "tc - · owner - · redir -"
        head = "### %s %s (%s) %s — %s — %s — %s\n\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), w["name"], w["coord"], action, nums, reason, self.id8)
        body = "".join("> %s\n" % l for l in ev["body"].splitlines()) + "\n"
        append_private(self.archive_path, head + body)

    def report_due(self, rec):
        """An escalation whose report must ride on this run's output: until the
        boss acts on its ladder line (R9.2), or, with no line to go by, until an
        output carrying it has been written; at most REPORT_MAX times, within
        REPORT_WINDOW_S of T+0."""
        if rec.get("acked") or rec.get("reports", 0) >= REPORT_MAX or time.time() - rec.get("ts", 0) > REPORT_WINDOW_S:
            return False
        if ladder_ack(self.track, rec):
            rec["acked"] = True
            return False
        return True

    def escalate(self, w, ev, p):
        """The T+0 steps for this occurrence."""
        rec = {"ts": time.time(), "id": self.id8, "worker": w["name"], "coord": w["coord"], "steps": {},
               "reported": False, "reports": 0}
        self.st["escalations"][self.digest] = rec
        for k in sorted(self.st["escalations"], key=lambda k: self.st["escalations"][k].get("ts", 0))[:-500]:
            if self.st["escalations"][k].get("reported"):
                del self.st["escalations"][k]
        steps = (("tracker", 0.3, lambda: self.tracker_line(w, ev)),
                 ("emoji", 0.3, lambda: self.emoji(w)),
                 ("slack", 0.9, lambda: self.slack(w)))
        for name, need, fn in steps:
            if self.remaining() < need:
                rec["steps"][name] = "not done: no time left"
                continue
            rec["steps"][name] = "started"
            self.save_state()
            try:
                rec["steps"][name] = fn()
            except Exception as e:           # noqa: BLE001 - any failure is reported, never raised
                rec["steps"][name] = "failed: %s" % (str(e)[:120] or type(e).__name__)
            self.save_state()
        return rec

    def tracker_line(self, w, ev):
        t0 = datetime.datetime.now().astimezone().replace(second=0, microsecond=0)
        nxt = t0 + datetime.timedelta(minutes=5)
        line = ('- boss-jev %s: %s (%s) blocked on OWNER: %s — T+0 %s [ladder id=%s t0=%s last=0 next=%s '
                'pane=%s ask="(boss names it)"]' % (
                    self.id8, w["name"], w["coord"], first_sentence(ev["body"]), t0.strftime("%Y-%m-%d %H:%M"),
                    self.id8, t0.isoformat(timespec="minutes"), nxt.isoformat(timespec="minutes"), w["coord"]))
        esc = ((self.st or {}).get("escalations") or {}).get(self.digest)
        if esc is not None:
            esc["line"] = line
        if dry():
            log("(dry run) tracker line: " + line)
            return "done (dry run)"
        return tracker_add(PM / ("%s.md" % self.track), line, "[ladder id=%s" % self.id8, self.deadline)

    def emoji(self, w):
        rec = session_by_pid(w["pid"])
        owner, _ = pane_info(w["pane"], min(0.5, self.remaining() - 0.2))
        if not rec or rec.get("sessionId") != w["sid"] or pane_of(rec) != w["pane"] or owner != self.boss:
            return "not done: the pane changed hands"
        e = client_emoji(w["cwd"], self.track)
        if not e:
            return "not done: no client emoji for this cwd"
        title = (tmux(["display-message", "-p", "-t", w["pane"], "#{@custom_title}"], 0.5) or "").strip()
        if title.startswith(e):
            return "done (already set)"
        if tmux(["set-option", "-p", "-t", w["pane"], "@custom_title", "%s %s" % (e, title or w["name"])],
                0.5) is None:
            return "failed: tmux"
        return "done"

    def slack(self, w):
        b = bej()
        text = b.redact("boss-jev: a worker in pane %s is blocked on OWNER (event %s), see the tracker"
                        % (w["coord"], self.id8))
        if b.leaks({"text": text}):
            return "not done: the alert text failed the leak check"
        if dry():
            log("(dry run) boss-alert 0 " + text)
            return "done (dry run)"
        timeout = min(2.5, self.remaining() - 0.4)
        r = subprocess.run([str(BOSS_ALERT), "0", text], capture_output=True, text=True, timeout=timeout)
        return "done" if r.returncode == 0 else "failed: boss-alert exit %d" % r.returncode

    # -- restart gates

    def restart_gates(self, w, ev, p, ctx, cost, mem, records):
        """(ok, facts, failed gate). A gate not evaluated in time fails."""
        facts = {}

        def need(t=0.3):
            if self.remaining() < t:
                raise Refused("not evaluated in time")

        try:
            need()
            rec = session_by_pid(w["pid"])
            if not rec or rec.get("sessionId") != w["sid"] or rec.get("status") != "idle":
                return False, facts, "status is %r, not idle" % ((rec or {}).get("status"),)
            if ctx < CTX_MIN and cost < COST_MIN:
                return False, facts, "CTX %dk and COST/TURN %dk under the thresholds" % (ctx // 1000, cost // 1000)
            facts["ctx"] = "CTX %dk, COST/TURN %dk" % (ctx // 1000, cost // 1000)
            i, sent_at = report_turn(records, ev["body"])
            if i is None:
                return False, facts, "its report is not in the last 4 MB of its transcript"
            if any(is_input(d) for d in records[i + 1:]):
                return False, facts, "it took input after the report"
            facts["pin"] = pin_of(records)
            if not facts["pin"]:
                return False, facts, "no complete conversation record in the last 4 MB to pin"
            disp = self.dispatch_for(w)
            if disp and disp["ts"] > sent_at:
                return False, facts, "the boss sent it something after the report"
            if p["redirected"] >= 0.5:
                return False, facts, "redirected %.2f" % p["redirected"]
            last = self.st["proposals"].get(w["pane"], 0)
            if time.time() - last < PROPOSAL_COOLDOWN_S:
                return False, facts, "a restart was proposed for this pane %d min ago" % ((time.time() - last) // 60)
            need()
            ok, why, repos, hand = footer_gate(w, disp)
            if not ok:
                return False, facts, why
            facts["handoff"] = hand
            need(0.5)
            ok, why = repos_gate(w["cwd"], repos, max(0.2, min(1.0, self.remaining() - 0.3)))
            if not ok:
                return False, facts, why
            facts["repos"] = ",".join(repos) or "none"
            need()
            ok, why = evidence_gate(ev["body"], repos, max(0.2, min(0.5, self.remaining() - 0.3)))
            if not ok:
                return False, facts, why
            ok, why = children_gate(w["pid"])
            if not ok:
                return False, facts, why
        except Refused as e:
            return False, facts, str(e)
        return True, facts, ""

    def run_pending(self):
        """Any other prompt of an armed boss (the owner typing, say) carries the
        escalation reports still due, and is never blocked (plan R11.2)."""
        if effective_mode()[0] != "armed" or not self.state_path.exists():
            return None
        with open(self.lock_path, "a") as lockf:
            try:
                fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return None
            self.st = self.load_state()
            pending = [k for k, r in self.st["escalations"].items() if self.report_due(r)]
            out = self.pending_only(pending) if pending else None
            self.save_state()
            if out is not None:
                _AFTER_OUTPUT.append((self.lock_path, self.state_path, list(self.delivered)))
            return out

    def pending_only(self, pending):
        """The event passes as it is, carrying only the escalation reports still due."""
        lines = []
        for k in pending:
            r = self.st["escalations"][k]
            lines.append(escalation_report(r, interrupted=not r.get("reports")))
            self.delivered.append(k)
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}

    # -- main

    def run(self, ev):
        PULSE.mkdir(parents=True, exist_ok=True)
        lockf = open(self.lock_path, "a")
        try:
            while True:
                try:
                    fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if self.remaining() < 3.0:
                        raise LockHeld("state lock held by another run")
                    time.sleep(0.05)
            self.st = self.load_state()
            self.mode, why = effective_mode()
            out = self.decide(ev, why)
            self.save_state()
            if out is not None and self.delivered:
                _AFTER_OUTPUT.append((self.lock_path, self.state_path, list(self.delivered)))
            return out
        finally:
            lockf.close()

    def decide(self, ev, mode_why):
        complete = self.scan_boss()
        self.boss = self.boss_pane()
        w = self.worker(ev, self.boss) if self.boss else None
        if not w:
            self.count("passed")
            log("%s pass: %s not a worker of this boss" % (self.id8, ev["kind"]))
            pending = [k for k, r in self.st["escalations"].items() if self.report_due(r)]
            if self.mode == "armed" and pending:
                return self.pending_only(pending)
            return None
        self.count("seen")
        if ev["kind"] == "idle":
            self.st.get("subs", {}).pop(w["sid"], None)     # one-shot: this notice used it up
        mem, disp = self.worker_mem(w)
        armed = self.mode == "armed"
        pending = [k for k, r in self.st["escalations"].items() if self.report_due(r)]

        if ev["kind"] == "idle":
            fin = finish_epoch(ev["finish"])
            action, reason = decide_idle(mem, fin, w["status"])
            p = None
        else:
            if not egress_on():
                remember(mem, ev["body"], None)
                self.count("passed")
                log("%s pass: egress off, message from %s" % (self.id8, w["name"]))
                if armed and pending:
                    return self.pending_only(pending)
                return None
            records = tail_records(w["transcript"]) if w["transcript"] else []
            ctx, cost = usage(records)
            handoff = bool(newest_handoff(w["cwd"], (disp or {}).get("ts", 0)))
            p = self.ask_jev(self.request(w, ev, disp, ctx, handoff))
            action, reason = decide_message(p, mem, ev["body"], ctx, cost)

        if action == "absorb":
            ok, why = absorb_ready(mem, complete)
            if not ok:
                action, reason = "wake", why
            elif pending:
                action, reason = "wake", "an earlier escalation was interrupted"
        nums = (" tc %.2f owner %.2f redir %.2f" % (p["task_complete"], p["needs_owner"], p["redirected"])) \
            if p else ""
        log("%s %s %s %s (%s):%s -> %s: %s" % (
            self.id8, self.mode, ev["kind"], w["name"], w["coord"], nums, action, reason))
        if ev["kind"] == "message":
            remember(mem, ev["body"], p)

        if not armed:
            self.count("would_" + action)
            if "absorb-candidate" in reason:
                self.count("absorb_candidate")
            return None

        lines = []
        for k in pending:
            r = self.st["escalations"][k]
            lines.append(escalation_report(r, interrupted=not r.get("reports")))
            self.delivered.append(k)

        if action == "absorb":
            self.archive(w, ev, "absorbed", reason, p)       # an archive failure raises: the event wakes
            self.count("absorbed_" + ev["kind"])
            return {"decision": "block",
                    "reason": "boss-jev absorbed: %s (%s) %s; archived %s in %s" % (
                        w["name"], w["coord"], reason, self.id8, self.archive_path.name)}

        if action == "escalate":
            rec = self.escalate(w, ev, p)
            lines.append(escalation_report(rec, interrupted=False))
            self.delivered.append(self.digest)
            self.count("escalated")
        elif action == "finished":
            ok, facts, failed = self.restart_gates(w, ev, p, ctx, cost, mem, records)
            if ok:
                self.st["proposals"][w["pane"]] = time.time()
                lines.append(
                    "[boss-jev] RESTART proposed for %s (%s): task #%s reported finished (task_complete %.2f), "
                    "%s, handoff %s with its footer, repos clean and pushed (%s), no child processes, no input "
                    "since its report. Run now: `boss-lifecycle.sh restart --require-idle --expect-session %s "
                    "--expect-last %s %s`, then log it under its roster row and tell the owner with the number. "
                    "If the script refuses, say why in one line and leave the worker." % (
                        w["name"], w["coord"], mem.get("task") or "?", p["task_complete"], facts["ctx"],
                        facts["handoff"], facts["repos"], w["sid"], facts["pin"], w["pane"]))
                self.count("proposed_restart")
            else:
                reason = "dispatch due (no restart: %s)%s" % (
                    failed, " [absorb-candidate]" if "absorb-candidate" in reason else "")
        if action != "escalate" and not (action == "finished" and lines and "RESTART" in lines[-1]):
            lines.append("[boss-jev] %s (%s):%s -> %s. Archived: pm/%s (%s)." % (
                w["name"], w["coord"], nums, reason, self.archive_path.name, self.id8))
        self.archive(w, ev, "woken" if action != "escalate" else "escalated", reason, p)
        self.count("woken")
        if "absorb-candidate" in reason:
            self.count("absorb_candidate")
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                       "additionalContext": "\n".join(lines)}}


def escalation_report(rec, interrupted, again=None):
    key = rec.get("id") or "?"
    again = bool(rec.get("reports")) if again is None else again
    steps = rec.get("steps") or {}
    done = [k for k, v in steps.items() if str(v).startswith("done")]
    bad = ["%s (%s)" % (k, v) for k, v in steps.items() if not str(v).startswith("done") and v != "started"]
    unknown = [k for k, v in steps.items() if v == "started"]
    if interrupted:
        head = "[boss-jev] ESCALATION %s for %s (%s) was interrupted before it reached you." % (
            key, rec.get("worker"), rec.get("coord"))
    elif again:
        head = "[boss-jev] ESCALATION %s for %s (%s) is still open: its action is not named yet." % (
            key, rec.get("worker"), rec.get("coord"))
    else:
        head = "[boss-jev] ESCALATION T+0 for %s (%s), event %s: the worker needs the owner." % (
            rec.get("worker"), rec.get("coord"), key)
    parts = [head, "Done by the hook: %s." % (", ".join(done) or "nothing")]
    if bad:
        parts.append("Not done: %s: do these yourself." % "; ".join(bad))
    tracker = str(steps.get("tracker", ""))
    if rec.get("line") and (not tracker.startswith("done") or "dry run" in tracker):
        parts.append("The Open blockers line was not written; add it yourself, with your action in ask=: %s"
                     % rec["line"])
    if unknown:
        parts.append("Unknown: %s (started, no result): for Slack, check #claude-ops before posting." %
                     ", ".join(unknown))
    parts.append('Now, in this turn: say it naming ONE action, where, and what waits on it (with TTS too if voice is ON); put that '
                 'action into ask="…" on the `[ladder id=%s` line in Open blockers (the ladder timer posts the '
                 'later rungs from it); arm your 300 s timer. If the owner is not in fact needed: `boss-alert '
                 'clear`, delete the line and the pane emoji, and say why in one line.' % key)
    return " ".join(parts)


def redact_all(obj):
    b = bej()
    if isinstance(obj, str):
        return b.redact(obj)
    if isinstance(obj, list):
        return [redact_all(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_all(v) for k, v in obj.items()}
    return obj


def finish_epoch(hm, now=None):
    """'finished a turn at HH:MM' (local, no date) as the epoch of its most
    recent occurrence not in the future, or 0 when that is not unambiguous: a
    local time that a DST change repeats or skips, or one more than 12 hours
    back. 0 turns the stale rule off, so the notice wakes the boss."""
    if not hm or not (0 <= hm[0] < 24 and 0 <= hm[1] < 60):
        return 0
    now = now or datetime.datetime.now()
    t = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if t > now:
        t -= datetime.timedelta(days=1)
    e0, e1 = t.replace(fold=0).timestamp(), t.replace(fold=1).timestamp()
    if e0 != e1:
        return 0
    back = datetime.datetime.fromtimestamp(e0)
    if (back.hour, back.minute) != hm:
        return 0                                   # a time the DST change skipped
    if now.timestamp() - e0 > 12 * 3600:
        return 0
    return e0


def api_key():
    try:
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise Refused("no TYPESAFE_API_KEY")


def post_jev(req, timeout):
    r = urllib.request.Request(bej().API, data=json.dumps(req).encode(), headers={
        "Authorization": "Bearer " + api_key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp).get("answers") or {}


def fake_jev(path, req, timeout):
    """FAKE_JEV file: {"rules": [{"match": "...", "answers": {q: p}, "delay": s}], "default": {q: p}}."""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    report = req["state"]["report"]
    rule = next((r for r in spec.get("rules", []) if r.get("match", "\0") in report), None)
    ans = (rule or {}).get("answers") or spec.get("default") or {}
    delay = float((rule or {}).get("delay", 0))
    if delay:
        time.sleep(min(delay, timeout))
        if delay > timeout:
            raise Refused("Jev timed out")
    return {q: {"type": "noul", "noul": v} for q, v in ans.items()}


# ------------------------------------------------------------------ gates

FOOTER_RE = re.compile(r"<!--\s*boss-handoff:\s*session=(\S+)\s+task=#?(\d+)\s+repos=(\S+)\s+unsaved=(\S+)\s*-->")


def newest_handoff(cwd, after):
    best = None
    try:
        for p in Path(cwd).glob("handoff-*.md"):
            s = os.lstat(p)
            if not os.path.isfile(p) or os.path.islink(p) or s.st_uid != os.getuid() or s.st_mtime <= after:
                continue
            if best is None or s.st_mtime > best[1]:
                best = (p, s.st_mtime)
    except OSError:
        return None
    return best[0] if best else None


def footer_gate(w, disp):
    """(ok, why, repos, handoff name)."""
    if not disp:
        return False, "no known dispatch, so no task number to check the footer against", [], ""
    hand = newest_handoff(w["cwd"], disp["ts"])
    if not hand:
        return False, "no handoff-*.md newer than the last dispatch in its cwd", [], ""
    try:
        m = FOOTER_RE.search(hand.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    if not m:
        return False, "%s has no boss-handoff footer" % hand.name, [], ""
    sess, task, repos, unsaved = m.groups()
    if sess != w["sid"]:
        return False, "%s footer names another session" % hand.name, [], ""
    if not disp.get("task") or task != disp["task"]:
        return False, "%s footer says task %s, the last dispatch was #%s" % (hand.name, task, disp.get("task")), [], ""
    if unsaved != "none":
        return False, "%s footer says unsaved=%s" % (hand.name, unsaved), [], ""
    lst = [] if repos == "none" else [os.path.realpath(os.path.expanduser(r)) for r in repos.split(",") if r]
    return True, "", lst, hand.name


def git(args, cwd, timeout):
    try:
        r = subprocess.run(["git", "-C", cwd] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return r.returncode, r.stdout


def repos_gate(cwd, repos, timeout):
    rc, top = git(["rev-parse", "--show-toplevel"], cwd, timeout)
    own = os.path.realpath(top.strip()) if rc == 0 and top.strip() else None
    if own and own not in repos:
        return False, "the footer does not list its own repo %s" % own
    for r in repos:
        rc, top = git(["rev-parse", "--show-toplevel"], r, timeout)
        if rc != 0 or os.path.realpath(top.strip()) != r:
            return False, "%s is not a git top level" % r
        rc, out = git(["status", "--porcelain", "--untracked-files=no"], r, timeout)
        if rc != 0 or out.strip():
            return False, "%s has uncommitted changes to tracked files" % r
        rc, out = git(["rev-list", "--count", "@{u}..HEAD"], r, timeout)
        if rc != 0:
            return False, "%s has no upstream" % r
        if out.strip() != "0":
            return False, "%s has %s unpushed commit(s)" % (r, out.strip())
    return True, ""


PATH_RE = re.compile(r"(?<![\w.:/-])(~/[^\s`'\"<>()\[\],;]+|/(?:home|tmp|opt|srv|var|etc|usr|mnt)/[^\s`'\"<>()\[\],;]+)")


def evidence_gate(report, repos, timeout):
    for p in PATH_RE.findall(report or ""):
        p = p.rstrip(".:)")
        if os.path.exists(os.path.expanduser(p)):
            return True, ""
    for sha in list(dict.fromkeys(SHA_RE.findall(report or "")))[:5]:
        for r in repos:
            rc, _ = git(["cat-file", "-e", sha + "^{commit}"], r, timeout)
            if rc == 0:
                return True, ""
    return False, "its report names no path that exists here and no SHA found in its repos"


def children_gate(pid):
    """No Bash-tool shell among the claude process's children, and none started
    late. MCP servers start in the first seconds (measured: +6 s)."""
    kids = []
    try:
        for t in Path("/proc/%d/task" % pid).iterdir():
            kids += (t / "children").read_text().split()
    except OSError:
        return False, "cannot read its child processes"
    base = proc_start(pid)
    tck = os.sysconf("SC_CLK_TCK")
    for k in kids:
        try:
            args = Path("/proc/%s/cmdline" % k).read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "shell-snapshots" in args:
            return False, "a Bash tool shell is still running under it (pid %s)" % k
        ks = proc_start(k)
        if base and ks and (int(ks) - int(base)) / tck > LATE_CHILD_S:
            return False, "a child process started after its first %d s (pid %s)" % (LATE_CHILD_S, k)
    return True, ""


# ------------------------------------------------------------ shared files

def insert_in_section(body, title, line):
    lines = body.split("\n")
    head = next((i for i, l in enumerate(lines) if re.match(r"^##\s+%s\b" % re.escape(title), l)), None)
    if head is None:
        return body.rstrip("\n") + "\n\n## %s\n%s\n" % (title, line)
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    at = end
    while at > head + 1 and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, line)
    return "\n".join(lines)


def tracker_add(path, line, tag, deadline):
    """Add `line` to Open blockers unless `tag` is already in the file. Under the
    lock the ladder timer also takes, and only if the file did not change
    between the read and the rename."""
    if not in_pm(path) or not regular_mine(path):
        return "failed: the tracker is not a regular file of this user in pm/"
    lockp = path.with_name(".%s.lock" % path.name)
    with open(lockp, "a") as lf:
        while True:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline - 0.5:
                    return "failed: tracker lock held"
                time.sleep(0.05)
        for _ in range(3):
            s1 = os.stat(path)
            body = path.read_text(encoding="utf-8")
            if tag in body:
                return "done (already there)"
            tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
            tmp.write_text(insert_in_section(body, "Open blockers", line), encoding="utf-8")
            os.chmod(tmp, s1.st_mode & 0o777)
            s2 = os.stat(path)
            if (s2.st_mtime_ns, s2.st_size, s2.st_ino) != (s1.st_mtime_ns, s1.st_size, s1.st_ino):
                tmp.unlink()
                continue
            os.replace(tmp, path)
            return "done"
    return "failed: the tracker kept changing"


def client_emoji(cwd, track):
    try:
        colors = json.loads(COLORS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    keys = sorted((k for k in colors if not k.startswith("_")), key=len, reverse=True)
    low = (cwd or "").lower()
    for k in keys:
        if k in low:
            return (colors[k] or {}).get("emoji") or ""
    return (colors.get((track or "").split("-")[0]) or {}).get("emoji") or ""


# ------------------------------------------------------------------ entry points

def hook_main(raw):
    """The JSON to print for one UserPromptSubmit payload, or None (pass through)."""
    t0 = time.monotonic()
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
        return None
    sid = payload.get("session_id") or ""
    track = boss_track(sid)
    if not track:
        return None
    ev = parse_event(payload.get("prompt") or "")
    h = Hook(payload, sid, track, t0 + DEADLINE_S)
    try:
        if not ev:
            return h.run_pending()                 # a typed prompt: carries due reports, never blocked
        return h.run(ev)
    except LockHeld as e:
        log("%s pass: %s" % (h.id8, e))
        if effective_mode()[0] != "armed" or not ev:
            return None
        lines = ["[boss-jev] not judged: another run of the hook held the state lock. Handle this "
                 "event yourself as before the hook existed."]
        try:                                       # read-only: state is replaced whole, never written in place
            st = json.loads(h.state_path.read_text(encoding="utf-8"))
            for r in (st.get("escalations") or {}).values():
                if h.report_due(dict(r)):
                    lines.append(escalation_report(r, interrupted=not r.get("reports")))
        except (OSError, ValueError, AttributeError):
            pass
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}
    except Refused as e:
        log("%s pass: %s" % (h.id8, e))
    except Exception:                          # noqa: BLE001 - every failure wakes the boss
        log("%s pass: error %s" % (h.id8, traceback.format_exc(limit=3).replace("\n", " | ")))
    try:
        if h.st is not None:
            h.count("errors")
            h.save_state()
    except Exception:                          # noqa: BLE001
        pass
    return None


def install_hook(print_only):
    cmd = "python3 %s hook" % (HERE / "boss-jev.py")
    entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 8}]}
    if print_only:
        print(json.dumps(entry, indent=2))
        return 0
    raw = SETTINGS.read_text(encoding="utf-8")
    s = json.loads(raw)
    ups = s.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    if any("boss-jev.py hook" in (h.get("command") or "") for e in ups for h in e.get("hooks", [])):
        print("already installed in %s" % SETTINGS)
        return 0
    backup = SETTINGS.with_name("settings.json.bak-%s-boss-jev" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(SETTINGS, backup)
    ups.append(entry)
    tmp = SETTINGS.with_name(".settings.json.boss-jev.tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, os.stat(SETTINGS).st_mode & 0o777)
    os.replace(tmp, SETTINGS)
    print("installed the boss-jev UserPromptSubmit hook in %s (backup %s)" % (SETTINGS, backup.name))
    return 0


def own_session():
    pid = os.getppid()
    for _ in range(40):
        if pid <= 1:
            break
        rec = session_by_pid(pid)
        if rec:
            return rec
        try:
            data = Path("/proc/%d/stat" % pid).read_bytes()
            pid = int(data[data.rindex(b")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return None


def footer(task, repos):
    rec = own_session()
    if not rec:
        print("no Claude session found above this process", file=sys.stderr)
        return 1
    cwd = rec.get("cwd") or os.getcwd()
    if repos:
        lst = [os.path.realpath(os.path.expanduser(r)) for r in repos.split(",") if r]
    else:
        rc, top = git(["rev-parse", "--show-toplevel"], cwd, 5)
        lst = [os.path.realpath(top.strip())] if rc == 0 and top.strip() else []
    for r in lst:
        rc, top = git(["rev-parse", "--show-toplevel"], r, 5)
        if rc != 0 or os.path.realpath(top.strip()) != r:
            print("%s is not a git top level" % r, file=sys.stderr)
            return 1
    print("<!-- boss-handoff: session=%s task=%s repos=%s unsaved=none -->" % (
        rec.get("sessionId"), str(task).lstrip("#"), ",".join(lst) or "none"))
    return 0


def stats(days):
    total = {}
    for p in sorted(PULSE.glob("jev-*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8")).get("counters") or {}
        except (OSError, ValueError):
            continue
        for day, kv in c.items():
            for k, v in kv.items():
                total.setdefault(day, {}).setdefault(k, 0)
                total[day][k] += v
    mode, why = effective_mode()
    print("mode %s (%s); egress %s" % (mode, why, "on" if egress_on() else "off"))
    for day in sorted(total)[-days:]:
        print(day, " ".join("%s=%d" % kv for kv in sorted(total[day].items())))
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "hook":
        out = hook_main(sys.stdin.read())
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            finish_delivery()
        return 0
    if cmd == "install-hook":
        return install_hook("--print" in argv)
    if cmd == "footer":
        task = argv[argv.index("--task") + 1] if "--task" in argv else None
        repos = argv[argv.index("--repos") + 1] if "--repos" in argv else ""
        if not task:
            print("usage: boss-jev.py footer --task N [--repos A,B]", file=sys.stderr)
            return 2
        return footer(task, repos)
    if cmd == "stats":
        return stats(int(argv[argv.index("--days") + 1]) if "--days" in argv else 7)
    if cmd == "--selftest":
        import unittest
        t = _load("test_boss_jev", HERE / "test_boss_jev.py")
        res = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(t))
        return 0 if res.wasSuccessful() else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
