# 39: Shrink the unread-stub baseline: the waiver and review track and brief tests read their stubs

**What to build:** Ticket 36 made `Sandbox.cleanup()` fail a test that installs a `codex`, `claude`, `gh` or `tmux` stub and never reads its call log, and exempted the older tests through `skills/boss/unread_stub_baseline.txt`, a list that may only shrink. Ticket 38 brought 28 of them under the rule. This ticket brings 31 more under it and deletes their 31 lines: the 14 `test_waiver`, the 12 `test_boss_review_track` and the 5 `test_boss_review_brief` entries. The baseline holds 124 entries after it.

How each test now reads its stubs, with no existing assertion weakened or removed:
- `test_waiver` (the `gh` stub was the unread one; its `tearDown` already reads `claude` and `codex`): the two waiver tests that succeed assert the comments (`len(self.comments())` is 1, and 2 for the second waiver), the post that fails asserts the one attempted comment, the command-line refusal asserts `assertNothingRecorded()`, and the ten tests that never reach `gh` (the six `Choose` tests, the empty command, the invalid track, the policy constants and the token expiry) say `sandbox.expect_unused("gh")`.
- `test_boss_review_track` and `test_boss_review_brief` (the `codex` stub was the unread one): every test that runs a review through Codex asserts `len(sandbox.calls_of("codex")) == 1`; the end-to-end test, whose stub is installed after four runs without one, asserts 2.

No test turned out to call a tool it should not: nothing to report as a finding.

**Blocked by:** 36, 38

**Status:** done (Nour built it)

- [x] The 14 `test_waiver`, 12 `test_boss_review_track` and 5 `test_boss_review_brief` baseline lines are deleted; the baseline holds 124 entries
- [x] Each of the 31 tests reads every stub it installs (`calls_of` for a tool the test expects called, `expect_unused` for one it must leave alone)
- [x] No existing assertion is weakened or removed
- [x] `test_waiver.py`, `test_boss_review_track.py`, `test_boss_review_brief.py` and `test_hermetic.py` pass
- [x] coverage.md's R25 rows give the new baseline size
- [x] CHANGELOG.md has the entry
