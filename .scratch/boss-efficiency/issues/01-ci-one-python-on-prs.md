# 01: One Python version on PRs, the full matrix on main only

**What to build:** repositories whose PR suite still runs a Python matrix run one version on `pull_request` and the whole matrix on push to main. One repository already does this; copy its `matrix:` line. Measure the wait until the last job starts, per repository, before and after.

**Why:** measured 2026-11-04 on 3,407 runs in 7 repositories: waiting on CI was 25% of active worker hours (513 h), 29.5% of runs ended cancelled, and at the 90th percentile the last job started after about 100 minutes in three repositories. On one track, all workers sat on CI for 62 of its 159 hours.

**Blocked by:** None (can start immediately)

**Status:** ready

- [ ] The repositories with a PR matrix are listed, each read from its workflow file
- [ ] Each runs one version on PRs and the matrix on main, with a green main run on record
- [ ] Wait until the last job starts, before and after, per repository, with the sample size
- [ ] The reason for the cancelled runs is counted: superseded by a push, cancelled by a worker, other
