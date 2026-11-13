# 46: Shrink the unread-stub baseline: the boss-review and boss-goal tests read their stubs

**What to build:** Ticket 36 made `Sandbox.cleanup()` fail a test that installs a `codex`, `claude`, `gh` or `tmux` stub and never reads its call log, and exempted the older tests through `skills/boss/unread_stub_baseline.txt`, a list that may only shrink. Tickets 38, 39 and 40 brought 90 of them under the rule. This ticket brings the 35 `test_boss_review` and 5 `test_bin` entries under it and deletes their 40 lines. The baseline holds 53 entries after it, all `test_reviewer_chain` (ticket 45 owns those).

`boss_review` is the PR gate, so the reads say what each test is about. In `test_boss_review.py` the `Base` class already reads `claude` and `gh` in `tearDown`; the unread stub was always `codex`, and each test now asserts through `assertAsked(times)` (a count of `calls_of("codex")`) that the reviewer was asked exactly as often as the test means:
- Once for a review that reached the reviewer (a posted GO or NO-GO, no verdict, a moved head, a failed post, a failed write, a refused directory), and once per round of a loop that resets the sandbox (`setUp_clean`).
- None where Codex is absent (the `absent` case of the no-reviewer test).
- Twice where a test runs two reviews (the retry after a failed post, the second round, the three concurrent tests); `assertLockIsFree` asserts the review it runs asks Codex once more than before.

In `test_bin.py` the five `GoalReviewers` tests assert one `codex` call, and `claude` once where Opus or Fable answers (`claude` stays unasked where Codex answered).

No existing assertion is weakened or removed, and no test turned out to call a tool it should not: nothing to report as a finding.

**Blocked by:** 36, 40

**Status:** done (Nadia built it)

- [x] The 35 `test_boss_review` and 5 `test_bin` baseline lines are deleted; the baseline holds 53 entries
- [x] Each of the 40 tests reads every stub it installs (`calls_of` for a tool the test expects called)
- [x] No existing assertion is weakened or removed
- [x] `test_boss_review.py`, `test_bin.py` and `test_hermetic.py` pass
- [x] coverage.md's R25 rows give the new baseline size
- [x] CHANGELOG.md has the entry
