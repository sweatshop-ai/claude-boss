# Changelog

## 0.3.0 — 2026-09-26

- **A worker keeps the name the boss gave it.** `boss-panes.py --set-name`
  wrote the peer file itself, and cc-agent-names' hook took a name that was
  not on its roster for Claude Code's own label and replaced it on the next
  prompt; a roster name was lost on resume. It now calls `agent-name set`
  (cc-agent-names 0.7.0) when that is on PATH, and writes the peer file
  directly only when it is not.

## 0.2.0 — 2026-09-26

The boss reads Claude Code's session registry through one module, shared with
cc-agent-names and agentview, and agrees with them on which sessions are alive.

- **A live session is one rule everywhere.** Its pid exists with the start
  time the peer file records (`procStart`), it is not a zombie, and a terminal
  session still has its terminal. boss-pulse and boss-panes used "`/proc/<pid>`
  exists", which a reused pid or an orphaned worker passes; boss-reap used
  "the peer file exists", so a leftover file kept a dead boss's marker forever.
- **boss-reap sweeps markers whose session has gone**, even when Claude Code
  left the peer file behind.
- **A worker whose cwd moved has its transcript found**, so its context and
  cost no longer show as 0.
- `skills/boss/registry.py` is vendored from cc-agent-names
  (`scripts/registry.py`); `scripts/vendor-registry` refreshes it and
  `test_registry_sync.py` fails when it drifts.

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
