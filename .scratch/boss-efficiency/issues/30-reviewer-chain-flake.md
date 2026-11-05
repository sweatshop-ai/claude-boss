# 30: The reviewer chain's SIGKILL test failed once on main

**What to build:** `skills/boss/test_reviewer_chain.py`, `Timeouts::test_a_reviewer_that_ignores_term_is_killed_after_the_grace_period` failed with "SIGKILL never followed SIGTERM" on merge 482b0e4 (line 234, 1 of 622), and passed on the next push. Find out whether the test is tight on a loaded runner or the chain really fails to kill a reviewer that ignores SIGTERM on some path; a real miss would leave a reviewer running with no limit. Then fix whichever it is. Also list every test failure on main in the last 14 days from the run logs, so that the next flake is on the list and not a surprise.

**Blocked by:** None (can start immediately)

**Claimed by:** Aurelio 2026-11-05 01:40

**Status:** done

- [x] The cause, shown from a reproduction or the code
- [x] The fix, with what the test proves unchanged
- [x] The list of main's test failures over 14 days, with a count per test

PR 62 merged as 703f4b5 (head d2618a6, squash). Reviews: `.scratch/boss-efficiency/reviews/pr-62-round0-code-review.md` and `pr-62-opus-round1.md` (GO). Codex follow-up owed (Codex out until 04:41).

Cause (VERIFIED by reproduction, PR 62): the test was tight; the chain kills correctly. `_stop` in `skills/boss/reviewer_chain.py` sends SIGTERM to the process group, waits `TERM_GRACE` on the leader, then sends SIGKILL to the group in every case, and reaps only the leader. A killed child leaves the process table a moment later; the test asked once, at once. Throwaway harness running the real `_stop` on a TERM-ignoring group at nice 19: child still listed right after in 162 of 200 rounds (24 of 30 in a second run), gone 1 s later in 30 of 30. Fix: both child checks in `Timeouts` poll up to 10 s; a mutant using `os.kill` for `os.killpg` fails the test after the poll.

Main failures, 14 days (`gh run list --branch main --status failure --created >=2026-10-22`): 2 runs.
- 41930248784 (2026-11-04 23:01): `RequireIdle::test_a_busy_worker_is_retried_until_its_turn_ends_and_nothing_is_typed_before`, 1 (ticket 26, fixed).
- 41942504002 (2026-11-05 00:35): `Timeouts::test_a_reviewer_that_ignores_term_is_killed_after_the_grace_period`, 1 (this ticket).
No test failed more than once.
