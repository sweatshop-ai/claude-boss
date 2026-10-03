# 01: One reviewer chain, shared

**What to build:** the chain that picks a reviewer (Codex first, a fallback model next, otherwise "no reviewer answered") lives in one place that `boss-run` and the coming PR review command both call. `boss-run` behaves exactly as it does today: Codex, then Haiku, otherwise exit 4 with nothing run. The chain takes the fallback model as a parameter so the PR gate can choose a different one.

**Scope:** the chain as `boss-run` and the PR review command use it. `boss-goal`'s own copy of the chain (`ask_second_model`) is not moved here; it is logged as a follow-up. Amended 2026-10-04 after Codex review 1 of the plan (`plan-review-codex-1.md`, findings 1, 2, 3, 6) and the owner-accepted premortem (R2, R3, R11, R12, R13, R25).

**Blocked by:** None (can start immediately)

**Claimed by:** Anouk 2026-10-03 23:54

**Status:** in-progress

- [ ] One module owns the reviewer chain; `boss-run` holds no reviewer logic of its own
- [ ] The fallback model and the timeout are parameters, with `boss-run`'s current values as its defaults
- [ ] The result says which reviewer answered (`codex`, the fallback's name, or `none`)
- [ ] Existing `boss-run` tests pass unchanged; new tests cover the three outcomes with stubbed `codex` and `claude` binaries (no real calls)

Added after Codex review 1 and the premortem:

- [ ] The fallback is optional: with none given, the chain is Codex only and a Codex failure gives `none` (ticket 02 uses this)
- [ ] The result is structured: `reviewer`, `output` (the answering reviewer's raw answer), `parsed`, `attempts`; the module writes no file, the caller keeps the output
- [ ] The verdict words are a parameter (`APPROVE`/`REJECT` for `boss-run`, `GO`/`NO-GO` for the PR command)
- [ ] The fallback is a spec (name, exact model id, optional tool restriction) that the caller passes in; 01 carries the restriction to the `claude` call, ticket 03 chooses and tests it
- [ ] Each attempt carries a reason from a closed set: `answered`, `absent` (not on PATH), `timeout`, `error` (non-zero exit), `noverdict` (answered, no usable VERDICT line); `timeout` and `error` stay distinct; `error` keeps the exit code and a stderr tail in the result, and `boss-run` prints nothing new
- [ ] Verdict words match whole tokens, longest first: `VERDICT: NO-GO` never parses as `GO` (tested); the first VERDICT line wins by default, as `boss-run` does today; a strict flag turns conflicting VERDICT lines into `noverdict`, off by default
- [ ] The timeout is per reviewer (Codex and the fallback apart), defaults 120 and 120 as today
- [ ] The result records the exact model id the fallback ran with; `boss-run` still logs reviewer `haiku`
- [ ] Tests are hermetic: a stub directory first on PATH, each stub appends to a call log the test asserts on, and a guard fails the test if `codex`, `claude` or `gh` resolves outside the stub directory; no real calls
- [ ] `boss-run`'s exit codes 2, 3, 4 and 5, its reviewer names and its nine log fields are pinned by tests that pass on the code before the move and after it
