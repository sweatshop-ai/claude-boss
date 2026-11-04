# PR 50, round 1: Opus fallback (fresh agent), head 40d716f. Codex follow-up owed (back at 23:38)

Verdict: GO. RequireIdle tests ran hermetically: 21 passed.

Checked, all VERIFIED (line read): wait loop boss-lifecycle.sh:340-349 only sleeps and re-reads; the session, pin and `st == idle` checks (359) run on the last read; `shell` still refused before /exit; restart reaches the wait through the global WAIT_IDLE (cmd_retire at 439); the widened post-/exit check (372) is safe because turns started by a task notification or cross-session message write an `enqueue` record that transcript.py:99-101 counts in the past-exit pin; `--wait-idle --force` is rejected by the number check (70).

Minor findings, not blocking, left open as a ticket (a change now would need another round):
1. `--wait-idle 08` is read as octal in the arithmetic (:344): the loop is skipped and it dies "still busy after 08 s" without waiting. Nothing typed. Fix: `$((10#$WAIT_IDLE))`.
2. Non-numeric BOSS_RETRY_EVERY: `sleep` fails, set -e stops the script, no ERROR line. Nothing typed.
3. BOSS_RETRY_EVERY=0 runs a python status read in a tight loop for up to WAIT_IDLE seconds; floor it at 1.
4. Design: `--wait-idle` with `--expect-last` always ends refused when a wait happened (the turn writes new records); without a pin it restarts after whatever turn ran meanwhile, including a task a peer gave it. SKILL.md:272 recommends no pin.
Untested: non-numeric `--wait-idle`, `--wait-idle --force`.
