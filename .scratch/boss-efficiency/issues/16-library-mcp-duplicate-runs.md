# 16: library-mcp runs its suite twice for most pushes

**What to build:** `thinkingtoo/tiroir-library-mcp` runs `tests.yml` on every push and on pull requests, so a pushed branch with a PR runs the suite twice on one commit: 126 of 179 branch pushes since 2026-10-01 duplicate a PR run. Remove the duplicate and keep what the workflow's comment asks for, that a branch without a pull request still shows a result. The first thing to try is dropping the `pull_request` trigger and keeping `push`; a push's checks show on the PR's head commit. Check what a pull request loses (the merge-commit test, and anything required by a rule) and say so.

**Why:** ticket 01 found this repository never had a matrix and still waits 75 minutes at p90 on PRs and 100 on pushes, with the highest load of the seven. Numbers: `.scratch/boss-efficiency/ci-wait-2026-11-04.md`.

**Blocked by:** None (can start immediately)

**Claimed by:** Yara 2026-11-04 21:33

**Status:** done

- [x] The change is merged, with a green run on main on record (PR 227 merged as e20a4c4; main push run https://github.com/thinkingtoo/tiroir-library-mcp/actions/runs/41911317136 success, total_count 1)
- [x] A pushed branch with a PR runs the suite once, and a pushed branch without a PR still runs it, each shown by a run URL (no PR: .../actions/runs/41907967336; with PR #227: .../actions/runs/41908217190, check-runs total 1, success)
- [x] What a pull request gives up is stated in the PR (thinkingtoo/tiroir-library-mcp#227, Merge Danger)
