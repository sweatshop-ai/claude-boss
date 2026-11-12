# 15: non-confined reviewer presets resolve a bare `claude` after changing into the checkout

**What to build:** in `skills/boss/reviewer_chain.py`, a spec without `env_unset` (the OPUS/FABLE presets) still runs `claude` by its bare name with the inherited PATH, with `cwd` set to the PR checkout, so `PATH=.:...`, an empty PATH entry or a checkout-local `.venv/bin` makes the PR's own `claude` run. `claude_launch` only resolves and filters for the confined fallback. Decide whether the presets take the same resolution (absolute path from a PATH without empty, relative and checkout-local entries) and test it with a planted `./claude`.

**Origin:** Codex review 3 of PR #87, head 4f449d9 (finding 4). Class c: the existing preset path, outside ticket 03.

**Blocked by:** none

**Status:** done (PR 98; Opus fallback reviews, Codex re-review owed; edge cases ticketed as 21)

- [x] Decision: every `claude` launch goes through `claude_launch`'s resolution (absolute path, filtered PATH, refused when its realpath is inside the checkout); the presets keep the rest of our environment
- [x] A planted `./claude` is not run with `.` in PATH, an empty PATH entry, or a relative entry; tested for OPUS
- [x] A planted checkout `.venv/bin/claude` first in PATH is not run; tested for FABLE
- [x] A symlink into the checkout in a safe PATH directory is refused (attempt "absent"); a normal PATH still starts the stub for both presets
- [x] The preset's `claude` is started by absolute path with the rest of the environment kept
