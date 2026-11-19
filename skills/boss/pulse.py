#!/usr/bin/env python3
"""What the pulse tells a boss: decided as data, then worded.

boss-pulse.py gathers the facts and owns the gate and the state file. This
module answers two things from those facts, apart:

    decide(facts)            the Decision, or None: the boss is left alone
    render(facts, decision)  the text the boss reads

A Decision is the ordered actions, the due rungs it names (`overdue`, three
at most) and the fired marks (`fired`) to save once the text is out. The
actions, in the order the boss is told to take them:

    ask             put the open blocker to the owner
    fix-graph       the ticket graph is broken; nothing is dispatched from it
    wake            an idle worker's park is over or expired: dispatch, re-park or retire it
    dispatch-ready  one READY ticket per idle worker
    spawn n         n more workers for the READY tickets left over
    retire-parked   memory is short for that spawn: retire the longest-parked worker, retry once
    dispatch-next   no ticket graph, or one with nothing READY: one NEXT item
                    per idle worker
    spawn-next n    no ticket graph: n more workers for the NEXT items no
                    worker is marked `(→ Name)` on, left over
    refill-next     ... and refill NEXT if it is empty or stale
    retire          idle workers with no park and nothing to dispatch: end them
    run-rung n      post the due rung n (the first overdue one)

A Decision also says whether the boss's turn may end (`block`): not while an idle worker
without a valid park sits beside unassigned work. The hook turns that into a Stop block and
counts it (BLOCK_LIMIT in a row for the same idle set, then it lets go).
"""
import re
from collections import namedtuple
from pathlib import Path

import objective
import park
import policy

FRONTIER_PY = Path(__file__).resolve().parent.parent / "hand-to-boss" / "frontier.py"

# idle: (name, coordinate) of this boss's idle workers; size: its live workers.
# rungs: the Rungs due now; fired: key -> rung already said.
# source: the ticket graph, "" for none; ready: "NN title"; broken: its error.
# outcome, unmet, next_items: from the objective, for the text only.
# decided: blockers the owner has answered; shown, never asked again.
# workers: the names of all its live workers, to tell a NEXT mark from a stale one;
# None when the roster could not be read, and no mark is called stale then.
# cap, cap_reason: the goal file's `Workers: N - <reason>` (cap None without the line);
# N holds only with a reason.
# parks: the Woken parks of idle workers (a park still waiting keeps its worker out of `idle`).
# parked: the idle workers whose park still holds, as Woken with state `waiting`.
# memshort: why a spawn would be refused now (memfloor.refusal), "" when it would fit.
Facts = namedtuple(
    "Facts",
    "track idle size rungs fired blockers source ready broken outcome unmet next_items decided"
    " parks workers cap cap_reason parked memshort",
    defaults=((), 0, (), {}, (), "", (), None, "", (), (), (), (), None, None, "", (), ""))
# An idle worker's park that no longer holds: state `over` (its event happened) or `expired`.
Woken = namedtuple("Woken", "worker event state minutes")
# A blocker line whose rung has come due: key into `fired`, the rung, minutes
# since its T+0, the line.
Rung = namedtuple("Rung", "key rung minutes line")
Decision = namedtuple("Decision", "actions overdue fired block", defaults=(False,))
BLOCK_LIMIT = 3         # blocks in a row for the same idle set, then the pulse lets go
Action = namedtuple("Action", "kind n", defaults=(None,))


MARK_RE = re.compile(r"\((?:→|->)\s*([^)]*?)\s*\)")


def _entries(items):
    """The NEXT list items, each with its wrapped and nested lines joined on."""
    entries = []
    for line in items:
        if objective.ITEM_RE.match(line):
            entries.append(line)
        elif entries:
            entries[-1] += " " + line.strip()
    return entries


def _marked(entry):
    """The worker names an entry is marked with, `(→ Ada)` or `(→ Ada, Bo)`."""
    return [n.strip() for m in MARK_RE.findall(entry) for n in m.split(",") if n.strip()]


def unassigned(items, workers, idle=()):
    """(the NEXT items no live worker is marked on, the marks naming a worker that is gone).

    The boss writes `(→ Name)` on a NEXT item a worker is on. An item without
    a mark, or whose mark names a worker that is not live, is unassigned.
    A mark naming an idle worker makes the item unassigned too, but is not
    called gone: that worker is not on it.
    `workers` None: the roster could not be read, so no mark is called gone."""
    live = None if workers is None else {w.casefold() for w in workers}
    resting = {w.casefold() for w in idle}
    free, gone = [], []
    for entry in _entries(items):
        names = _marked(entry)
        stale = [] if live is None else [n for n in names if n.casefold() not in live]
        if not names or stale or any(n.casefold() in resting for n in names):
            free.append(entry)
        gone += [n for n in stale if n not in gone]
    return free, gone


def _idle_names(facts):
    return [n for n, _ in facts.idle]


def _more_workers(demand, facts):
    """How many workers to add for `demand` open items: those the idle ones
    cannot take. No team limit but the one the track wrote with a reason; the
    spawn path checks memory."""
    n = demand - len(facts.idle)
    if facts.cap is not None and facts.cap_reason:
        n = min(n, facts.cap - facts.size)
    return n


def _team(facts, n):
    if facts.cap is not None and facts.cap_reason:
        return "team %d of %d: %s" % (facts.size + n, facts.cap, facts.cap_reason)
    return ("team %d now, no worker limit; the spawn refuses below %d GB free memory"
            % (facts.size, policy.MEMORY_FLOOR_GB))


def open_work(facts):
    """The unassigned work: the READY tickets of a sound graph, else the NEXT items no live
    worker is on. A broken graph hands out only NEXT."""
    if facts.source and not facts.broken and facts.ready:
        return list(facts.ready)
    return unassigned(facts.next_items, facts.workers, _idle_names(facts))[0]


def _spawn_wanted(facts):
    """(workers the ready tickets ask for, workers the unassigned NEXT items ask for); memory
    not yet counted."""
    # More ready tickets than idle workers: one new worker for each.
    spawn = _more_workers(len(facts.ready), facts) if not facts.broken else 0
    free = [] if facts.source else unassigned(facts.next_items, facts.workers, _idle_names(facts))[0]
    spawn_next = (_more_workers(len(free), facts)
                  if not facts.source and facts.workers is not None else 0)
    return spawn, spawn_next, free


def spawn_wanted(facts):
    spawn, spawn_next, _ = _spawn_wanted(facts)
    return max(spawn, 0) + max(spawn_next, 0)


def longest_parked(facts):
    """The Woken of the parked worker that has waited longest, or None. Only a park that still
    holds counts: a worker whose park is over or expired is idle already, and is dispatched."""
    return max(facts.parked, key=lambda w: w.minutes) if facts.parked else None


def shortfall(facts):
    """The memory refusal when a spawn is wanted, memory is short and nobody is parked to
    retire: the pulse starts nobody and logs this. None otherwise."""
    if facts.memshort and spawn_wanted(facts) > 0 and not longest_parked(facts):
        return facts.memshort
    return None


def decide(facts):
    spawn, spawn_next, free = _spawn_wanted(facts)
    retire = 0
    if facts.memshort and spawn_wanted(facts) > 0:
        # memory is short: no spawn; retire the longest-parked worker if there is one
        retire = spawn_wanted(facts) if longest_parked(facts) else 0
        spawn = spawn_next = 0
    if (not facts.idle and not facts.rungs and not facts.blockers and not facts.broken
            and not facts.parks and spawn <= 0 and spawn_next <= 0 and not retire):
        return None                               # team busy, nothing overdue
    overdue = list(facts.rungs[:3])
    fired = dict(facts.fired)
    for r in overdue:
        fired[r.key] = r.rung
    actions = []
    if facts.blockers:
        actions.append(Action("ask"))
    if facts.broken:
        actions.append(Action("fix-graph"))
    else:
        if facts.parks:
            actions.append(Action("wake"))
        if facts.source:
            if facts.idle and facts.ready:
                actions.append(Action("dispatch-ready"))
            if spawn > 0:
                actions.append(Action("spawn", spawn))
            if retire:
                actions.append(Action("retire-parked", retire))
            # A graph whose open tickets all wait on someone is not an empty
            # backlog: the side work lives in NEXT, so hand that out instead.
            if facts.idle and not facts.ready and facts.next_items:
                actions += [Action("dispatch-next"), Action("refill-next")]
        else:
            entries = _entries(facts.next_items)
            if facts.idle and (free or not entries):
                actions.append(Action("dispatch-next"))
            if spawn_next > 0:
                actions.append(Action("spawn-next", spawn_next))
            if retire:
                actions.append(Action("retire-parked", retire))
            if facts.idle and len(free) == len(entries):   # no item is being worked
                actions.append(Action("refill-next"))
    work = open_work(facts)
    woken = {w.worker for w in facts.parks}
    resting = [n for n in _idle_names(facts) if n not in woken]
    # Prose in NEXT, not a list, may still be work, and a ticket graph may hold open tickets
    # that wait on others: retire only on a NEXT list whose items are all marked busy,
    # or, beside a refill, as the fallback when the refill finds nothing.
    if resting and not work and not facts.broken and not facts.source and (
            _entries(facts.next_items) or not facts.next_items):
        actions.append(Action("retire"))
    if facts.rungs:
        actions.append(Action("run-rung", facts.rungs[0].rung))
    return Decision(actions, overdue, fired, block=bool(facts.idle and work and not facts.broken))


def _ask(facts, action):
    return ("**Ask the owner: send it to your concierge by `SendMessage`, or with "
            "`AskUserQuestion` if you have none.** One question, the "
            "one that unblocks the most work; hold the rest with their timers "
            "running but silent. Self-contained - they remember nothing of this "
            "context. Options they can click, your recommendation first and "
            "labelled, and the reason that actually decides it. Prose makes them "
            "type; a question makes the dashboard chime and their phone light up. "
            "See `references/escalation.md`.")


def _fix_graph(facts, action):
    return ("Fix the ticket graph before dispatching from it: "
            "`python3 %s %s` names what is wrong." % (FRONTIER_PY, facts.source))


def _woken_line(w, track):
    kind, _, target = w.event.partition(":")
    if w.state == "retired":
        return ("%s was retired for memory and its wait on %s has ended: hand its work (see its "
                "Tracker line) to a worker, then `boss-park %s %s --clear --retired`"
                % (w.worker, w.event, track, w.worker))
    if w.state == "over":
        what = {"ticket": "ticket %s done", "worker": "%s finished", "owner": "%s answered",
                "pr": "%s merged or closed", "ci": "CI of %s finished, or the PR is no longer open"}.get(
                    kind, "%s happened") % (target.removesuffix("-merged") if kind == "pr" else target)
        return "%s's wait is over (%s): dispatch it" % (w.worker, what)
    return "%s has waited %d h on %s: dispatch, re-park or retire" % (
        w.worker, park.TTL_S // 3600, w.event)


def _wake(facts, action):
    return "Wake the workers whose park no longer holds: " + "; ".join(
        _woken_line(w, facts.track) for w in facts.parks[:policy.LIST_MAX]) + "."


def _dispatch_ready(facts, action):
    return ("Dispatch the READY tickets this turn, one ticket per idle worker "
            "until the READY list runs out, not one per turn. Claim each first: `python3 %s claim %s "
            "<NN> <worker>`." % (FRONTIER_PY, facts.source))


def _spawn(facts, action):
    return ("Spawn %d more worker%s (%s) and dispatch the "
            "remaining READY tickets to them." % (
                action.n, "s" if action.n > 1 else "", _team(facts, action.n)))


def _spawn_next(facts, action):
    return ("Spawn up to %d more worker%s (%s) and dispatch the unassigned "
            "NEXT items to them; none for an item that waits on work in progress." % (
                action.n, "s" if action.n > 1 else "", _team(facts, action.n)))


def _retire_parked(facts, action):
    w = longest_parked(facts)
    waited = "%d h %d min" % divmod(w.minutes, 60) if w.minutes >= 60 else "%d min" % w.minutes
    return ("Memory is short for the %d more worker%s your open work asks for (%s). Retire "
            "%s (parked %s on %s), the longest-parked: `boss-lifecycle.sh retire <pane> "
            "--require-idle --kill`, its pane from `boss-lifecycle.sh list --mine`. Then mark its "
            "park `boss-park %s %s --retire` (the event stays recorded, and the pulse tells you "
            "when it has happened) and write on its Tracker line that it was retired for memory "
            "and waits on %s, so its work is picked up then. Retry the spawn once; if it is "
            "refused again, start nobody and carry on: this is not a blocker."
            % (action.n, "s" if action.n > 1 else "", facts.memshort, w.worker, waited,
               w.event, facts.track, w.worker, w.event))


def _dispatch_next(facts, action):
    return ("Dispatch NEXT items to the idle workers, one each, top first, "
            "never one marked `(→ Name)` for a busy worker; mark each item you hand "
            "out; skip an item that waits on work still in progress (P6: match "
            "the project; move or spawn only if none fits).")


def _refill_next(facts, action):
    return ("NEXT empty or stale? Refill it from the board or the "
            "tracker (`boss-goal next %s`), then dispatch." % facts.track)


def _retire(facts, action):
    woken = {w.worker for w in facts.parks}
    names = [n for n in _idle_names(facts) if n not in woken]
    return ("Nothing is left to hand out%s and no park holds %s: retire %s "
            "(`boss-lifecycle.sh retire <pane> --require-idle --kill`)." % (
                " (after the refill, if it finds nothing)"
                if not _entries(facts.next_items) else "",
                ", ".join(names[:policy.LIST_MAX]), "it" if len(names) == 1 else "them"))


def _run_rung(facts, action):
    return 'Run the due rung: `boss-alert %d "<one action, where, what it costs>"`.' % action.n


SAY = {"ask": _ask, "fix-graph": _fix_graph, "wake": _wake, "dispatch-ready": _dispatch_ready,
       "spawn": _spawn, "retire-parked": _retire_parked, "dispatch-next": _dispatch_next,
       "spawn-next": _spawn_next, "refill-next": _refill_next, "retire": _retire,
       "run-rung": _run_rung}


def block_reason(facts, decision):
    """Why the turn may not end: each idle worker and the unassigned items, the ways out,
    then the pulse's own instructions."""
    work = open_work(facts)
    names = _idle_names(facts)[:policy.LIST_MAX]
    return ("[boss pulse - BLOCK] You may not end this turn: %s idle without a park while work "
            "is unassigned.\nIDLE: %s\nUNASSIGNED: %s\n"
            "The only ways out: dispatch each idle worker, or park it with `boss-park %s <worker> "
            "--until <event>` (%s; 2 h at most).\n\n%s" % (
                ", ".join(names), ", ".join("%s (%s)" % (n, c) for n, c in facts.idle[:policy.LIST_MAX]),
                "; ".join(w[:80] for w in work[:policy.LIST_MAX]), facts.track, park.allowed(),
                render(facts, decision)))


def render(facts, decision):
    lines = ["[boss pulse - track `%s`] Your objective is still OPEN, so this "
             "turn continues rather than ending." % facts.track, ""]
    if facts.outcome:
        lines.append("OUTCOME: " + facts.outcome.splitlines()[0][:300])
    if facts.unmet:
        lines.append("NOT YET MET:")
        lines += ["  " + c[:160] for c in facts.unmet[:6]]
    if facts.broken:
        lines.append("TICKET GRAPH BROKEN (%s): %s" % (facts.source, facts.broken))
    elif facts.source:
        lines.append("READY NOW: " + ("; ".join(r[:60] for r in facts.ready[:policy.LIST_MAX])
                                      or "none"))
    if facts.cap is not None and not facts.cap_reason:
        lines.append("NOTE: `Workers: %d` in the goal file is ignored: it needs a reason "
                     "(`Workers: %d - <reason>`)." % (facts.cap, facts.cap))
    if facts.next_items and (facts.broken or not facts.source or not facts.ready):
        lines.append("NEXT, in priority order:")
        lines += ["  " + item[:160] for item in facts.next_items[:6]]
        if not facts.source:
            free, gone = unassigned(facts.next_items, facts.workers, _idle_names(facts))
            total = len(_entries(facts.next_items))
            tail = "; marks naming a worker that is gone: " + ", ".join(gone) if gone else ""
            if (total and total != len(free)) or gone:
                lines.append("UNASSIGNED in NEXT: %d of %d%s" % (len(free), total, tail))
    lines.append("")

    short = shortfall(facts)
    if short:
        lines.append("MEMORY: %s. No worker is parked to retire, so start nobody; dispatch to the "
                     "idle ones. This is not a blocker." % short)
    if facts.idle:
        lines.append("IDLE NOW, yours: "
                     + ", ".join("%s (%s)" % (n, c) for n, c in facts.idle[:policy.LIST_MAX]))
    lines += [_woken_line(w, facts.track) for w in facts.parks[:policy.LIST_MAX]]
    for r in decision.overdue:
        lines.append("OVERDUE: blocker open %d min, rung %d due - %s" % (r.minutes, r.rung, r.line))
    if facts.decided:
        lines.append("DECIDED by the owner, do not ask again: " + "; ".join(facts.decided[:3]))
    if facts.blockers:
        lines.append("BLOCKED, and you are ending your turn without asking: "
                     + "; ".join(facts.blockers[:3]))

    lines += ["", "Act, in this order:"]
    lines += ["%d. %s" % (i, SAY[a.kind](facts, a)) for i, a in enumerate(decision.actions, 1)]
    lines.append("Then update the tracker, and tick off any DONE WHEN criterion "
                 "that has just been met.")
    lines.append("If none of this applies - the objective is finished - say so and stop. "
                 "An idle worker is parked only by `boss-park %s <worker> --until <event>` "
                 "(%s; 2 h at most); \"parked on purpose\" in words is not a park, "
                 "so dispatch, park or retire it. "
                 '`boss-goal status %s met "<evidence>"` closes it and '
                 "ends the pulse." % (facts.track, park.allowed(), facts.track))
    return "\n".join(lines)
