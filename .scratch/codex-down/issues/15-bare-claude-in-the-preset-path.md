# 15: non-confined reviewer presets resolve a bare `claude` after changing into the checkout

**What to build:** in `skills/boss/reviewer_chain.py`, a spec without `env_unset` (the OPUS/FABLE presets) still runs `claude` by its bare name with the inherited PATH, with `cwd` set to the PR checkout, so `PATH=.:...`, an empty PATH entry or a checkout-local `.venv/bin` makes the PR's own `claude` run. `claude_launch` only resolves and filters for the confined fallback. Decide whether the presets take the same resolution (absolute path from a PATH without empty, relative and checkout-local entries) and test it with a planted `./claude`.

**Origin:** Codex review 3 of PR #87, head 4f449d9 (finding 4). Class c: the existing preset path, outside ticket 03.

**Blocked by:** none

**Status:** open
