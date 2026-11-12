# 36: The Sandbox fails a test that never reads the call log of a stub it installed

**What to build:** R25 says every new test asserts its stubs were called and fails if `codex`, `claude`, `gh` or `tmux` resolves outside the stub directory. The second half is enforced by `Sandbox.guard` in `skills/boss/hermetic.py`; the first was a per-test habit (goal audit 2026-11-12, gap 8). `Sandbox.cleanup()` now raises when a test installed a stub for one of those four tools and never read its call log. Reading it is `sandbox.calls_of(name)`; a test that expects the tool never to be called says so with `sandbox.expect_unused(name)`, which asserts zero calls and counts as a read. Silence does not pass.

The blast radius was measured before the design: 183 of 984 tests in the 17 Sandbox test files install a stub and read none of its log (the CI count of a draft run with the rule on; the base test classes install default stubs for all three and each test reads the ones it needs). That is far over the limit for one PR, so the rule is a ratchet: `skills/boss/unread_stub_baseline.txt` lists those 183 test ids (`module.Class.test_name`, nothing else), and `Sandbox` exempts exactly them. A test outside the list that leaves a stub unread fails; a listed test that now reads every stub it installs also fails, with the line to delete, so the list can only shrink. A test with several Sandboxes counts as one.

**Blocked by:** none

**Status:** done (Bettina built it, PR 129). The baseline holds 183 entries and may only shrink; "every new test" is true, "every test" is not yet.

- [x] A test proves a Sandbox fails a test that never reads its stub log, and passes one that reads it or declares it unused (`skills/boss/test_hermetic.py`)
- [x] `expect_unused` fails when the stub was called
- [x] A test proves a new test outside the baseline fails, a listed test may leave a stub unread, and a listed test that reads everything must come off the list
- [x] The baseline is generated from a CI run of the rule with an empty baseline, never on the laptop, and holds test ids only (a test checks the form)
- [x] coverage.md's R25 rows say the rule is enforced, the baseline size and that it may only shrink
- [x] CHANGELOG.md has the entry
