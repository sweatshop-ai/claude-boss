# 01: An empty `CLAUDE_CONFIG_DIR` means `~/.claude` in every hook

**What to build:** the track store (`boss_store.py`) owns the one rule for the
config directory: an empty `CLAUDE_CONFIG_DIR` is unset and means `~/.claude`,
read at call time, with an optional `cfg=` for tests. Today `boss_store` and
`registry` follow that rule, while `boss-guard`, `boss-reap`, `boss-compact` and
the ladder core use `os.environ.get(…, default)`, so an empty variable sends them
to the current directory: the guard then looks for boss files under `./pm` and
never fires (verified 2026-10-26 at 9d7ab1c). Every hook and the ladder core ask
the store; `registry.config_dir` calls it; the hooks drop their `CFG`, `PM`,
`MARKERS` and `STATE` constants. This is the prefactor the other tickets build on.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A test, written first and red on today's code, runs guard, pulse, compact
      and reap as subprocesses with `CLAUDE_CONFIG_DIR=""` and `HOME=<tmp>`, and
      each reads or writes under `<tmp>/.claude/pm`
- [ ] No hook or routine computes the config directory itself (a grep for
      `CLAUDE_CONFIG_DIR` in the Python finds only the store and tests)
- [ ] The ladder's `BOSS_LADDER_PM` and `BOSS_LADDER_STATE` overrides still win
- [ ] The touched test files pass locally; CI on t-compute is green
