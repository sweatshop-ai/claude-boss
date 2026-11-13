# 40: Shrink the unread-stub baseline: the boss-run tests read their stubs

**What to build:** Ticket 36 made `Sandbox.cleanup()` fail a test that installs a `codex`, `claude`, `gh` or `tmux` stub and never reads its call log, and exempted the older tests through `skills/boss/unread_stub_baseline.txt`, a list that may only shrink. Tickets 38 and 39 brought 59 of them under the rule. This ticket brings the 31 `test_boss_run` entries under it and deletes their 31 lines. The baseline holds 93 entries after it.

`boss-run` is the gate's own reviewer path, so the reads say what the test is about, not only that a log was touched. How each test now reads its stubs, with no existing assertion weakened or removed:
- Every test that runs a review through Codex asserts `len(sandbox.calls_of("codex"))`: 1 for a single run, and for a test that loops, one call per command (`HardRules`: the nine commands that are not a merge), per answer (`VerdictParsing`: eleven cases; the tab and no-space test: two) or per round (the approve-noise test: one, then two).
- Where Opus answers, `calls_of("claude")` is 1; where Codex answered or a hard rule stopped the run, `claude` stays `assertNotCalled`, as it already did in most.
- The tests with a second sandbox read it too: the non-zero-exit test (`claude` once in the second) and the Codex-progress test (`codex` once in the second, which ends in exit 4).
- The `FailClosed` tests make `python3` a stub, so the chain never runs and the approving `codex` that `setUp` installs is never reached: a `tearDown` says `expect_unused("codex")`.

No test turned out to call a tool it should not: nothing to report as a finding.

**Blocked by:** 36, 39

**Status:** done (Vera built it)

- [x] The 31 `test_boss_run` baseline lines are deleted; the baseline holds 93 entries
- [x] Each of the 31 tests reads every stub it installs (`calls_of` for a tool the test expects called, `expect_unused` for one it must leave alone)
- [x] No existing assertion is weakened or removed
- [x] `test_boss_run.py` and `test_hermetic.py` pass
- [x] coverage.md's R25 rows give the new baseline size
- [x] CHANGELOG.md has the entry
