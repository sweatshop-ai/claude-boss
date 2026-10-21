#!/usr/bin/env python3
"""The boss's steering numbers, in one place.

Every threshold a boss or a worker acts on lives here, and only here:

  context bands   when a session's context calls for action, by role
  cost lines      when cost per turn calls for action
  escalation      the rungs at which a blocker on the owner is re-raised
  review waits    how long a PR review waits on Codex, on the fallback, on gh and on its lock

    flag_for(ctx, cost, role) -> list of flags, e.g. ["CTX-SPLIT"]
    heavy(ctx, cost, role)    -> True past the first context or recycle line
    rung_for(elapsed_min)     -> the highest rung reached, or None
    next_rung(rung)           -> the rung after it

The prose (SKILL.md, team/SKILL.md, references/, bin/boss-start) quotes these
numbers so that a model reading it does not need this file. test_policy.py
checks that every quote still matches; change a number here and that test
names each file to update.

Units are tokens for context and priced cost-units for cost (see transcript.py
for the weights), minutes for rungs, seconds for review waits.
"""

WORKER, BOSS = "worker", "boss"

# A worker gets one task per session (2026-10-01). Past SPLIT the task is
# bigger than the smart zone and is cut at its next natural boundary; past
# OVER that cut is overdue.
WORKER_SPLIT, WORKER_OVER = 150_000, 250_000

# A boss compacts at 450k (bin/boss-start) and its state is the tracker. EVAL:
# start evaluating; RESTART: overdue.
BOSS_EVAL, BOSS_RESTART = 400_000, 500_000

# Cost per turn, against a fresh session's ~30k.
COST_HEAVY, COST_RECYCLE = 60_000, 90_000

# Re-raise a blocker on the owner at 5, 15, 30, 60, 120 minutes, then every
# 120 until STOP_MIN, when the ladder says so once and stops (set 2026-09-18).
RUNGS = (5, 15, 30, 60, 120)
RUNG_EVERY = 120
STOP_MIN = 24 * 60

# PR review (boss_review.py), seconds. A Codex review of a plan took 8 minutes, so Codex gets 600;
# the fallback reviewer, once there is one, gets a wait of its own, also 600; a `gh` or `git` call or
# the wait for a PR's lock gets 60; the review's child process gets 30 past Codex's wait to wind up.
REVIEW_CODEX_TIMEOUT = 600
REVIEW_FALLBACK_TIMEOUT = 600
REVIEW_IO_TIMEOUT = 60
REVIEW_CHAIN_SLACK = 30


def flag_for(ctx, cost, role):
    """Flags for a session with `ctx` tokens of context and `cost` cost-units
    per turn. Unknown values (None) raise no flag."""
    flags = []
    if cost is not None:
        if cost >= COST_RECYCLE:
            flags.append("RECYCLE")
        elif cost >= COST_HEAVY:
            flags.append("heavy")
    if ctx is not None:
        if role == BOSS:
            if ctx >= BOSS_RESTART:
                flags.append("CTX-RESTART")
            elif ctx >= BOSS_EVAL:
                flags.append("CTX-EVAL")
        else:
            if ctx >= WORKER_OVER:
                flags.append("CTX-OVER")
            elif ctx >= WORKER_SPLIT:
                flags.append("CTX-SPLIT")
    return flags


def heavy(ctx, cost, role=WORKER):
    """True when the session is past its first context line or the recycle
    cost line: the point at which its messages always reach the boss."""
    first = BOSS_EVAL if role == BOSS else WORKER_SPLIT
    return ctx >= first or cost >= COST_RECYCLE


def rung_for(elapsed_min):
    """Highest rung reached at `elapsed_min`, or None before the first; STOP_MIN
    once the stop is reached. The rung label is the elapsed minutes, which is
    what boss-alert prints."""
    if elapsed_min < RUNGS[0]:
        return None
    if elapsed_min >= STOP_MIN:
        return STOP_MIN
    if elapsed_min < RUNGS[-1]:
        return max(r for r in RUNGS if r <= elapsed_min)
    return (elapsed_min // RUNG_EVERY) * RUNG_EVERY


def next_rung(rung):
    """The rung after `rung`, capped at STOP_MIN."""
    if rung in RUNGS[:-1]:
        return RUNGS[RUNGS.index(rung) + 1]
    return min(rung + RUNG_EVERY, STOP_MIN)
