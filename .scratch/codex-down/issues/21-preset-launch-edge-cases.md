# 21: edge cases of the presets' claude resolution (ticket 15)

**What to build:** three leftovers from the review of PR 98.
- [x] The preset's child gets the filtered PATH, not only the lookup of `claude`: an MCP server or hook the preset loads (presets pass no `--strict-mcp-config`) that is found only through a relative PATH entry or a venv under the checkout no longer starts. Decide whether to keep the owner's PATH for the child and filter only the lookup of `claude`.
- [x] With no `--cwd` (boss-run, boss-goal) a preset keeps absolute PATH entries under the current directory (an activated `.venv/bin`) and symlinks into it: no worse than before ticket 15, but no longer covered by the filter.
- [x] `CONTEXT.md` and `CHANGELOG.md` do not say that `--fallback opus|fable` now resolves `claude` through the filtered PATH.

**Origin:** Fallback review 1 of PR 98 (Opus, Codex unavailable). Class c and d.

**Blocked by:** 15

**Claimed by:** Faisal 2026-11-12

**Status:** done (Faisal built it, PR 111, merge 9d32bb6)

**Evidence:** box 1: `reviewer_chain.py` `claude_launch` (child_keep vs keep), `test_a_preset_child_keeps_an_absolute_entry_inside_the_checkout`, `test_the_confined_fallback_child_still_loses_the_entry_inside_the_checkout`. Box 2: already true, `test_without_a_cwd_a_preset_under_the_current_directory_is_still_started`; link case pinned by `test_without_a_cwd_a_preset_starts_a_claude_that_links_into_the_current_directory`. Box 3: `CONTEXT.md` Fallback paragraph, `CHANGELOG.md` Unreleased.
