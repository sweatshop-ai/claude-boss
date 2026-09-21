# boss-jev: the boss is not woken for events that need nothing

`skills/boss/boss-jev.py`, a `UserPromptSubmit` hook (#77, 2026-09-18). Plan, evidence and the Codex
rounds: `~/.claude/plans/2026-09-18-boss-jev-hook.md`.

**The saving in this release is the idle-notice rule.** An idle notice that repeats a report the boss
already had wakes nobody: on Lucas's transcript (10:45–14:02, 2026-09-18) that is 24 of 51 idle wakes, decided
by code alone, with no Jev call and nothing leaving the machine. A boss turn costs its whole context whether it
reads a report or one line, so turns that never start are the only saving there is. Worker messages still wake
the boss; Jev's part is escalation and the restart proposal.

The hook sees each cross-session message and idle notice from the boss's own workers before the boss's turn
and does one of these:

| Event | What happens |
|---|---|
| idle notice repeating a report the boss already had (or stale, or the worker is busy again) | **absorbed**: no turn; the notice goes to `pm/<track>.jev-archive.md` |
| worker message, Jev `needs_owner` ≥ 0.85 | **escalation**: `[ladder` line in Open blockers, pane emoji, `boss-alert 0`; the boss wakes to speak and name the action. The report repeats on the boss's later wakes until `ask=` in the ladder line is filled (at most 6 times, 2 hours) |
| worker message, finished, every restart gate passed | the boss wakes with a **restart proposal** and the exact `boss-lifecycle.sh restart --require-idle …` command |
| anything else | the boss wakes as before, with one `[boss-jev]` line (Jev's three numbers and the decision) |

Worker messages are never absorbed in this release. The rule that would absorb them is evaluated on every
message and logged as `absorb-candidate`, so a week of advisory logs can show how often it would have fired
before anyone switches it on.

## Reading a week of advisory mode

In `advisory` (and with egress on, so messages are judged), `pm/.pulse/jev.log` gets one line per event:

```
<date> <time> <id> advisory <idle|message> <worker> (<coord>): tc 0.05 owner 0.07 redir 0.02 -> <action>: <reason>
```

`action` is what armed mode would do: `absorb` (idle notices only), `escalate`, `finished` (restart gates or
"dispatch due"), `wake`. A message the switched-off rule would have absorbed carries `[absorb-candidate]` in
its reason. `boss-jev.py stats` sums the day's counters: `seen`, `would_absorb`, `would_escalate`,
`would_finished`, `would_wake`, `absorb_candidate`, `passed`, `errors`. The absorb-candidate rate is
`absorb_candidate / (would_wake + would_finished)`; the idle saving is `would_absorb`. With egress off, messages
are not judged (they count as `passed`) and only the idle-notice numbers mean anything.

## Installing (the owner's hand)

1. The hook entry in `~/.claude/settings.json`. The command appends it to `hooks.UserPromptSubmit`,
   writes a dated backup next to the file, and does nothing if it is already there:

   ```
   ! python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-jev.py install-hook
   ```

   It adds exactly this (see it without writing: `boss-jev.py install-hook --print`):

   ```json
   {"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-jev.py hook", "timeout": 8}]}
   ```

2. Egress: lets worker messages go to TypeSafe (Jev), redacted. Without it, idle notices are still absorbed
   and every message wakes the boss exactly as today:

   ```
   ! echo on > ~/.claude/pm/.pulse/jev.egress
   ```

## Modes

`~/.claude/pm/.pulse/jev.mode`:
- `advisory` (default, also when the file is absent): the hook decides and logs what it **would** do.
  Nothing is blocked, written or posted, and nothing is added to the boss's context.
- `armed`: it acts. Honoured only while `$CLAUDE_CONFIG_DIR/pm/.pulse/jev-score.json` shows ≥ 0.95
  accuracy at confidence ≥ 0.85 on `task_complete` and `needs_owner` (it does: 1.000 on both).

Off: `echo advisory > ~/.claude/pm/.pulse/jev.mode`, or remove the hook entry from settings.json.

## Files

| Path | What |
|---|---|
| `pm/.pulse/jev-<boss session>.json` | state: dispatch memory, worker memory, escalations, counters (0600) |
| `pm/.pulse/jev.log` | one line per decision, including every advisory "would" (0600) |
| `pm/<track>.jev-archive.md` | armed only: every event the hook judged, with its body (0600, local) |

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-jev.py stats` prints the mode, the egress switch and the counters per
day: `seen`, `absorbed_idle`, `escalated`, `woken`, `passed`, `errors`, `absorb_candidate` (messages the
switched-off message rule would have absorbed), and `would_*` in advisory.

## For workers: the handoff footer

A restart is proposed only if the worker's newest `handoff-*.md` (after the boss's last dispatch) ends with
the footer for its own session and the dispatched task number. Print it with:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-jev.py footer --task <N> --repos <repo>[,<repo>]
```

## Every failure wakes the boss

A malformed payload, an unknown sender, a lock held by another run, Jev slow or wrong, a leak in the request,
a state or archive write that fails: the hook prints nothing and the prompt goes through (in armed mode a held
lock adds one "not judged" line, so the event is not taken for a handled one). The harness also lets
the prompt through when a hook overruns its timeout (tested on a throwaway, 2026-09-18).

## Known limit (residual risk 8, accepted by Lucas 15:03)

The hook payload says nothing about where a prompt came from. An exact copy of a whole harness idle notice,
typed or pasted into a boss pane, naming a subscribed worker that has already reported, is absorbed like the
real notice. The typer sees "…blocked by hook: boss-jev absorbed: …" and retypes. Anything short of an exact
copy is not an idle notice and goes through.

## Tests

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-jev.py --selftest
```

93 tests: the #76 replay, the idle rule, identity and binding, the finish-time rules, escalation steps and
recovery, redaction, the state file, the fail-open paths, the tracker and archive files, `boss-panes.py
--state`, and `boss-lifecycle.sh --require-idle` against a stub tmux.
