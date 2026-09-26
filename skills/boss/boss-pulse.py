#!/usr/bin/env python3
"""Stop hook — the boss's pulse. Keeps a boss working toward its objective.

The failure this exists to fix: Phase D was event-driven and nothing armed the
events. "Worker goes idle" was a row in the response table for something that
never arrived, so a boss with four idle workers and an open objective would end
its turn and wait — correct by the letter of the skill, useless in fact. the owner
then dispatched the four workers themselves, by hand, in four panes.

A Stop hook's `additionalContext` is delivered to the model and the conversation
continues (Claude Code 2.1.266: hookSpecificOutput for Stop accepts exactly that
one field, "non-error feedback delivered to the model; the conversation
continues so the model can act on it"). So the pulse does not argue with the
boss and does not block it. It hands it the objective and the list of idle
workers at the moment it was about to go quiet.

Silence stays the default. The pulse fires ONLY when all of these hold:

  * the session is a registered boss with a track          (marker file)
  * that track has an objective and it is OPEN             (<track>.goal.md)
  * no Stop hook already blocked this turn                 (stop_hook_active)
  * no background work of the boss is still running        (background_tasks)
  * the rate limits allow it                               (60 s / 12 per hour)
  * the boss is not already asking something              (registry `waitingFor`)
  * AND there is something concrete: a worker of this boss is idle, an
    escalation rung has come due, or a blocker is open and the boss is about
    to end its turn without putting it to anyone

With nothing idle and no rung due it emits nothing, which is the whole point: a
boss whose team is busy is correctly silent. The runtime caps consecutive
Stop-hook continuations at 8 (CLAUDE_CODE_STOP_HOOK_BLOCK_CAP) as a backstop,
but this hook is designed never to reach it — its condition goes false as soon
as the boss dispatches.

Opt-in by construction: no goal file, no pulse. Boss sessions already running
when this was installed are unaffected until someone runs `boss-goal init`.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
PM = CFG / "pm"
MARKERS = PM / ".boss-sessions"
STATE = PM / ".pulse"

MIN_GAP_S = 60          # never twice inside a minute
MAX_PER_HOUR = 12       # a boss needing more than this is in a loop, not a job
RUNGS = (5, 15, 30, 60, 90, 120, 180, 240)   # minutes, matching escalation.md


# ---------------------------------------------------------------- goal file

def read_goal(track):
    try:
        return (PM / ("%s.goal.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return None


def goal_status(body):
    m = re.search(r"^_Status:\s*(.+?)_\s*$", body, re.M)
    return (m.group(1).strip() if m else "").upper()


def section(body, title):
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(title),
                  body, re.M | re.S)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------ fleet

def live_sessions():
    """Every live peer session in a tmux pane, keyed by pane id."""
    out = {}
    for rec in registry.live(CFG):
        tm = rec.get("tmux") or ""
        if "%" in tm:
            out[tm.rsplit(".", 1)[-1]] = rec
    return out


def owned_panes(boss_pane):
    """Panes this boss stamped @boss_pane on, as (pane_id, coordinate).

    The coordinate is the session:window.pane INDEX form, because that is the
    only shape the boss may quote to the owner — it is what they see on the pane
    and what `boss-lifecycle.sh list` prints. A raw `%4` is banned by safety
    rule 15, so the pulse must not hand one over.
    """
    if not boss_pane:
        return []
    fmt = "#{pane_id}\t#{@boss_pane}\t#{session_name}:#{window_index}.#{pane_index}"
    try:
        raw = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", fmt],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    mine = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pane, owner, coord = parts[0], parts[1].strip(), parts[2]
        if owner == boss_pane and pane != boss_pane:
            mine.append((pane, coord))
    return mine


def idle_workers(sid):
    """Named workers owned by this boss that are idle right now."""
    live = live_sessions()
    me = next((r for r in live.values() if r.get("sessionId") == sid), None)
    if not me:
        return []
    boss_pane = (me.get("tmux") or "").rsplit(".", 1)[-1]
    out = []
    for pane, coord in owned_panes(boss_pane):
        rec = live.get(pane)
        if not rec or (rec.get("status") or "") != "idle":
            continue
        out.append((rec.get("name") or coord, coord))
    return out


def open_blockers(track):
    """Every line under `## Open blockers` that is an entry, newest last.

    `due_rungs` below answers "is a rung overdue". This answers the blunter
    question the boss keeps getting wrong: is anything blocked at all. A rung
    needs a T+0 timestamp the boss must have written; this needs nothing but
    the line existing, which is the point — the failure being fixed is a boss
    that never armed a timer.
    """
    try:
        body = (PM / ("%s.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"^##\s+Open blockers.*?$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith(("-", "*")) and len(line) > 2:
            out.append(line.lstrip("-* ").strip()[:160])
    return out


def question_pending(sid):
    """Is a dialog already open in this session?

    Claude Code writes `status: waiting` and a `waitingFor` label into the
    session registry while a question or a permission prompt is on screen. A
    turn that ends on `AskUserQuestion` leaves a tool call in flight, so Stop
    should not fire at all — measured 2026-09-20 across 209 real waits, 197 saw
    no transition. But 6 did, presumably on an interrupt, so this reads the
    registry rather than trusting that. It is the difference between a boss
    that has asked and one that has gone quiet.
    """
    rec = registry.by_sid(sid, CFG)
    if rec is None:
        return False
    return bool(rec.get("waitingFor")) or (rec.get("status") or "") == "waiting"


# ------------------------------------------------------- escalation rungs

TPLUS = re.compile(r"T\+0[^0-9]{0,12}(\d{4}-\d{2}-\d{2})?[T ]?(\d{2}):(\d{2})")


def due_rungs(track, fired):
    """Open blockers in the tracker whose next escalation rung has come due."""
    try:
        body = (PM / ("%s.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"^##\s+Open blockers.*?$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    if not m:
        return []
    now = time.localtime()
    due = []
    for line in m.group(1).splitlines():
        if "[ladder" in line:
            # boss-ladder.timer owns this line and posts its rungs from a user
            # timer, with no boss turn. Telling the boss to post it too is a
            # double rung, and a channel that repeats itself becomes wallpaper.
            continue
        t = TPLUS.search(line)
        if not t:
            continue
        day, hh, mm = t.group(1), int(t.group(2)), int(t.group(3))
        try:
            if day:
                y, mo, d = (int(x) for x in day.split("-"))
            else:
                y, mo, d = now.tm_year, now.tm_mon, now.tm_mday
            t0 = time.mktime((y, mo, d, hh, mm, 0, 0, 0, -1))
        except (ValueError, OverflowError):
            continue
        mins = int((time.time() - t0) / 60)
        if mins < RUNGS[0] or mins > 60 * 24:
            continue                              # too fresh, or stale/mistyped
        rung = max(r for r in RUNGS if r <= mins)
        key = re.sub(r"\W+", "", line)[:40]
        if fired.get(key) == rung:
            continue                              # already said this one
        due.append((key, rung, mins, line.strip()[:120]))
    return due


# ------------------------------------------------------------ rate limit

def gate(sid):
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / ("%s.json" % sid)
    try:
        st = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    now = time.time()
    if now - st.get("last", 0) < MIN_GAP_S:
        return None, st, f
    if now - st.get("hour_start", 0) > 3600:
        st["hour_start"], st["count"] = now, 0
    if st.get("count", 0) >= MAX_PER_HOUR:
        return None, st, f
    return now, st, f


def commit(f, st, now, fired):
    st["last"] = now
    st["count"] = st.get("count", 0) + 1
    st.setdefault("hour_start", now)
    st["rungs"] = fired
    try:
        f.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ main

def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if payload.get("hook_event_name") != "Stop":
        return 0
    if payload.get("stop_hook_active"):
        return 0                                  # never stack on another block

    sid = payload.get("session_id") or ""
    marker = MARKERS / sid
    if not sid or not marker.is_file():
        return 0                                  # not a boss
    try:
        track = marker.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return 0
    if not track:
        return 0                                  # no track claimed yet

    body = read_goal(track)
    if body is None:
        return 0                                  # opt-in: no objective, no pulse
    if not goal_status(body).startswith("OPEN"):
        return 0                                  # paused, or met

    # "Session is done" vs "session is paused waiting for background work" — the
    # runtime hands us the difference, so use it instead of guessing.
    for t in payload.get("background_tasks") or []:
        if (t.get("status") or "").lower() in ("running", "pending"):
            return 0

    now, st, statef = gate(sid)
    if now is None:
        return 0

    # Already asking? Then the boss is visibly waiting and needs no push. This
    # is also what stops the check looping: a pending question ends the turn
    # differently, and the registry says so.
    if question_pending(sid):
        return 0

    idle = idle_workers(sid)
    fired = dict(st.get("rungs") or {})
    rungs = due_rungs(track, fired)
    blockers = open_blockers(track)
    if not idle and not rungs and not blockers:
        return 0                                  # team busy, nothing overdue

    outcome = section(body, "Outcome")
    unmet = [l for l in section(body, "Done when").splitlines()
             if l.startswith("- [ ]")]
    nxt = [l for l in section(body, "Next, in priority order").splitlines()
           if l.strip()]

    lines = ["[boss pulse - track `%s`] Your objective is still OPEN, so this "
             "turn continues rather than ending." % track, ""]
    if outcome:
        lines.append("OUTCOME: " + outcome.splitlines()[0][:300])
    if unmet:
        lines.append("NOT YET MET:")
        lines += ["  " + l[6:][:160] for l in unmet[:6]]
    if nxt:
        lines.append("NEXT, in priority order:")
        lines += ["  " + l[:160] for l in nxt[:6]]
    lines.append("")

    if idle:
        lines.append("IDLE NOW, yours: "
                     + ", ".join("%s (%s)" % (n, c) for n, c in idle[:8]))
    for key, rung, mins, text in rungs[:3]:
        lines.append("OVERDUE: blocker open %d min, rung %d due - %s"
                     % (mins, rung, text))
        fired[key] = rung

    if blockers:
        lines.append("BLOCKED, and you are ending your turn without asking: "
                     + "; ".join(blockers[:3]))

    lines += ["", "Act, in this order:"]
    n = 0
    if blockers:
        n += 1
        lines.append("%d. **Ask the owner, with `AskUserQuestion`.** One question, the "
                     "one that unblocks the most work; hold the rest with their timers "
                     "running but silent. Self-contained - they remember nothing of this "
                     "context. Options they can click, your recommendation first and "
                     "labelled, and the reason that actually decides it. Prose makes them "
                     "type; a question makes the dashboard chime and their phone light up. "
                     "See `references/escalation.md`." % n)
    if idle:
        n += 1
        lines.append("%d. Dispatch the top NEXT item to an idle worker (P6: match "
                     "the project; move or spawn only if none fits)." % n)
        n += 1
        lines.append("%d. NEXT empty or stale? Refill it from the board or the "
                     "tracker (`boss-goal next %s`), then dispatch." % (n, track))
    if rungs:
        n += 1
        lines.append('%d. Run the due rung: `boss-alert %d "<one action, where, '
                     'what it costs>"`.' % (n, rungs[0][1]))
    lines.append("Then update the tracker, and tick off any DONE WHEN criterion "
                 "that has just been met.")
    lines.append("If none of this applies - the idle worker is deliberately "
                 "parked, or the objective is finished - say which in one line "
                 'and stop. `boss-goal status %s met "<evidence>"` closes it and '
                 "ends the pulse." % track)

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": "\n".join(lines),
    }}))
    commit(statef, st, now, fired)
    return 0


if __name__ == "__main__":
    sys.exit(main())
