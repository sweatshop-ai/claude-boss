# Changelog

## 0.10.0 — 2026-10-05

A boss no longer leads agent-teams teammates by accident; a worker may lead
them on purpose.

- **`boss-start` turns agent teams off for the boss** with
  `--settings '{"env":{"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS":"0"}}'`. With them
  on, any `Agent` call carrying a `name` starts a teammate inside the boss's
  process, without asking: no pane, no stamp, invisible to `list --mine`, the
  pulse and the workers watch, and gone when the boss exits. A shell export
  cannot do this (settings.json env wins); a `--settings` payload can.
  Checked: a control session wrote `~/.claude/teams/session-*` at startup, the
  overridden one did not.
- **The guard watches `Agent`.** A named call (not a fork, not `isolation`) is
  said every time, outside the power-of-two throttle, because nothing else the
  boss runs will ever mention it. An unnamed call is counted like any other.
  Still warn-only. Seven tests in `test_boss_guard.py`.
- **Bursts.** Phase B's dispatch lets a worker run a ticket as a burst of at
  most three agent-teams teammates, when its parts need no talk and share no
  files. The worker decides; the burst spends its 150k. Criteria in
  `references/models.md`.
- **Glossary:** *Agent-teams teammate* and *Burst*; bare "teammate" and "team"
  are to be avoided — the first means four things here, the second is `/team`.

## 0.9.1 — 2026-10-03

The `boss` and `team` skill descriptions are shorter.

- **`boss` 241 → 147 characters, `team` 278 → 127.** Claude Code lists every
  skill's description in every session, so each character is paid on every turn.
  Each description now leads with its triggers, one per case. `boss`: "be the
  boss" / "you're /boss", "dispatch this", worker status or task-board report,
  wrap-up. `team`: "tell X…", "ask @y…", "tell everyone…" and a peer's
  cross-session message. "manage the team" is dropped as another way of saying
  "be the boss".
- Read against past model-started runs: 8 of 11 `boss` starts were a role
  assignment ("you're /boss now", "become /boss", "taking over as boss"), so
  that phrase is now named; `team` starts were "tell X", "pass it to X" and
  "ask the active workers", all still named.

## 0.9.0 — 2026-10-02

One module knows the formats of a track's files, and the ladder no longer
counts a closed track as open.

- **`skills/boss/tracker.py`** holds the ladder marker (`scan_marker`,
  `validate`, `render_marker`, `rewrite`), the `## Open blockers` section
  (`blockers_range`, `open_blockers`, `insert_in_section`), the shared lock
  path and the objective's status (`goal_status`, `goal_open`). boss-jev, the
  pulse and the ladder read it; each had its own copy, and the tests a third
  regex for the marker.
- **Fix: the ladder read `_Status: OPEN_` anywhere in the objective.** On
  2026-10-02 six of nineteen objectives carried their header twice, and three
  (ai-consultancy, purpleshares, tray-indicator-state) said MET or PAUSED on
  line 2 and OPEN on line 4. The pulse read them as closed, the ladder as open,
  so a marker there would have kept escalating. Both now read the first status
  line. No rung went out from it: none of the three had a marker.
- **Fix: `boss-goal set` drops a header piped in on stdin.** That is how the
  duplicates came about: a body edited from `show` kept its header under the
  file's own, and `status` only ever rewrote line 2.
- **boss-jev's ladder acknowledgement parses the marker** instead of searching
  for `ask="(boss names it)"`. A marker the ladder cannot read now counts as not
  acted on, so the report keeps coming until the line is repaired.
- The Open blockers readers in the pulse and the ladder agreed on every real
  tracker; that part removes duplication and changes no output.
- The marker tests moved from the ladder's `--selftest` to `test_tracker.py`,
  which also runs `boss-tracker` and `boss-goal` and reads their output back.

## 0.8.0 — 2026-10-01

One module reads a transcript.

- **`skills/boss/transcript.py`** holds the tail read (last 4 MB), the token
  price weights and the pin. `tail`, `usage` and `pin` are its interface.
  boss-panes and boss-jev each had their own copy of all three.
- **boss-panes reads the last 4 MB**, not the whole file. On the six largest
  transcripts on the machine (20-33 MB) the context and cost came out identical
  and the read was 2-5x faster.
- **The `turns` column now counts the turns in that tail**, not the whole
  session. Nothing reads it; `boss-lifecycle.sh list` does not show it.
- `test_transcript.py` tests the module on JSONL fixtures. The test that only
  checked the two pin copies agreed is gone with the second copy.

## 0.7.0 — 2026-10-01

The steering numbers live in one module.

- **`skills/boss/policy.py`** holds the context bands (worker 150k/250k, boss
  400k/500k), the cost lines (60k/90k per turn) and the escalation rungs
  (5, 15, 30, 60, 120, then every 120, stop at 24 h). `flag_for`, `heavy`,
  `rung_for` and `next_rung` are its interface.
- **`boss-panes.py` prints the flags** as an eighth column, by role: a session
  with a boss marker gets the boss band, every other session the worker band.
  `boss-lifecycle.sh list` shows them and no longer codes any threshold. A
  second boss in the list now gets the boss band too (it got the worker one).
- **The pulse and the ladder share one rung schedule.** The pulse had its own
  (5…90…240) and could remind the boss of a rung the ladder never posts.
- **boss-jev's `heavy` gate uses the worker band** (150k), not the boss's 400k.
- **`test_policy.py` checks every prose quote** of these numbers in SKILL.md,
  team/SKILL.md, models.md, escalation.md, boss-ladder.md and boss-start.
  Change a number and it names each line to update.
- **The #76 Replay tests run again**: they looked for the sample next to the
  repo, a path left from the `~/.claude/skills` layout, and skipped silently.
- `escalation.md` and `boss-alert`'s usage now state the real rungs.

## 0.6.0 — 2026-10-01

One task, one session. A model gets worse as its context fills, well before
the window ends (Pocock's "smart zone", ~125–150k), so workers no longer carry
one task's dead ends into the next.

- **Every finished task is a restart.** Every dispatch asks for the handoff and
  the push; the boss restarts the worker before its next dispatch. boss-jev
  drops its 400k / 90k-per-turn gate and proposes the restart for any finished
  task that passes the other gates.
- **A task bigger than 150k gets split.** `list` flags workers `CTX-SPLIT` at
  150k and `CTX-OVER` at 250k (was `CTX-EVAL` 400k, `CTX-RESTART` 500k): the
  worker stops at its next boundary, hands off, and a fresh session continues.
- **The boss keeps its 400k/500k band** and its 450k autocompact; its state is
  the tracker.

## 0.5.0 — 2026-09-29

One rule for the boss files, and the tools write where the hooks read.

- **`boss-marker register [track]`** replaces the `touch` and `echo` SKILL.md
  told the model to run. It is on every session's PATH.
- **`boss_store.py`** is the one reader of the marker: guard, pulse, compact
  and jev each had their own. Pulse and compact turned an unchecked first line
  into a file name under `pm/`; a marker reading `../evil` made the pulse act
  on a goal file outside `pm/`.
- **`boss-tracker`, `boss-goal` and `boss-run` honour `CLAUDE_CONFIG_DIR`**, as
  the hooks always did. They wrote to `$HOME/.claude/pm`, so with another
  config dir the boss's tracker was one no hook read.
- **Track names are checked** before they become file names
  (`boss-tracker init ../x` wrote outside `pm/`).
- **`boss-tracker append` takes the tracker lock** boss-jev and the ladder
  routine rewrite under.
- **`boss-goal check` no longer says the pulse is NOT ARMED** under a plugin
  install; it reads `enabledPlugins`.

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
