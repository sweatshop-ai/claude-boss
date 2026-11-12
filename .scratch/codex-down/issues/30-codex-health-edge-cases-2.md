# 30: Codex health, edge cases found in the review of 18 (class c and d)

**Blocked by:** 18

**Status:** ready-for-agent

Found by the fallback review of PR 109 (`18-reviews/round-1.md`, GO). No round blocked on them.

- [ ] Class d: `test_duplicate_keys_are_skipped_not_resolved_to_the_last` (`test_codex_health.py`) only differs from main in `skipped`. Put the duplicate line after an `F` (last key `codex`, first `opus`), so main gives `answers` 1 and `failures` 0 and the branch gives `failures` 1.
- [ ] Class d: `test_a_torn_write_swallows_the_next_attempt` passes on main (accepted behaviour) and pins two docstring phrases, so rewording the docstring breaks it. Keep the count assertions and drop the docstring-word asserts, or say so in the test.
- [ ] Class d: `05b-policy-and-codex-health.md` box says the command exits 0; add "exits 2 with the error on stderr when the log exists but cannot be read (ticket 18)".
- [ ] Class c: the duplicate-key hook rejects a repeat at any depth; a future writer dumping a dict with `{1: x, "1": y}` would have every such line skipped silently, which could hide an outage. Today's writer has no such field. Decide: leave, or count skipped lines above a threshold in 05c.
