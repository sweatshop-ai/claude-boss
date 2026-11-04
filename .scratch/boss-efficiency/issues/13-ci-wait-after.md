# 13: The CI wait after the change, on a sample that can be read

**What to build:** nothing; a measurement. Repeat ticket 01's wait until the last job starts, for every repository whose "after" sample was too small on 2026-11-04, with the sample size and the pool load. Take it from ticket 04's routine if that reports it.

**Why:** ticket 01 found the PR matrix already gone from render-doc and sheaf since 2026-10-25/26. The audit's 100-minute figure mixes before and after. Ticket 01's final sample: render-doc PR p90 100 before, 4 after, on 40 runs; its main push after has only 14 runs.

**Blocked by:**
- 04
- External: about 40 PR runs after the change, around 2026-11-11

**Status:** waits for runs

- [ ] Before and after per repository, at least 40 runs after, with the pool load
- [ ] Why mail-replies' main-push wait rose from 19 to 70 minutes at p90 after 2026-10-25, unexplained on 2026-11-04
