#!/usr/bin/env python3
"""The boss's steering numbers, in one place.

Every threshold a boss or a worker acts on lives here, and only here:

  context bands   when a session's context calls for action, by role
  cost lines      when cost per turn calls for action
  escalation      the rungs at which a blocker on the owner is re-raised
  review waits    how long a PR review waits on Codex, on the fallback, on gh and on its lock
  review text     how much of a PR's text goes into the brief, and how much of the findings into the comment
  fallback call   the model, the tools and the permission mode of the read-only fallback reviewer
  Codex health    how many failed or answered Codex attempts in a row say it is down or back

    flag_for(ctx, cost, role) -> list of flags, e.g. ["CTX-SPLIT"]
    heavy(ctx, cost, role)    -> True past the first context or recycle line
    rung_for(elapsed_min)     -> the highest rung reached, or None
    next_rung(rung)           -> the rung after it

The prose (SKILL.md, team/SKILL.md, references/, bin/boss-start) quotes these
numbers so that a model reading it does not need this file. test_policy.py
checks that every quote still matches; change a number here and that test
names each file to update.

Units are tokens for context and priced cost-units for cost (see transcript.py
for the weights), minutes for rungs, seconds for review waits, UTF-8 bytes for
the PR text in a brief, characters for a published finding, counts elsewhere in
a review.
"""

WORKER, BOSS = "worker", "boss"

# A worker gets one task per session (2026-10-01). Past SPLIT the task is
# bigger than the smart zone and is cut at its next natural boundary; past
# OVER the "Session age" rule for a long worker applies.
WORKER_SPLIT, WORKER_OVER = 150_000, 250_000

# A boss compacts at 450k (bin/boss-start) and its state is the tracker. EVAL:
# start evaluating; RESTART: overdue.
BOSS_EVAL, BOSS_RESTART = 400_000, 500_000

# How many workers one boss runs at once (2026-10-21, the owner: finish sooner,
# spend the weekly budget sooner). The binding limit is the weekly usage cap,
# not the machine; each report still lands in the boss's context.
BOSS_SPAN = 12

# A burst: at most BURST_MAX helpers inside one worker, BURST_START by default.
# Anthropic's agent-teams guide: "Start with 3-5 teammates for most workflows."
BURST_START, BURST_MAX = 3, 5

# Cost per turn, against a fresh session's ~30k.
COST_HEAVY, COST_RECYCLE = 60_000, 90_000

# Re-raise a blocker on the owner at 5, 15, 30, 60, 120 minutes, then every
# 120 until STOP_MIN, when the ladder says so once and stops (set 2026-09-18).
RUNGS = (5, 15, 30, 60, 120)
RUNG_EVERY = 120
STOP_MIN = 24 * 60

# Codex health (codex_health.py), counted over the attempts log, all repos together (2026-11-12, the owner:
# an outage should be an open blocker, not a silent wait). DOWN_AFTER failed Codex attempts in a row make
# it down. UP_AFTER answered ones in a row make it up again, so one answer amid failures never clears it;
# 2 is the smallest value that says so, and the recheck passes supply the second answer soon, where a
# larger value would leave a recovered outage on the ladder for hours.
CODEX_DOWN_AFTER = 3
CODEX_UP_AFTER = 2

# The fallback reviewer, `claude` in read-only mode (boss_review.fallback_spec). The model is passed by
# its exact id, so no CLI default is ever accepted; the tools are the built-in set it may use, and
# `--strict-mcp-config` (with no `--mcp-config`) keeps every MCP server out, which `--tools` alone does not.
# `--restricted` (no constant: it takes no value) keeps the user, project and local settings files out;
# managed and remote settings still apply, hence the variables below.
REVIEW_FALLBACK_MODEL = "claude-opus-5-5"
REVIEW_FALLBACK_TOOLS = ("Read", "Grep", "Glob")
REVIEW_FALLBACK_PERMISSION_MODE = "dontAsk"
# Variables the fallback's `claude` does not inherit: the plugin directories named here load their hooks
# whatever `--restricted` says about settings files (found 2026-11-12 by --check-fallback with 2.1.311).
# The list is a denylist and so can fall behind a release of `claude`: the init-event and hook checks of
# --check-fallback are what shows that nothing slipped through, not this list.
REVIEW_FALLBACK_ENV_UNSET = (
    "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CODE_PLUGIN_SEED_DIR", "CLAUDE_CODE_PLUGIN_CACHE_DIR",
    "CLAUDE_CODE_DESKTOP_SKILLS_PLUGIN_DIR", "CLAUDE_DEV_MODS_DIR",
    # managed and remote settings still apply under --restricted, so a path a PR could be named in is out
    "CLAUDE_CODE_MANAGED_SETTINGS_PATH", "CLAUDE_CODE_REMOTE_SETTINGS_PATH", "CLAUDE_CODE_MOCK_REMOTE_SETTINGS",
    "CLAUDE_CODE_REMOTE_MCP_CONFIG", "CLAUDE_CODE_BRIDGE_CHILD_MACHINE_SETTINGS",
    # launchers and loaders: they run a program before `claude` has read any flag
    "CLAUDE_ENV_FILE", "CLAUDE_CODE_PROCESS_WRAPPER", "CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT",
    "BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH", "NODE_OPTIONS", "BUN_OPTIONS")

# PR review (boss_review.py), seconds. A Codex review of a plan took 8 minutes, so Codex gets 600;
# the fallback reviewer, once there is one, gets a wait of its own, also 600; a `gh` or `git` call or
# the wait for a PR's lock gets 60; the review's child process gets 30 past Codex's wait to wind up.
REVIEW_CODEX_TIMEOUT = 600
REVIEW_FALLBACK_TIMEOUT = 600
REVIEW_IO_TIMEOUT = 60

# The waiver (ticket 09c): how long the owner's command may run, and how long a consent token lives.
WAIVE_TEST_TIMEOUT = 900         # seconds; a timeout counts as failed tests
CONSENT_TTL = 600                # seconds a token written after the owner's "yes" can be used
REVIEW_CHAIN_SLACK = 30

# What a PR review publishes of the reviewer's findings: at most this many `FINDING:` lines, each cut to
# this many characters (the prefix counts).
REVIEW_FINDINGS_MAX = 20
REVIEW_FINDING_CHARS = 300
# A finding line longer than REVIEW_FINDING_READ characters is neither matched nor shown, only its
# length: a site pattern is judged on a whole line, and one without an end cannot stall the matching.
REVIEW_FINDING_READ = 4000

# The PR text in the brief. The prompt reaches `codex` as one argv element and Linux refuses one of
# 131072 bytes, so the title, body and diff are cut (by UTF-8 bytes) and the whole brief stays under
# REVIEW_BRIEF_MAX. The cut limits the copy in the brief, not the review: the reviewer reads the checkout.
REVIEW_TITLE_MAX = 1_000
REVIEW_BODY_MAX = 20_000
REVIEW_DIFF_MAX = 80_000
REVIEW_BRIEF_MAX = 120_000
REVIEW_BASE_MAX = 255            # the longest base branch name the brief takes, in bytes
REVIEW_DELIMITER_DRAWS = 20      # how many delimiters are drawn before the PR text is given up as unfenceable

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
