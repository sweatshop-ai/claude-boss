# 01: ci_state(repo, branch): is this branch's work waiting on CI, and until when

**What to build:** one small read-only module, written here and vendored by agentview the
way `registry.py` is (header + `scripts/vendor-registry`). Agreed with Tarek (agentview),
2026-10-21.

`ci_state(repo, branch) -> {status, conclusion, queued_for_s, running_for_s, eta_s, run_url}`
from GitHub's `actions/runs` (`status` queued / in_progress / completed, `created_at`,
`run_started_at`, `updated_at`). Status is a fact. The ETA is an estimate: the median
duration of that workflow's recent successful runs, minus the elapsed time.

Constraints from agentview (Tarek):
- **Never blocks the caller.** agentview's poll path reads only local files, and reads
  that hung the poll were hunted down before. Network calls happen off the caller's path,
  with a hard timeout, and the cached value is served while a refresh runs.
- **Failure is a value.** gh/auth failure, rate limit or no network return
  `status: "unknown"`, never raise.
- **Keyed by repo + branch.** agentview has the branch per session (`providers/claude.py`,
  `m["branch"]`) and the repo from the cwd's remote (`projects.py _remote`), not a head sha.
- **No queue position.** `actions/runs` does not give it, and counting free runners needs
  the org runners API with admin scope.

Why: on sweatshop-ai/render-doc a run takes 45-95 min and waited up to 2 h for a runner
(2026-10-21). A worker whose PR is queued or running is waiting on CI, not working: the
boss should not read it as stuck or idle, and agentview could show it.

**Blocked by:** None (can start immediately)

**Status:** done (PR 21)

- [x] Tests with a fake `gh`: queued, in_progress, completed, gh failure -> unknown, a slow
      gh never delays the caller past the cache read (`skills/boss/test_ci_state.py`, 12 tests)
- [x] Vendor header so agentview can copy it unchanged (agentview's use: Thierry said yes
      on 2026-10-21, Tarek builds it)
- The boss pulse using it moved to ticket 02.
