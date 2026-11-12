# 21: edge cases of the presets' claude resolution (ticket 15)

**What to build:** three leftovers from the review of PR 98.
- The preset's child gets the filtered PATH, not only the lookup of `claude`: an MCP server or hook the preset loads (presets pass no `--strict-mcp-config`) that is found only through a relative PATH entry or a venv under the checkout no longer starts. Decide whether to keep the owner's PATH for the child and filter only the lookup of `claude`.
- With no `--cwd` (boss-run, boss-goal) a preset keeps absolute PATH entries under the current directory (an activated `.venv/bin`) and symlinks into it: no worse than before ticket 15, but no longer covered by the filter.
- `CONTEXT.md` and `CHANGELOG.md` do not say that `--fallback opus|fable` now resolves `claude` through the filtered PATH.

**Origin:** Fallback review 1 of PR 98 (Opus, Codex unavailable). Class c and d.

**Blocked by:** 15

**Status:** open
