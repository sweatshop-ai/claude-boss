# Changelog

## 0.16.0 — 2026-10-26

- **The pulse decides as data, then words it** (architecture review,
  candidate 4). `boss-pulse.py`'s `main()` gathered the facts, decided what to
  tell the boss, built the numbered text and marked the fired rungs, all in
  one 140-line function, and its tests could only look for substrings in the
  text. `skills/boss/pulse.py` now holds `decide(facts)`, which returns the
  ordered actions, the overdue rungs and the rung marks (or nothing), and
  `render(facts, decision)`, which words them. The rung marks are part of the
  decision; the text no longer sets them as it is built. `boss-pulse.py` keeps
  the gathering, the gate and the state file. The text is byte-identical: the
  full output of 1152 situations matched `main` before the change.

## 0.15.0 — 2026-10-25

- **One owner for the objective file** (architecture review, candidate 3).
  `pm/<track>.goal.md` had one format and three readers: `tracker.goal_status`
  took the first `_Status:` line, `boss-goal check`/`list` took line 2 with
  `sed`, and the pulse parsed the sections with its own regex. `boss-goal
  status` overwrote line 2 whatever it held, so a note above the status line
  was lost and the status left untouched. `skills/boss/objective.py` now reads
  and writes the format, and `boss-goal` goes through its command line. All 44
  objectives on the author's machine had the status on line 2, so nothing read
  differently before; the gap was in hand-edited files. The only format the
  script still writes itself is the `init` template.
- `boss-goal status` rewrites the first status line (or inserts one under the
  heading, and refuses a note with a newline in it, which would have written a
  status that reads as nothing). `set` keeps the heading and that status line.
  `next` replaces only its own section: it used to cut every section after
  `## Next` too. Every write goes through a temp file and keeps the file's mode.
- The criteria are the boxes under `## Done when`, for `check` and `verify`
  as for the pulse. `check` and `verify` took every `- [ ]` line in the file.
  One live objective (`tiroir-groups`, paused) keeps its boxes under a bold
  `**Done when:**` instead of a heading: the pulse never saw them, and now
  `check` says so.
- `boss-goal` finds its neighbours (`objective.py`, `reviewer_chain.py`, the
  prompt templates, `frontier.py`) through its real path. Run through the
  `install.sh BIN=1` symlink in `~/.local/bin`, `review` and `premortem` looked
  for them under `~/.local` (found by the Codex review).
- `boss-goal check` counts the items of `## Next` only (a numbered or bulleted
  line at the margin; a wrapped line belongs to its item). It counted numbered
  lines up to the end of the file, so a numbered list in a later section was
  queued too and a bulleted Next was empty. Same counts as before on all 44
  live objectives.
- `tracker.goal_status`/`goal_open` moved to `objective.status`/`is_open`; the
  ladder and the pulse import them from there.
- Not in this release: the GitHub frontier cache (`boss-goal check` and the
  pulse share its file name through a comment). No objective uses a `gh:`
  ticket source today.
- Tests: `test_objective.py` (the rules and the command line); `test_bin.py`
  gained the line-3 status cases for `status`, `list`, `check` and `set`.

## 0.14.0 — 2026-10-25

- **One fleet view** (architecture review, candidate 2). Which pane runs which
  session was worked out twice: `boss-panes.py` walked `/proc` ancestry,
  `boss-pulse.py` sliced the registry's `tmux` field, and the tmux format string
  and the `@boss_pane` stamp were spelled in three files. `skills/boss/fleet.py`
  now owns both rules, behind a tmux adapter and an in-memory one for tests.
  The rule is the registry's `tmux` field (on the live fleet it matched the
  `/proc` walk on 15 of 15 panes, without the walk).
- **`shared-pane`**: when two live sessions name one pane (a claude started
  inside another inherits its pane), the oldest wins, the row is flagged, and
  `list` prints a line under it naming the others, and which of them a
  keystroke reaches in each case.
- `boss-lifecycle.sh` asks `boss-panes.py get <pane> <field>...` for fields by
  name instead of cutting TSV columns by position, and `list` and the stamp go
  through `boss-panes.py list` / `stamp`. Output of `list` is unchanged (27 of
  27 rows identical on the live fleet).
- The cross-boss guard fails closed: when the owner of a pane cannot be read
  (tmux not answering, boss-panes failing), `retire`/`restart`/`move`/`claim`
  refuse instead of treating the pane as unowned. A stamp tmux refuses fails
  the claim instead of passing silently.
- When tmux does not answer, `list` says so and exits 1 instead of printing an
  empty fleet (found by the Codex review).
- Tests: `test_fleet.py` (rules and the tmux adapter); `test_boss_lifecycle.py`
  gained the bash side (`get`, `list`, `claim`).

## 0.13.0 — 2026-10-25

- **Jev is gone** (the owner, 2026-10-25). The `UserPromptSubmit` hook
  `boss-jev.py` was meant to keep the boss asleep for worker events that need
  nothing. It ran in `advisory` mode with egress off, so on every boss prompt it
  spawned a process, logged `pass: egress off` and decided nothing. Removed: the
  hook, `tools/boss-event-jev.py`, the redact list example, `references/boss-jev.md`
  and the handoff footer (`boss-jev.py footer --task N`), whose only reader was
  Jev's restart gate. A dispatch still names `Task #<N>` and still asks for a
  handoff file.
- Kept: `boss-lifecycle.sh retire|restart --require-idle` and `boss-panes.py
  --state`. Their tests moved from `test_boss_jev.py` to `test_boss_lifecycle.py`.
- **Your old Jev files stay where they are.** Nothing deletes them. To clean up:
  `rm -f ~/.claude/pm/.pulse/jev.* ~/.claude/pm/.pulse/jev-*.json ~/.claude/pm/.pulse/jev-*.lock ~/.claude/pm/*.jev-archive.md`
  (and `boss-redact.json` / `typesafe.env` if nothing else uses them).
  `unwire-legacy-hooks.py` still removes a hand-written `boss-jev.py` hook.

## 0.12.0 — 2026-10-25

- **One reviewer chain** (architecture review, the owner, 2026-10-25). `boss-goal
  review` and `premortem` carried a second copy of the chain in bash: it counted
  prose mentions of `VERDICT:` as an answer, ignored Codex's exit status and kept no
  attempt record. Both now call `reviewer_chain.py` like `boss-run`, and when nobody
  answers they print each reviewer's reason (`codex: timeout, opus: absent`). The
  chain grew what they needed: a second acceptance rule (`--lines RISK --min-lines 8
  --max-lines 25`: enough labelled lines, returned stripped), `--cwd` (Codex `-C`,
  the fallback run in that directory), fallback presets (`--fallback opus|fable`,
  the only place the model ids are written; `boss-run` lost its copy), and a
  fallback timeout that defaults to twice Codex's, as every caller set it.
- **Premortem falls back to Fable** (`claude-fable-5-1`), the strongest model, for
  the widest risk sweep; `review` and `boss-run` stay on Opus. Codex is still asked
  first everywhere.
- Tests: `review` and `premortem` had none; they now run hermetically in
  `test_bin.py` through the sandbox's `codex`/`claude` stubs.

## 0.11.6 — 2026-10-22

- **P16: on a small shared runner pool, push only gate-ready heads** (owner,
  2026-10-22). Three self-hosted runners and a three-job matrix meant one suite at a
  time while four waited, one branch having started six runs in 14 minutes. Every
  dispatch that pushes now carries three rules: push once, when the head is the one
  to gate; cancel only your own superseded queued runs before a re-run; never re-run
  a queued job. The boss checks `gh run list --status queued` before adding parallel
  PR work.

## 0.11.5 — 2026-10-22

- **The reviewer fallback is Opus, not Haiku** (Thierry, 2026-10-22). When Codex is
  absent, silent or at its usage limit, `boss-run`, `reviewer_chain.py` and
  `boss-goal review` / `premortem` ask `claude-opus-5-5`. The log's `reviewer` field
  reads `opus` instead of `haiku`. Opus answers slower, so in `boss-run` and
  `boss-goal` the fallback gets twice Codex's time (`reviewer_chain.py`'s own
  `--fallback-timeout` default is still 120 s): `boss-run` uses `BOSS_RUN_REVIEW_FALLBACK_TIMEOUT` (default 2 x
  `BOSS_RUN_REVIEW_TIMEOUT`), `boss-goal` 240 s (600 s when it reads code). Also fixed: `boss-goal premortem
  <track> <repo-dir>` passed `--allowedTools` after `-p`, which swallowed the prompt, so
  the fallback never answered for that form.

## 0.11.4 — 2026-10-21

- **A worker that left background work running can be retired again.** Its `/exit`
  opens "Background work is running"; `retire --require-idle` read that as a turn
  started in the gap, closed it with Escape and gave up, and the plain retire looped
  on it, so a restart waited for someone to press Enter in the pane (Sinead
  2026-09-22, a sleep watcher; Tobias 2026-10-21, an orphaned curl), which the
  classifier forbids the boss. Now, when the worker is still idle on the same input
  as before `/exit` and the dialog shows `❯ 1. Exit and stop tasks`, the retire
  confirms it and prints what it stopped. "Same input" leaves out the three user
  records `/exit` writes itself (`transcript.pin(past_exit=True)`, a 4th field of
  `boss-panes.py --state`). A confirmed exit still shutting down is left alone. A changed state or any other dialog
  keeps the old refusal. Claude Code has no setting or flag to skip this dialog.
- **The dispatch asks the worker to stop its background tasks before the handoff.**

## 0.11.3 — 2026-10-21

- **`ci_state` returns `head_sha`**, the commit the run is for (null when unknown),
  so agentview shows "waiting on CI" only when the run is for the session's own
  HEAD, not for a commit someone else pushed to the same branch (Tarek).

## 0.11.2 — 2026-10-21

- **`ci_state` hardened** (Codex review 3 of PR 21): a cache file of another shape
  reads as `unknown` instead of raising on the caller's poll path; a re-run's wait
  counts from its own attempt (`run_started_at`), not the first attempt's
  `created_at`; a `waiting` run reports no wait, since no timestamp says when it
  started waiting.

## 0.11.1 — 2026-10-21

- **`ci_state.py`**: `ci_state(repo, branch)` says whether a branch's latest Actions
  run is queued, running or done, how long it has waited or run, and an ETA (median
  of the workflow's last successful runs, minus elapsed; a queued run's ETA leaves the
  queue out). The caller never waits on the network: it reads a cache and starts a
  detached refresh; every failure reads as `unknown`. Written for agentview, which
  vendors it (Tarek, 2026-10-21), and for the boss pulse, which does not use it yet.
  On sweatshop-ai/render-doc a run takes 45-95 min and waited up to 2 h for a runner.

## 0.11.0 — 2026-10-21

The boss hands out the whole frontier, not the top item.

- **`## Tickets` in the objective** names a ticket graph: a folder of ticket
  files, or `gh:owner/repo#N`. With it, the pulse reads the frontier and lists
  every ready ticket, asks for one to each idle worker in the same turn, and
  asks for a spawn when ready tickets outnumber idle workers and the team is
  under `BOSS_SPAN`. A broken graph (a cycle, a missing Blocked by) is named and
  nothing is dispatched from it. `boss-goal check` reads the graph too.
  Before this the graph lived only in the hand-to-boss brief, and the pulse said
  "dispatch the top NEXT item": one worker per turn.
- **GitHub ticket graphs.** `frontier.py gh:owner/repo#N` reads the sub-issues
  of issue N and GitHub's native issue dependencies; a closed issue is done, a
  `worker:<name>` label is the claim (every worker writes as one account, so the
  assignee cannot say who), an open blocker outside the sub-issues is external.
  The claim re-reads the live graph and refuses a ticket that is blocked,
  claimed, done or not a sub-issue, and creates the label before adding it.
  Paginated sub-issues and blockers are joined across pages, and an issue is
  known by repo and number. The pulse's Stop hook has 5 s, so it keeps the last
  `frontier.py --json`, keyed by track and source, and reads GitHub again when
  it is older than 30 s, for 3 s at most (a bigger graph finishes in the
  background); `boss-goal check` saves the same cache. A failed read keeps the
  last good frontier.
- **Without a graph, Next works the same way**: one item per idle worker.
- **Span of control 5 → 12** (`policy.BOSS_SPAN`). The five had no measurement
  behind it. The limit the owner hits is the weekly usage cap (four times since
  10-10), not the five-hour one; the owner prefers finishing sooner.
- **Bursts: background subagents by default, 3 to start, at most 5**
  (`policy.BURST_START`, `BURST_MAX`). Agent-teams teammates only when the parts
  must talk. The old "at most three" misquoted Anthropic's guide, which says
  "Start with 3-5 teammates" and that three "often" beat five.
- **Codex: at most three rounds on one PR**, then the open findings become a
  ticket and the PR merges, unless one is about security or lost data. PR 11
  ran twelve.
- **Glossary:** *Ticket graph* and *Frontier*; *Burst* now covers subagents.

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
  overridden one did not. A second `--settings` replaces the first rather
  than merging (checked: two payloads, only the last one's env survived), so
  `boss-start` now refuses an owner's `--settings` with exit 2 and says why.
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
