# PR 50, mattpocock code-review (two axes), commit before the rebase onto 3f34dcc

## Standards (no documented standard; style of boss-lifecycle.sh and its tests)
No hard violations. Judgement calls, none acted on except where noted:
- Duplicated Code: the state set is spelled in several inline regexes; a named constant next to SHELL_CMDS would match the file idiom.
- Duplicated Code: the `--state` read plus `IFS read` appears three times in retire_require_idle (a read_state helper).
- Mysterious Name: WAIT_IDLE holds seconds (WAIT_IDLE_SECS).
- Primitive Obsession: BOSS_RETRY_EVERY is not validated (a non-number makes `sleep` fail under set -e; the script stops).
- Shotgun Surgery: the option list is copied in the header, the usage die and the pairing error.

## Spec (ticket 18 plus the false-turn brief)
- Box 1 (count) missing from the diff: it is in the ticket and PR text, not in code. Done outside the diff.
- Box 2: the idle-notice cause is not shown. Open, stays unticked.
- Retry test called retire, not restart: ADDED `test_restart_waits_too_and_types_nothing_at_a_worker_that_stays_busy`.
- Scope creep / safety: accepting `shell` before /exit was unverified. ACTED ON: measured live in an isolated tmux server, `shell` is read mid-turn (a turn waiting on a Monitor), so it is NOT accepted before /exit any more; it is retried. Tests added for shell and waiting retried to the limit.
- Missing tests for `waiting` kept in the retry loop to timeout (a concierge holding a question): ADDED.
- Open: a turn that is `waiting` with no new transcript record in the gap would read as no turn (no counter-case found, no test).
