# 01: One Python version on PRs, the full matrix on main only

**What to build:** repositories whose PR suite still runs a Python matrix run one version on `pull_request` and the whole matrix on push to main. One repository already does this; copy its `matrix:` line. Measure the wait until the last job starts, per repository, before and after.

**Why:** measured 2026-11-04 on 3,407 runs in 7 repositories: waiting on CI was 25% of active worker hours (513 h), 29.5% of runs ended cancelled, and at the 90th percentile the last job started after about 100 minutes in three repositories. On one track, all workers sat on CI for 62 of its 159 hours.

**Blocked by:** None (can start immediately)

**Claimed by:** Kaveh 2026-11-05

**Status:** done

- [x] The repositories with a PR matrix are listed, each read from its workflow file (seven read; none has a PR matrix now, four lost theirs on 2026-10-25/26 by others' changes; seventh repo identified by elimination, see `ci-wait-2026-11-04.md`)
- [x] Each runs one version on PRs and the matrix nightly, with a green nightly run on record (amended 2026-11-04: render-doc and sheaf moved the matrix from main to nightly on 2026-10-25/26, on purpose, because three jobs held the pool for about 25 minutes per merge; that decision stands). Open because sheaf's nightly has been red on py3.14 since 2026-10-31 (`test_hub_lifecycle.py::test_a_hub_that_is_stopped_and_continued_keeps_running`); render-doc, mail-replies, tiroir-clients and tt-tiroir are green on 2026-11-04; owner being asked by Anton, not touched here; closed 2026-11-05: sheaf run 41990051404 (07:50Z, ca80ef5, the merge of PR 196), py3.11, 3.13 and 3.14 all success after three failed nightlies on 47fba4d; render-doc run 41988406977 (07:36Z, cdae0f6), the same three all success
- [x] Wait until the last job starts, before and after, per repository, with the sample size and the pool load; an after sample too small to read moves to ticket 13 (numbers in `ci-wait-2026-11-04.md`; pool load is a proxy, the API has no history; small after samples listed there go to ticket 13)
- [x] The reason for the cancelled runs is counted: superseded by a push, cancelled by a worker, other (1,045 of 3,529 cancelled; the API cannot split superseded from worker-cancelled except in claude-boss, which has no concurrency group; see `ci-wait-2026-11-04.md`)

Finding for Anton: tiroir-library-mcp has no matrix but waits a p90 of 75 to 100 minutes; its workflow runs on every push and on pull requests, so 126 of its 179 branch pushes duplicate a pull request run. Not changed; details in `ci-wait-2026-11-04.md`.
