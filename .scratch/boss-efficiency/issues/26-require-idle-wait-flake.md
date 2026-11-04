# 26: RequireIdle success-path tests spend a 2 s wall-clock wait on slow reads

**What to build:** `RequireIdle::test_a_busy_worker_is_retried_until_its_turn_ends_and_nothing_is_typed_before` failed once on main (merge 54de129, Actions run 41930248784, job 126925011540) with "still busy after 2 s"; six later main runs and PR 54's head passed. Fix: PR from branch `jonas/ticket-26-require-idle-flake`, test file only.

**Blocked by:** None (can start immediately)

**Claimed by:** Jonas 2026-11-05 00:30

**Status:** done

PR 58 merged as af13162 (head 6e12be1, squash). Reviews: `.scratch/boss-efficiency/reviews/pr-58-round0-code-review.md` and `pr-58-opus-verdict.md` (GO). Codex follow-up owed (Codex out until 04:38).

Cause (VERIFIED by reproduction): `retire_require_idle` in `skills/boss/boss-lifecycle.sh` loops `while still_busy && (( SECONDS - t0 < WAIT_IDLE ))`, a wall-clock budget. The test passes `--wait-idle 2` with `BOSS_RETRY_EVERY=1` and rows busy, busy, idle: it needs two sleeps and three status reads, and gives up if the first retry's sleep plus read already took 2 s, which leaves under 1 s of slack for one read. The failing job's log shows the first test group stalled for 93 s, so a status read crossed 1 s. Bash `SECONDS` counts whole seconds, so the 2 s budget can also run out on a fast runner (reviewer measured a difference of 2 for a 1.15 s sleep in 2 of 12 runs); a slow read makes it likelier. The script is correct: the budget is meant to be wall-clock.

Reproduction: a throwaway wrapper that adds a 1.1 s sleep to the stub `boss-panes.py --state` and runs the single test at nice 19 fails with the CI message (`ERROR: %5 is still busy after 2 s`); without the delay it passes in 2.6 s.

Siblings checked with the same 1.1 s delay:
- [x] `test_shell_and_waiting_are_retried_and_the_wait_can_end_in_a_refusal` (second half, shell, shell, idle): fails the same way. Fixed.
- [x] `test_the_wait_does_not_forgive_a_changed_session_or_input`, `test_a_pin_cannot_hold_across_a_wait_and_the_refusal_says_so`, `test_a_wait_written_with_a_leading_zero_is_read_as_decimal` (8 s), `test_the_wait_keeps_waiting_on_a_shell_with_the_turn_over_unless_stop_shells`: need one retry only; the last read is idle or the expected refusal comes either way. Pass under the delay, unchanged.
- The tests that expect "still busy after N s" are unaffected: a slow read only makes them refuse sooner, with the same words.
