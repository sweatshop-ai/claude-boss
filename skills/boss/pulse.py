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
    dispatch-ready  one READY ticket per idle worker
    spawn n         n more workers for the READY tickets left over
    dispatch-next   no ticket graph: one NEXT item per idle worker
    refill-next     ... and refill NEXT if it is empty or stale
    run-rung n      post the due rung n (the first overdue one)
"""
from collections import namedtuple
from pathlib import Path

import policy

FRONTIER_PY = Path(__file__).resolve().parent.parent / "hand-to-boss" / "frontier.py"

# idle: (name, coordinate) of this boss's idle workers; size: its live workers.
# rungs: the Rungs due now; fired: key -> rung already said.
# source: the ticket graph, "" for none; ready: "NN title"; broken: its error.
# outcome, unmet, next_items: from the objective, for the text only.
Facts = namedtuple(
    "Facts",
    "track idle size rungs fired blockers source ready broken outcome unmet next_items",
    defaults=((), 0, (), {}, (), "", (), None, "", (), ()))
# A blocker line whose rung has come due: key into `fired`, the rung, minutes
# since its T+0, the line.
Rung = namedtuple("Rung", "key rung minutes line")
Decision = namedtuple("Decision", "actions overdue fired")
Action = namedtuple("Action", "kind n", defaults=(None,))


def decide(facts):
    # More ready tickets than idle workers, and room left in the team.
    spawn = (min(len(facts.ready) - len(facts.idle), policy.BOSS_SPAN - facts.size)
             if not facts.broken else 0)
    if (not facts.idle and not facts.rungs and not facts.blockers and not facts.broken
            and spawn <= 0):
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
    elif facts.source:
        if facts.idle and facts.ready:
            actions.append(Action("dispatch-ready"))
        if spawn > 0:
            actions.append(Action("spawn", spawn))
    elif facts.idle:
        actions += [Action("dispatch-next"), Action("refill-next")]
    if facts.rungs:
        actions.append(Action("run-rung", facts.rungs[0].rung))
    return Decision(actions, overdue, fired)


def _ask(facts, action):
    return ("**Ask the owner, with `AskUserQuestion`.** One question, the "
            "one that unblocks the most work; hold the rest with their timers "
            "running but silent. Self-contained - they remember nothing of this "
            "context. Options they can click, your recommendation first and "
            "labelled, and the reason that actually decides it. Prose makes them "
            "type; a question makes the dashboard chime and their phone light up. "
            "See `references/escalation.md`.")


def _fix_graph(facts, action):
    return ("Fix the ticket graph before dispatching from it: "
            "`python3 %s %s` names what is wrong." % (FRONTIER_PY, facts.source))


def _dispatch_ready(facts, action):
    return ("Dispatch the READY tickets this turn, one ticket per idle worker "
            "until the READY list runs out, not one per turn. Claim each first: `python3 %s claim %s "
            "<NN> <worker>`." % (FRONTIER_PY, facts.source))


def _spawn(facts, action):
    return ("Spawn %d more worker%s (team %d of %d) and dispatch the "
            "remaining READY tickets to them." % (
                action.n, "s" if action.n > 1 else "", facts.size, policy.BOSS_SPAN))


def _dispatch_next(facts, action):
    return ("Dispatch NEXT items to the idle workers, one each, top first; "
            "skip an item that waits on work still in progress (P6: match "
            "the project; move or spawn only if none fits).")


def _refill_next(facts, action):
    return ("NEXT empty or stale? Refill it from the board or the "
            "tracker (`boss-goal next %s`), then dispatch." % facts.track)


def _run_rung(facts, action):
    return 'Run the due rung: `boss-alert %d "<one action, where, what it costs>"`.' % action.n


SAY = {"ask": _ask, "fix-graph": _fix_graph, "dispatch-ready": _dispatch_ready,
       "spawn": _spawn, "dispatch-next": _dispatch_next, "refill-next": _refill_next,
       "run-rung": _run_rung}


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
        lines.append("READY NOW: " + ("; ".join(r[:60] for r in facts.ready[:policy.BOSS_SPAN])
                                      or "none"))
    elif facts.next_items:
        lines.append("NEXT, in priority order:")
        lines += ["  " + item[:160] for item in facts.next_items[:6]]
    lines.append("")

    if facts.idle:
        lines.append("IDLE NOW, yours: "
                     + ", ".join("%s (%s)" % (n, c) for n, c in facts.idle[:policy.BOSS_SPAN]))
    for r in decision.overdue:
        lines.append("OVERDUE: blocker open %d min, rung %d due - %s" % (r.minutes, r.rung, r.line))
    if facts.blockers:
        lines.append("BLOCKED, and you are ending your turn without asking: "
                     + "; ".join(facts.blockers[:3]))

    lines += ["", "Act, in this order:"]
    lines += ["%d. %s" % (i, SAY[a.kind](facts, a)) for i, a in enumerate(decision.actions, 1)]
    lines.append("Then update the tracker, and tick off any DONE WHEN criterion "
                 "that has just been met.")
    lines.append("If none of this applies - the idle worker is deliberately "
                 "parked, or the objective is finished - say which in one line "
                 'and stop. `boss-goal status %s met "<evidence>"` closes it and '
                 "ends the pulse." % facts.track)
    return "\n".join(lines)
