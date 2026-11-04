# 13: The CI wait after the change, on a sample that can be read

**What to build:** nothing; a measurement. Repeat ticket 01's wait until the last job starts, for every repository whose "after" sample was too small on 2026-11-04, with the sample size and the pool load. Take it from ticket 04's routine if that reports it.

**Why:** ticket 01 found the PR matrix already gone from render-doc and sheaf since 2026-10-25/26. The audit's 100-minute figure mixes before and after. render-doc's after had 13 PR runs, too few to say the wait fell.

**Blocked by:**
- 04
- External: about 40 PR runs after the change, around 2026-11-11

**Status:** waits for runs

- [ ] Before and after per repository, at least 40 runs after, with the pool load
