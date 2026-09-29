# Changelog

## 0.4.0 — 2026-09-29

- **`/hand-to-boss` starts a boss on an approved plan.** It is the last link of
  grill → plan → to-tickets → hand-to-boss: it checks the plan and its ticket
  graph, writes a brief from a fixed template (sources by path, the frontier
  and who holds each external blocker, staffing, guardrails quoted from the
  repo's and the owner's CLAUDE.md, time windows, report language), commits it
  beside the tickets, launches `boss-start` in a new tmux session and reports
  the boss's name from `ListAgents`. User-invoked only: it starts a team that
  spends for hours.
- **The brief travels as a path, not as text.** The first manual run passed
  the whole brief on the command line, where `ps` and shell history keep it.
- **A boss stuck on the trust prompt is caught.** The folder's trust is
  checked in `~/.claude.json` before launch, and the wait for the boss's name
  gives up after 90 seconds and reports what the pane shows.
- **A ticket has an owner.** The boss protocol assigns work but kept no owner
  on a ticket file, so two workers picking from one frontier could take the
  same ticket. The boss now claims it at dispatch with `frontier.py claim`,
  which refuses a ticket already claimed, done or blocked, and commits that
  one file by path.
- `skills/hand-to-boss/frontier.py` reads a to-tickets folder and prints the
  frontier. It exits 2 on a graph a boss cannot finish: a missing field, an
  unknown ticket, a self-block, a cycle, a file that is not UTF-8. 20 tests.
- **The boss no longer asks the owner what could go wrong.** It asked one
  blank-page question, *"What would make you say this went wrong?"*, and an
  owner who says yes to most suggestions gave thin answers. `boss-goal
  premortem <track> [repo-dir]` now has a second model (Codex, Haiku as
  fallback) list every concrete way the track could fail, reading the code in
  `repo-dir` when given. The owner strikes out the numbers that are not a
  problem; every risk left in gets a criterion, a constraint or a pause in
  the objective, and the full mapping goes to the tracker. An answer with
  fewer than 8 risks falls through to the next model; more than 25 is cut.
- `review` and `premortem` share one second-model path in `boss-goal`.

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
