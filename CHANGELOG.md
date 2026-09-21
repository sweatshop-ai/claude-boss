# Changelog

## 0.1.0 — 2026-09-20

First release as a plugin. The boss had lived in `~/.claude/skills/boss/` with
its hooks typed into `settings.json` by hand, versioned only by a nightly
mechanical commit.

- Six hooks declared once in `hooks/hooks.json`, resolved through
  `${CLAUDE_PLUGIN_ROOT}`.
- Every path is an environment variable with a default. Code resolves from the
  script's own location; state stays under `CLAUDE_CONFIG_DIR`.
- `install.sh` / `uninstall.sh` for the state directories and the two systemd
  user timers. Neither touches `pm/`.
- `scripts/unwire-legacy-hooks.py` for the migration, so the six hooks do not
  fire twice.
- 119 tests, at each hook's real seam.

Behaviour changes carried in this release:

- **The guard says it once, then counts.** It repeated a 330-character sentence
  on every flagged call: 2,589 firings over 14 days, about 215,000 tokens.
  Replayed over that log, the new version spends 4,982. It also stopped
  scolding the boss for running `boss-goal`, `boss-start` and `team-line`, and
  for anything behind a `cd X &&` or `VAR=…` prefix — 32% of all firings.
- **A stuck boss is visibly stuck.** An open blocker at `Stop` now pushes the
  boss to ask with `AskUserQuestion`, which raises a notification and rings the
  dashboard, rather than ending the turn in silence. It checks the session
  registry for a pending dialog first, so it never talks over a question.
- **Silent by default.** Speech is opt-in through `pm/.pulse/boss.voice`.
- **Per-session state is reaped** at `SessionEnd`, and swept for the crashes
  that leave no `SessionEnd`.
