# 01: Rebase only on a conflict or an overlap, not after every merge

**What to build:** a merge rule in `skills/boss/SKILL.md` (P8) for every boss, taken from
sheaf-v2 (Malik, 2026-10-21). After a PR lands, another open PR rebases only when

- git reports a conflict, or
- the files of what just landed overlap the PR's own files:
  `git diff --name-only <old base> origin/main` intersected with the PR's diff.

Otherwise it merges at its tested head: a `pull_request` run already tested the merge
commit with base as it was at trigger time. Main's push run is the net: a red main gets a
revert PR or a fix first, before anything else merges.

Why (sweatshop-ai/render-doc, 2026-10-21, `gh api repos/sweatshop-ai/render-doc/actions/runs`):
13 of the last 30 CI runs were cancelled. `ci.yml` has
`concurrency: cancel-in-progress` for pull requests, so every force-push after a rebase
kills the run in progress. A run takes 45-95 min on three shared t-compute runners; one
waited 2 h in the queue (created 16:33, started 18:39). The boss now runs up to 12
workers, so more PRs are open at once and the old rule costs more.

The overlap check stays because textual merges hide semantic coupling (sheaf: page.js and
live.py, PRs #105/#107).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] P8 states the rule, with the overlap command and the red-main rule
- [ ] A helper prints REBASE or MERGE for one PR (`gh pr view --json files`, the landed
      range) with a test on a fake repo: no overlap -> MERGE, overlap -> REBASE, conflict -> REBASE
