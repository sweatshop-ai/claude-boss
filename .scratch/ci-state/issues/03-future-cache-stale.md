# 03: A future-dated cache is served past the stale limit when refreshes fail

**What to build:** after the clock steps back, `ci_state()` gives a cache dated in the
future the age `MAX_AGE_S + 1` (`skills/boss/ci_state.py`, the `age < 0` branch), so a
refresh starts. If that refresh and every later one fail, the cache keeps its future
mtime, its age never passes `STALE_S`, and an obsolete queued/running answer is served
for the whole clock offset plus 15 minutes. Treat a future-dated cache as stale for
serving (read as `unknown`) while still starting the refresh.

Found by Codex review 3 of PR 22 (head 0f3e1bc, merged as 8d2a491), [P2].

**Blocked by:**
- 01: ci_state(repo, branch)

**Status:** ready-for-agent

- [ ] A test: cache mtime 2 h ahead, fake `gh` failing: the read is `unknown` and a refresh was attempted
