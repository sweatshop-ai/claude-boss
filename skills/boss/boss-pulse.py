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
import boss_store  # noqa: E402
import fleet  # noqa: E402
import objective  # noqa: E402
import policy  # noqa: E402
import pulse  # noqa: E402
import registry  # noqa: E402
import tracker  # noqa: E402

MIN_GAP_S = 60          # never twice inside a minute
MAX_PER_HOUR = 12       # a boss needing more than this is in a loop, not a job


# ---------------------------------------------------------------- goal file

def read_goal(track):
    try:
        return (boss_store.pm_dir() / ("%s.goal.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return None


# ------------------------------------------------------------------ fleet

def team(sid):
    """This boss's live workers: (the idle ones as (name, coordinate), how many in all).

    The coordinate is the session:window.pane INDEX form, because that is the
    only shape the boss may quote to the owner — it is what they see on the pane
    and what `boss-lifecycle.sh list` prints. A raw `%4` is banned by safety
    rule 15, so the pulse must not hand one over.
    """
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
    except fleet.TmuxUnavailable:
        return [], 0
    me = fleet.seat_of(seats, sid=sid)
    if not me:
        return [], 0
    idle, size = [], 0
    for seat in fleet.owned(seats, me.pane.id):
        if not seat.session:
            continue
        size += 1
        if (seat.session.get("status") or "") == "idle":
            idle.append((seat.session.get("name") or seat.pane.coord, seat.pane.coord))
    return idle, size


# ------------------------------------------------------------- ticket graph

FRONTIER_PY = pulse.FRONTIER_PY


GH_CACHE_S = 30         # a GitHub frontier older than this is read again
GH_FIRST_S = 3          # one read of a GitHub graph, inside the hook's 5 s


def ready_of(out):
    return ["%s %s" % (t["num"], t["title"]) for t in out["tickets"] if t["state"] == "ready"]


def frontier_cache(track, source):
    """Where the last `frontier.py --json` of this track's GitHub graph is kept.
    Keyed by the source too, so a track moved to another graph never reads the
    old one's tickets. `boss-goal check` writes the same file."""
    import hashlib
    return boss_store.state_dir() / ("%s.%s.frontier.json" % (track, hashlib.sha1(source.encode()).hexdigest()[:10]))


def read_frontier(source, track):
    """(ready tickets as "NN title", error) for the ticket graph at `source`.

    A folder is read the way `frontier.py` reads it, by importing it, so the
    pulse and the claim never disagree on what is ready. GitHub takes one call
    per ticket: the pulse keeps the last `frontier.py --json` under .pulse/ and
    reads GitHub again when it is older than GH_CACHE_S, for GH_FIRST_S at most
    inside this hook's 5 s. A graph too big for that is refreshed in the
    background and by `boss-goal check`, which saves the same cache; a failed
    read keeps the last good frontier."""
    if source.startswith("gh:"):
        cache = frontier_cache(track, source)
        try:
            age = time.time() - cache.stat().st_mtime
        except OSError:
            age = None
        if age is None or age > GH_CACHE_S:
            try:
                r = subprocess.run([sys.executable, str(FRONTIER_PY), "--json", source],
                                   capture_output=True, text=True, timeout=GH_FIRST_S)
                # A failed read never replaces a good frontier: GitHub down for a
                # minute must not turn the graph "broken". With no cache at all,
                # the error is what the boss needs to see.
                if r.returncode == 0 or age is None:
                    boss_store.state_dir().mkdir(parents=True, exist_ok=True)
                    tmp = cache.with_suffix(".tmp%d" % os.getpid())
                    tmp.write_text(r.stdout if r.returncode == 0 else r.stderr, encoding="utf-8")
                    os.replace(tmp, cache)
                    age = 0
            except (subprocess.SubprocessError, OSError):
                # Too slow for this hook: finish in the background, success only.
                try:
                    subprocess.Popen(
                        ["sh", "-c", '"$0" "$1" --json "$2" > "$3.$$" 2>/dev/null '
                         '&& mv "$3.$$" "$3" || rm -f "$3.$$"',
                         sys.executable, str(FRONTIER_PY), source, str(cache)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    pass
        if age is None:
            return [], None
        text = cache.read_text(encoding="utf-8", errors="replace")
        try:
            return ready_of(json.loads(text)), None
        except (ValueError, KeyError, TypeError):
            return [], text.strip()[:300] or "empty frontier cache"
    import importlib.util
    spec = importlib.util.spec_from_file_location("frontier", str(FRONTIER_PY))
    fr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fr)
    tickets, errors = fr.load(source)
    if tickets is None or errors:
        return [], "; ".join(errors)[:300]
    return ready_of(fr.classify(tickets)), None


def open_blockers(track):
    """Every line under `## Open blockers` that is an entry, newest last.

    `due_rungs` below answers "is a rung overdue". This answers the blunter
    question the boss keeps getting wrong: is anything blocked at all. A rung
    needs a T+0 timestamp the boss must have written; this needs nothing but
    the line existing, which is the point — the failure being fixed is a boss
    that never armed a timer.
    """
    try:
        body = (boss_store.pm_dir() / ("%s.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return []
    return [b[:160] for b in tracker.open_blockers(body)]


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
    rec = registry.by_sid(sid, boss_store.config_dir())
    if rec is None:
        return False
    return bool(rec.get("waitingFor")) or (rec.get("status") or "") == "waiting"


# ------------------------------------------------------- escalation rungs

TPLUS = re.compile(r"T\+0[^0-9]{0,12}(\d{4}-\d{2}-\d{2})?[T ]?(\d{2}):(\d{2})")


def due_rungs(track, fired):
    """Open blockers in the tracker whose next escalation rung has come due."""
    try:
        body = (boss_store.pm_dir() / ("%s.md" % track)).read_text(encoding="utf-8")
    except OSError:
        return []
    now = time.localtime()
    due = []
    for line in tracker.blocker_lines(body):
        if tracker.has_marker(line):
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
        rung = policy.rung_for(mins)              # the ladder's rungs (policy.py)
        if rung is None or mins > policy.STOP_MIN:
            continue                              # too fresh, or stale/mistyped
        key = re.sub(r"\W+", "", line)[:40]
        prev = fired.get(key)
        if isinstance(prev, int) and prev >= rung:
            continue                              # already said this one, or a later one
                                                  # (state from an older schedule: 90, 180)
        due.append(pulse.Rung(key, rung, mins, line.strip()[:120]))
    return due


# ------------------------------------------------------------ rate limit

def gate(sid):
    state = boss_store.state_dir()
    state.mkdir(parents=True, exist_ok=True)
    f = state / ("%s.json" % sid)
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
    if not boss_store.is_boss(sid):
        return 0                                  # not a boss
    track = boss_store.track_of(sid)
    if not track:
        return 0                                  # no track claimed yet, or not a plain name

    body = read_goal(track)
    if body is None:
        return 0                                  # opt-in: no objective, no pulse
    if not objective.is_open(body):
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

    idle, size = team(sid)
    fired = dict(st.get("rungs") or {})
    rungs = due_rungs(track, fired)
    blockers = open_blockers(track)
    source = objective.tickets_source(body)
    ready, broken = read_frontier(source, track) if source else ([], None)
    facts = pulse.Facts(
        track=track, idle=idle, size=size, rungs=rungs, fired=fired,
        blockers=blockers, source=source, ready=ready, broken=broken,
        outcome=objective.section(body, "Outcome"), unmet=objective.unmet(body),
        next_items=objective.next_items(body))
    decision = pulse.decide(facts)
    if decision is None:
        return 0                                  # team busy, nothing overdue

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": pulse.render(facts, decision),
    }}))
    commit(statef, st, now, decision.fired)
    return 0


if __name__ == "__main__":
    sys.exit(main())
