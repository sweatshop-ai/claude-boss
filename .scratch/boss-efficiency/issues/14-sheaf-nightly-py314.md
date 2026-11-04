# 14: sheaf's nightly is red on Python 3.14

**What to build:** diagnose why `tests/test_hub_lifecycle.py::test_a_hub_that_is_stopped_and_continued_keeps_running` fails with `assert (0 is None)` on py3.14 in the nightly, from 2026-10-31, and fix what the diagnosis names: the test, the py3.14 behaviour, or the hub. The test file last changed on 2026-10-23, and the failure starts later, so find what moved on 10-31.

**Why:** ticket 01's matrix runs at night, so a nightly that stays red for five nights means the matrix protects nothing. Ticket 01 needs a green nightly on record.

**Constraints:** do not tag sheaf: another track pins it by sha. If this is a real hub fault rather than a test or py3.14 fault, the boss tells that track's boss before the fix merges.

**Blocked by:** None (can start immediately)

**Claimed by:** Oskar 2026-11-04 21:29

**Status:** done

- [x] The cause is named, with the run and the command that show it: sheaf#78 guard took CPython's unfilled sigtimedwait siginfo (si_signo 2 on 3.14) for SIGINT; failing run 41792145531 (first red 41178289633, last green 41017156953); `nice .venv/bin/python -m pytest tests/test_hub_lifecycle.py::test_a_hub_that_is_stopped_and_continued_keeps_running` failed 5/5 on 3.14.9, probe results in sheaf PR 195
- [x] The fix is merged, or the finding is reported if the fault is not in sheaf: PR 195 merged as 11ae9522692f2e677aabbd29d26fbb7aa117efd6 (CI success on 8d03fbc), not tagged; follow-ups in ticket 20; Codex follow-up owed
- [x] A nightly run with py3.14 is green on record: manual workflow_dispatch python=3.14 on main at 11ae952, run 41914458641, ubuntu-24.04 py3.14 success, https://github.com/sweatshop-ai/sheaf/actions/runs/41914458641 (tonight's 01:00 schedule is the second record)
