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

- [x] A park on a merged PR wakes; on an open PR it holds — test_park.py::GithubEvents::test_a_park_on_a_merged_pr_wakes_and_on_an_open_pr_holds + test_boss_pulse park-on-merge test pass
- [x] A park on CI wakes when all check runs of the PR head have concluded — GithubEvents::test_a_park_on_ci_wakes_when_every_check_run_of_the_head_has_concluded passes (queued/in-progress/no runs hold)
- [x] Repeated Stops within a minute make no new `gh` call for the same PR — GithubEvents::test_stops_within_a_minute_make_no_new_gh_call_for_the_same_pr passes (3 lookups, 1 call)
- [x] A `gh` failure keeps the park and writes a log line, never a crash — GithubEvents gh-failure, bad-output and timeout tests pass; log in pm/park-gh.log
- [x] A worker reporting "PR #N open, CI running" is auto-parked on `ci:` for that PR — worker parks itself via the reporting contract; test_boss_pulse ready-work-beside-a-parked-worker test shows Spawn, no IDLE NOW

PR not opened yet: waits for PR 164 to merge and a rebase on main. Status stays in-progress until then (commit 168d55a on pulse-park/04-park-github, 747 related tests pass).
