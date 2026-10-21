# 02: The first read of a big GitHub graph leaves the pulse silent

**What to build:** with no cache yet, `boss-pulse.py` reads a `gh:` graph for at most
3 s. When that times out it starts a background refresh and returns an empty, unbroken
frontier, so with no idle worker, rung or blocker the pulse says nothing, and the
refresh finishing does not wake it. Ready tickets wait for an unrelated turn. Return a
"frontier loading" state that keeps the boss's turn alive once (the pulse's rate limit
already caps it), or tell the boss to run `boss-goal check <track>`, which reads the
graph without a time limit and saves the cache.

Found by Codex review 3 of PR 20 (head 7f082c9), [P2], `skills/boss/boss-pulse.py:204-205`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A test where the fake `gh` sleeps past `GH_FIRST_S` with no cache: the pulse
      still emits a line naming the graph as loading and what to run
- [ ] No second message while the refresh is still running (rate limit holds)
