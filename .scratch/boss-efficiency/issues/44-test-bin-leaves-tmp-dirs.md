# 44: test_bin leaves its temporary directories in /tmp

**What to build:** `class Tools` in `skills/boss/test_bin.py` (`setUp`, lines 121-122) makes two directories per test with `tempfile.mkdtemp` (`boss-bin-cfg-`, `boss-bin-home-`) and never removes them; `GoalReviewers` and the two later classes do clean up (`addCleanup`). Add an `addCleanup` that removes both.

**Measured 2026-11-05:** one run of `python3 -m unittest test_bin` with `TMPDIR` pointing at an empty private directory left 20 `boss-bin-home-*` and 20 `boss-bin-cfg-*` directories, 89 inodes, 53 tests run. That is 40 directories per run, not 700: the 700 the boss saw is about 17 runs' worth, accumulated by workers re-running the file. `/tmp` showed 15% of its inodes used (157099 of 1048576) when this was checked, none of these directories left, so the 97% of earlier today is not reproduced now.

**Why:** every run adds to /tmp, and on this laptop many sessions run tests all day.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Status:** ready-for-agent

- [ ] Test or check first: a run of `test_bin` with a private `TMPDIR` leaves no `boss-bin-*` directory
- [ ] The count after the fix is 0, stated here
