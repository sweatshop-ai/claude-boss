# 45: a preset is classified by its identity, not by full equality, so boss-goal's fallback keeps the preset PATH

**What to build:** A bug found by the Codex re-review of PR 111 (ticket 21), real on main 0f6b17a (class b).

`claude_launch` decided `preset = fb in PRESETS.values()`, which is dataclass equality over every field. `boss-goal` always runs `--fallback opus --cwd DIR --fallback-tools Read,Grep,Glob`, so the Fallback `reviewer_chain` rebuilds (`allowed_tools` and a timeout set) was not equal to `OPUS`, was treated as custom and got the fully filtered child PATH. An activated checkout `.venv/bin` that an MCP server or hook needs was lost: the ticket-21 failure, on the boss-goal path.

`_is_preset` now classifies by identity: the preset's name and model, with no `extra_args` and no `env_unset` of its own. `allowed_tools`, `timeout` and `when` may differ. The two flags stay in the key because `boss_review.fallback_spec` is named `opus` on the preset's model and confines the child with exactly those; by name and model alone it would have turned into a preset and lost its filtered PATH. Callers checked: `boss-goal` and `boss-run` (both through `reviewer_chain --fallback`; `boss-run` passes no tools and was already a preset), `boss_review.py` `fallback_spec` (custom, unchanged). A genuinely custom Fallback gets what it got.

**Blocked by:** none

**Status:** done (Otilia built it)

- [x] A preset rebuilt with `allowed_tools` and a timeout (the boss-goal shape) keeps the preset PATH, `opus` and `fable`; the test fails on the old code
- [x] A Fallback on the preset's name and model with its own `extra_args` or `env_unset` (the `fallback_spec` shape) still gets the filtered PATH
- [x] A custom spec that unsets nothing still gets the filtered PATH (existing test)
- [x] The new tests read their stubs (ticket 36); no entry added to `unread_stub_baseline.txt`
- [x] CHANGELOG.md has the entry
