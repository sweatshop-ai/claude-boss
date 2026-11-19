# 04: Park on a PR merged or CI finished, and the automatic park on a worker's own PR

**What to build:** two more park events, `pr:<owner/repo#N>-merged` and
`ci:<owner/repo#N>`, checked with `gh` and cached (at most one call per PR per minute) so the
Stop hook stays fast and works offline (a failed check keeps the park, logs it). A worker whose
last report names its own open PR and that is waiting on CI or review gets a park on its PR's
CI without the boss doing anything; it keeps its PR, and the pulse counts the work around it as
unassigned so the boss spawns rather than pulling the worker off. First establish where a
worker's PR is recorded today (report, tracker, seat); if it is nowhere, this ticket adds that
record to the worker's report path.

**Blocked by:** 03

**Claimed by:** Talia 2026-11-19 18:03

**Status:** in-progress

- [ ] A park on a merged PR wakes; on an open PR it holds
- [ ] A park on CI wakes when all check runs of the PR head have concluded
- [ ] Repeated Stops within a minute make no new `gh` call for the same PR
- [ ] A `gh` failure keeps the park and writes a log line, never a crash
- [ ] A worker reporting "PR #N open, CI running" is auto-parked on `ci:` for that PR
