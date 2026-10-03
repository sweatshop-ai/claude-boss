# 01: One reviewer chain, shared

**What to build:** the chain that picks a reviewer (Codex first, a fallback model next, otherwise "no reviewer answered") lives in one place that `boss-run` and the coming PR review command both call. `boss-run` behaves exactly as it does today: Codex, then Haiku, otherwise exit 4 with nothing run. The chain takes the fallback model as a parameter so the PR gate can choose a different one.

**Blocked by:** None (can start immediately)

**Claimed by:** Anouk 2026-10-03 23:54

**Status:** in-progress

- [ ] One module owns the reviewer chain; `boss-run` holds no reviewer logic of its own
- [ ] The fallback model and the timeout are parameters, with `boss-run`'s current values as its defaults
- [ ] The result says which reviewer answered (`codex`, the fallback's name, or `none`)
- [ ] Existing `boss-run` tests pass unchanged; new tests cover the three outcomes with stubbed `codex` and `claude` binaries (no real calls)
