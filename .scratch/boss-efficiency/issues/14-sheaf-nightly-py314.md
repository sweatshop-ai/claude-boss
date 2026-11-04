# 14: sheaf's nightly is red on Python 3.14

**What to build:** diagnose why `tests/test_hub_lifecycle.py::test_a_hub_that_is_stopped_and_continued_keeps_running` fails with `assert (0 is None)` on py3.14 in the nightly, from 2026-10-31, and fix what the diagnosis names: the test, the py3.14 behaviour, or the hub. The test file last changed on 2026-10-23, and the failure starts later, so find what moved on 10-31.

**Why:** ticket 01's matrix runs at night, so a nightly that stays red for five nights means the matrix protects nothing. Ticket 01 needs a green nightly on record.

**Constraints:** do not tag sheaf: another track pins it by sha. If this is a real hub fault rather than a test or py3.14 fault, the boss tells that track's boss before the fix merges.

**Blocked by:** None (can start immediately)

**Claimed by:** Oskar 2026-11-04 21:29

**Status:** in-progress

- [ ] The cause is named, with the run and the command that show it
- [ ] The fix is merged, or the finding is reported if the fault is not in sheaf
- [ ] A nightly run with py3.14 is green on record
