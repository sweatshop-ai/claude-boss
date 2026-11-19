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
boss. It hands it the objective and the list of idle workers at the moment it
was about to go quiet. One case blocks the Stop: an idle worker with no park beside
unassigned work, at most 3 times in a row for the same idle set, then the pulse lets go.

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
import codex_blocker  # noqa: E402
import fleet  # noqa: E402
import memfloor  # noqa: E402
import objective  # noqa: E402
import park  # noqa: E402
import policy  # noqa: E402
import pulse  # noqa: E402
import registry  # noqa: E402
import silence_log  # noqa: E402
import tracker  # noqa: E402

MIN_GAP_S = 60          # never twice inside a minute
MAX_PER_HOUR = 12       # a boss needing more than this is in a loop, not a job


# ---------------------------------------------------------------- goal file

def read_goal(track):
    return boss_store.read_objective(track)


# ------------------------------------------------------------------ fleet

def team(sid):
    """This boss's live workers: (the idle ones as (name, coordinate), how many in all,
    the names of all of them, None when the roster cannot be read).

    The concierge is not one: it sits idle by design, and no ticket is for it.

    The coordinate is the session:window.pane INDEX form, because that is the
    only shape the boss may quote to the owner — it is what they see on the pane
    and what `boss-lifecycle.sh list` prints. A raw `%4` is banned by safety
    rule 15, so the pulse must not hand one over.
    """
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
    except fleet.TmuxUnavailable:
        return [], 0, None
    me = fleet.seat_of(seats, sid=sid)
    if not me:
        return [], 0, None
    idle, size, names = [], 0, []
    for seat in fleet.workers(seats, me.pane.id):
        if not seat.session:
            continue
        size += 1
        names.append(seat.session.get("name") or seat.pane.coord)
        if (seat.session.get("status") or "") == "idle":
            idle.append((seat.session.get("name") or seat.pane.coord, seat.pane.coord))
    return idle, size, names


def worker_statuses(sid):
    """{name: status} of this boss's live workers, for a park on `worker:<name>`.

    A name that is missing has ended: park.py counts that as finished. With no fleet to
    read the answer is `None`, not `{}`, which would wake every such park."""
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
    except fleet.TmuxUnavailable:
        return None
    me = fleet.seat_of(seats, sid=sid)
    if not me:
        return None
    return {(s.session.get("name") or s.pane.coord): (s.session.get("status") or "")
            for s in fleet.workers(seats, me.pane.id) if s.session}


def woken_parks(sid, track, idle, done, tracker_text):
    """(idle workers still without a park, the Woken parks, the parked ones).

    A worker whose park still holds is not idle for the pulse; it is one of the parked, as
    Woken with state `waiting`, which the boss may retire when memory is short. A park of a
    worker that is busy or gone is left alone: only an idle worker is the boss's to dispatch.
    A retired worker's park (`boss-park --retire`) is no idle worker's: when its event has
    happened or its time ran out, it is a Woken with state `retired`, for the boss to hand that
    work on. For `park.RETIRE_GAP_S` after a retire nobody is offered to retire (the memory the
    retire freed is not back yet), so retires do not cascade."""
    parks = park.read_parks(track)
    if not parks:
        return idle, (), ()
    workers = worker_statuses(sid) if any(p.event.startswith("worker:") for p in parks.values()) else {}
    if workers is None:                     # no fleet to read: a worker park is not woken on a guess
        workers = {}
        for p in parks.values():
            if p.event.startswith("worker:"):
                workers[p.event.partition(":")[2]] = "busy"
    world = park.World(done=frozenset(done), workers=workers, prs=park.pr_lookup(track),
                       blockers=tuple(tracker.blocker_lines(tracker_text)) if tracker_text else ())
    now = time.time()
    free, woken, waiting = [], [], []
    for p in parks.values():
        if (p.retired and not (p.event.startswith("owner:") and tracker_text is None)
                and park.state(p, now, world) != "waiting"):
            woken.append(pulse.Woken(p.worker, p.event, "retired", int((now - p.since) / 60)))
    kept = {p.worker for p in parks.values() if p.retired}    # `--retire` would refuse these names
    just_retired = any(p.retired and now - p.retired < park.RETIRE_GAP_S for p in parks.values())
    for name, coord in idle:
        p = parks.get(name)
        if p and tracker_text is None and p.event.startswith("owner:"):
            st = "waiting"                  # tracker unread: no blocker line proves nothing
        else:
            st = park.state(p, now, world) if p else None
        if st == "waiting":
            if name not in kept:
                waiting.append(pulse.Woken(name, p.event, st, int((now - p.since) / 60)))
            continue
        free.append((name, coord))
        if st:
            woken.append(pulse.Woken(name, p.event, st, int((now - p.since) / 60)))
    return free, tuple(woken), () if just_retired else tuple(waiting)


def memory_short(sid):
    """memfloor's refusal for one more worker, or "" when it would fit (or cannot be told)."""
    try:
        avail = memfloor.mem_available_kb(os.environ.get("BOSS_MEMINFO") or "/proc/meminfo")
    except (OSError, ValueError):
        return ""
    rss = []
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
        me = fleet.seat_of(seats, sid=sid)
        if me:
            rss = [r for r in (memfloor.rss_kb(s.session.get("pid"))
                               for s in fleet.workers(seats, me.pane.id) if s.session) if r]
    except fleet.TmuxUnavailable:
        pass
    return memfloor.refusal(avail, rss) or ""


# ------------------------------------------------------------- ticket graph

FRONTIER_PY = pulse.FRONTIER_PY


GH_CACHE_S = 30         # a GitHub frontier older than this is read again
GH_FIRST_S = 3          # one read of a GitHub graph, inside the hook's 5 s


def ready_of(out):
    return ["%s %s" % (t["num"], t["title"]) for t in out["tickets"] if t["state"] == "ready"]


def done_of(out):
    return [t["num"] for t in out["tickets"] if t["state"] == "done"]


def read_frontier(source, track):
    ready, _, err = read_graph(source, track)
    return ready, err


def read_graph(source, track):
    """(ready tickets as "NN title", numbers of the done tickets, error) for the graph at `source`.

    A folder is read the way `frontier.py` reads it, by importing it, so the
    pulse and the claim never disagree on what is ready. GitHub takes one call
    per ticket: the pulse keeps the last `frontier.py --json` under .pulse/ and
    reads GitHub again when it is older than GH_CACHE_S, for GH_FIRST_S at most
    inside this hook's 5 s. A graph too big for that is refreshed in the
    background and by `boss-goal check`, which saves the same cache; a failed
    read keeps the last good frontier."""
    if source.startswith("gh:"):
        cache = boss_store.frontier_cache(track, source)
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
            return [], [], None
        text = cache.read_text(encoding="utf-8", errors="replace")
        try:
            out = json.loads(text)
            return ready_of(out), done_of(out), None
        except (ValueError, KeyError, TypeError):
            return [], [], text.strip()[:300] or "empty frontier cache"
    import importlib.util
    spec = importlib.util.spec_from_file_location("frontier", str(FRONTIER_PY))
    fr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fr)
    tickets, errors = fr.load(source)
    if tickets is None or errors:
        return [], [], "; ".join(errors)[:300]
    out = fr.classify(tickets)
    return ready_of(out), done_of(out), None


def open_blockers(body):
    """Every line under `## Open blockers` that is an entry, newest last.

    `due_rungs` below answers "is a rung overdue". This answers the blunter
    question the boss keeps getting wrong: is anything blocked at all. A rung
    needs a T+0 timestamp the boss must have written; this needs nothing but
    the line existing, which is the point — the failure being fixed is a boss
    that never armed a timer.
    """
    if body is None:
        return []
    decided = _decided_entries(body)
    return [b[:160] for b in tracker.open_blockers(body) if b not in decided]


def _decided_entries(body):
    """{entry: choice} for the Open blockers entries the owner has already answered.

    The answer is `codex_blocker`'s: `_state` says whether the one open Codex down
    blocker has a valid recorded choice, and an entry counts only when its own marker
    carries that blocker's id. A malformed choice, one for another id, and a tracker
    with several open Codex down lines decide nothing. The lines are split as `_state`
    split them, and a marker that does not parse (a line closed by hand) is skipped.
    """
    lines = body.split("\n")
    status, id_, choice = codex_blocker._state(lines)
    if status != "chosen":
        return {}
    lo, hi = tracker.blockers_range(lines)
    out = {}
    for line in lines[lo:hi]:
        try:
            found = codex_blocker._is_cd(line) and tracker.scan_marker(line)
        except tracker.MarkerError:
            continue
        if found and found[1].get("id") == id_:
            out[line.strip().lstrip("-* ").strip()] = choice
    return out


def decided_blockers(body):
    """The blockers the owner has answered, as `entry (owner chose X)` lines, for the text."""
    if body is None:
        return []
    return ["%s (owner chose %s)" % (e.split(tracker.TOKEN)[0].strip()[:120], c)
            for e, c in _decided_entries(body).items()]


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


def concierge_holding(sid):
    """Has this boss's concierge got work in hand? Then the open blockers have been
    asked, or wait behind the one on screen. Idle means nothing is with it, so a
    blocker still open is the boss's to ask again."""
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
    except fleet.TmuxUnavailable:
        return False
    me = fleet.seat_of(seats, sid=sid)
    seat = fleet.concierge_of(seats, me.pane.id) if me else None
    return bool(seat) and (seat.session.get("status") or "") != "idle"


# ------------------------------------------------------- escalation rungs

TPLUS = re.compile(r"T\+0[^0-9]{0,12}(\d{4}-\d{2}-\d{2})?[T ]?(\d{2}):(\d{2})")


_UNREAD = object()


def due_rungs(track, fired, body=_UNREAD):
    """Open blockers in the tracker whose next escalation rung has come due.

    `body` is the tracker text a caller already read (None: it could not be);
    left out, this reads it.
    """
    if body is _UNREAD:
        body = boss_store.read_tracker(track)
    if body is None:
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
    """(now, state) when the pulse may speak, (None, state) when it must not."""
    st = boss_store.read_state(sid, "pulse")
    now = time.time()
    if now - st.get("last", 0) < MIN_GAP_S:
        return None, st
    if now - st.get("hour_start", 0) > 3600:
        st["hour_start"], st["count"] = now, 0
    if st.get("count", 0) >= MAX_PER_HOUR:
        return None, st
    return now, st


BLOCKS_STALE_S = 3600   # a count older than this is from another spell of idleness


def blocks_so_far(sid, idle_key, now):
    """Blocks in a row already given for this exact idle set; a different set, or one
    long ago, starts again."""
    b = boss_store.read_state(sid, "pulse").get("blocks") or {}
    if b.get("set") != idle_key or now - b.get("at", 0) > BLOCKS_STALE_S:
        return 0
    return b.get("n", 0)


def reset_blocks(sid):
    """Nobody is idle beside open work any more: the count of blocks starts over."""
    if boss_store.read_state(sid, "pulse").get("blocks"):
        boss_store.update_state(sid, "pulse", lambda st: st.pop("blocks", None))


def commit(sid, now, fired, blocks=None):
    """Record that the pulse spoke. Under the store's lock, so the hour's count
    is the sum of every Stop hook that spoke, not the last writer's."""
    def spoke(st):
        if now - st.get("hour_start", 0) > 3600:
            st["hour_start"], st["count"] = now, 0
        st["last"] = now
        st["count"] = st.get("count", 0) + 1
        st.setdefault("hour_start", now)
        st["rungs"] = fired
        if blocks is not None:
            st["blocks"] = blocks
    boss_store.update_state(sid, "pulse", spoke)


# ------------------------------------------------------------------ main

def main():
    if sys.argv[1:2] == ["why"]:
        if len(sys.argv) != 3:
            print("usage: boss-pulse.py why <track>", file=sys.stderr)
            return 2
        print(silence_log.why(sys.argv[2]))
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if payload.get("hook_event_name") != "Stop":
        return 0

    sid = payload.get("session_id") or ""
    if not boss_store.is_boss(sid):
        return 0                                  # not a boss: nothing of ours to log
    track = boss_store.track_of(sid)

    def held(gate, **details):
        silence_log.record(sid, track, gate, **details)
        return 0

    if payload.get("stop_hook_active"):
        return held("stop-hook-active")           # never stack on another block
    if not track:
        return held("no-track")                   # no track claimed yet, or not a plain name

    body = read_goal(track)
    if body is None:
        return held("no-goal")                    # opt-in: no objective, no pulse
    if not objective.is_open(body):
        return held("objective-closed")           # paused, or met

    # "Session is done" vs "session is paused waiting for background work" — the
    # runtime hands us the difference, so use it instead of guessing.
    for t in payload.get("background_tasks") or []:
        if (t.get("status") or "").lower() in ("running", "pending"):
            return held("background-tasks")

    now, st = gate(sid)
    if now is None:
        return held("rate-gate")

    # Already asking? Then the boss is visibly waiting and needs no push. This
    # is also what stops the check looping: a pending question ends the turn
    # differently, and the registry says so.
    if question_pending(sid):
        return held("open-question")

    idle, size, names = team(sid)
    fired = dict(st.get("rungs") or {})
    tracker_text = boss_store.read_tracker(track)  # once per Stop, both consumers share it
    rungs = due_rungs(track, fired, tracker_text)
    blockers = [] if concierge_holding(sid) else open_blockers(tracker_text)
    decided = decided_blockers(tracker_text)
    source = objective.tickets_source(body)
    ready, done, broken = read_graph(source, track) if source else ([], [], None)
    idle, woken, parked = woken_parks(sid, track, idle, done, tracker_text)
    cap, cap_reason = objective.workers_cap(body) or (None, "")
    facts = pulse.Facts(
        track=track, idle=idle, size=size, rungs=rungs, fired=fired,
        blockers=blockers, decided=decided, source=source, ready=ready, broken=broken,
        outcome=objective.section(body, "Outcome"), unmet=objective.unmet(body),
        next_items=objective.next_items(body), parks=woken, parked=parked,
        workers=None if names is None else tuple(names), cap=cap, cap_reason=cap_reason)
    if pulse.spawn_wanted(facts) > 0:
        facts = facts._replace(memshort=memory_short(sid))   # one meminfo read, only when a spawn may follow
    decision = pulse.decide(facts)
    short = pulse.shortfall(facts)
    unassigned = len(ready) if source else len(facts.next_items)
    if decision is None:
        # team busy, nothing overdue
        reset_blocks(sid)
        if short:
            return held("memory-short", idle=len(idle), unassigned=unassigned, refusal=short)
        return held("nothing-to-say", idle=len(idle), unassigned=unassigned)

    let_go = 0
    if decision.block:
        idle_key = ",".join(sorted(n for n, _ in idle))
        blocked = blocks_so_far(sid, idle_key, now)
        if blocked < pulse.BLOCK_LIMIT:
            commit(sid, now, decision.fired, blocks={"set": idle_key, "n": blocked + 1, "at": now})
            print(json.dumps({"decision": "block", "reason": pulse.block_reason(facts, decision)}))
            return held("blocked", idle=len(idle), unassigned=unassigned, blocks=blocked + 1,
                        refusal=short)
        let_go = blocked           # the ordinary pulse below still speaks: only the block is let go
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": pulse.render(facts, decision),
    }}))
    commit(sid, now, decision.fired, blocks={"set": idle_key, "n": let_go, "at": now} if let_go else {})
    if let_go:
        return held("block-let-go", idle=len(idle), unassigned=unassigned, blocks=let_go,
                    actions=",".join(a.kind for a in decision.actions))
    return held("fired", idle=len(idle), unassigned=unassigned,
                actions=",".join(a.kind for a in decision.actions), refusal=short)


if __name__ == "__main__":
    sys.exit(main())
