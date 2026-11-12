# 38: Shrink the unread-stub baseline: the recheck and Codex health tests read their stubs

**What to build:** Ticket 36 made `Sandbox.cleanup()` fail a test that installs a `codex`, `claude`, `gh` or `tmux` stub and never reads its call log, and exempted 183 older tests through `skills/boss/unread_stub_baseline.txt`, a list that may only shrink. This ticket brings 28 of them under the rule and deletes their 28 lines: the 27 `test_boss_recheck` entries and the 1 `test_codex_health` entry. The baseline holds 155 entries after it.

How each test now reads its stubs, with no existing assertion weakened or removed:
- `test_boss_recheck.Base.codex_heads()` (the heads the `codex` stub noted) also reads `sandbox.calls_of("codex")` and asserts one logged call per noted head, so every test that checks which heads were reviewed now checks the call log too. Tests whose pass reviews a PR and did not look at the heads now assert the head that was reviewed (`[head]`).
- A test that starts no review (an empty list, a worktree check with no entry, a usage error, an unusable or unreadable tracker, the id arithmetic) says `sandbox.expect_unused("codex")`.
- `test_codex_health.Command.test_health_itself_still_raises_...` calls `health()` in process and says `expect_unused` for `codex`, `claude` and `gh`.

No test turned out to call a tool it should not: nothing to report as a finding.

**Blocked by:** 36

**Status:** done (Pablo built it)

- [x] The 27 `test_boss_recheck` and the 1 `test_codex_health` baseline lines are deleted; the baseline holds 155 entries
- [x] Each of the 28 tests reads every stub it installs (`calls_of` for a tool the test expects called, `expect_unused` for one it must leave alone)
- [x] No existing assertion is weakened or removed
- [x] `test_boss_recheck.py`, `test_codex_health.py` and `test_hermetic.py` pass
- [x] coverage.md's R25 rows give the new baseline size
- [x] CHANGELOG.md has the entry
