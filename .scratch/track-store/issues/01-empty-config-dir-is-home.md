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

**Claimed by:** Farid 2026-10-27 12:16

**Status:** done

- [x] A test, written first and red on today's code, runs guard, pulse, compact
      and reap as subprocesses with `CLAUDE_CONFIG_DIR=""` and `HOME=<tmp>`, and
      each reads or writes under `<tmp>/.claude/pm`
      Evidence: `skills/boss/test_config_dir.py` (four hooks + ladder). On the old code
      (`git archive feat/track-store`): FAILED (failures=3, errors=1): guard
      "'is implementation work' not found in ''", reap "True is not false", compact
      JSONDecodeError (no output), ladder `PosixPath('pm') != .../home/.claude/pm`.
      On 5bcee99: `Ran 7 tests ... OK`. Pulse already passed (it used
      `registry.config_dir`); its case stays as the guard.
- [x] No hook or routine computes the config directory itself (a grep for
      `CLAUDE_CONFIG_DIR` in the Python finds only the store and tests)
      Evidence: `grep -rn CLAUDE_CONFIG_DIR --include=*.py skills routines` outside tests
      finds `boss_store.py` (the store), `registry.py:45` and `hermetic.py:80,218`. Two
      exceptions, by the boss's decision: `registry.py` is a vendored byte copy of
      cc-agent-names (enforced by test_registry_sync, not edited) and applies the same
      rule; `hermetic.py` is test harness. `RegistryAgrees` in test_config_dir.py fails
      if `registry.config_dir()` and `boss_store.config_dir()` differ with the variable
      unset, "" or a path.
- [x] The ladder's `BOSS_LADDER_PM` and `BOSS_LADDER_STATE` overrides still win
      Evidence: `test_ladder_overrides_still_win` OK; `boss_ladder_core.py --selftest`:
      `selftest: 84/84 checks passed`.
- [x] The touched test files pass locally; CI on t-compute is green
      Evidence: touched files OK locally; full `pytest -q skills`: `400 passed, 1 skipped,
      300 subtests passed`. `gh api repos/sweatshop-ai/claude-boss/commits/c38de19.../check-runs`:
      `total_count 1`, `pytest: completed success` (draft PR #32 makes tests.yml run on
      feat/track-store; ubuntu-latest, not t-compute, as the workflow is written).
