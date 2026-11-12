# Changelog

## Unreleased

- **The merge gate: `boss_merge.py` (ticket 04).** `skills/boss/boss_merge.py --repo OWNER/REPO --pr N [--dry-run]` reads the PR once (`gh pr view`, identity checked as `boss_review.py` does), walks its `round<NN>.json` files from the highest down and runs `gh pr merge --repo R N --merge --match-head-commit <head it read>` only when the first round that decides allows it. A `codex` GO on the live head and base allows on any branch; a `provisional` (08) or `waived` (09c) GO allows only when the base is listed in `.boss/deploy.json` on the base branch (`gh api repos/R/contents/.boss/deploy.json?ref=<base>`, exact names, never read from the PR's head). It fails closed: a round file it cannot read as one of this PR's, a missing or invalid deploy file, and a provisional or waived GO that any later round (of any status, any head) supersedes (`superseded-go`, ticket 22) all refuse. Exit 0 merged (or allowed under `--dry-run`), 2 usage or a PR that is not open, 3 refused, 4 a weak GO on a deploying branch, 5 the merge or the check after it failed (`gh pr merge` returning 0 with the PR not `MERGED`, or on another base, or unreadable, also calls `boss-alert 0`), 7 a `gh` read failed. Every decision is one `O_APPEND` line in `pm/reviews/merges.jsonl` (mode 0600). This repo gets `.boss/deploy.json` listing `main`. The hand-typed merge is still outside it until ticket 11 (`boss-run` hard rule, the skill text).
- **Merge on tests alone, only through `--waive` and the owner's consent (ticket 09c).** `boss_review.py --waive --repo R --pr N --checkout DIR --author NAME --track T --test-cmd CMD` runs `CMD` (`/bin/sh -c`, in the checkout, within `policy.WAIVE_TEST_TIMEOUT`, 900 s) and, if the owner chose `tests-alone` for the open `Codex down` blocker, it passes on a clean checkout that stands on the PR head, and nothing moved while it ran (re-read under the PR's lock), records a `kind: waived` round (reviewer `tests`, verdict GO) and posts `Merge on tests alone (Codex unavailable): CMD passed on SHA`. Exit 5 is a refusal that records nothing; 6 is a head, base or checkout that moved or turned dirty (a `head-moved` round, nothing posted). `codex_blocker.py --choose T tests-alone --test-cmd CMD` joins `wait` and `accept-fallback`, and the owner is asked again, in the boss's own turn, with a `CONSENT:` question that names the track and the command. The guard gains a PostToolUse hook on `AskUserQuestion`: a yes to exactly one such question writes `pm/consent/<session_id>.json` (mode 0600, ten minutes), any later Ask deletes it, and both commands refuse without a valid one. The token is a guardrail against a session that runs the command unasked; forging it as the same user is a residual the owner accepted (coverage R26). Real `AskUserQuestion` payloads (yes, no, free text) and a subagent's hook payload are fixtures under `skills/boss/fixtures/askuser`: a subagent reports its parent's `session_id`.
- **Owner's choice record, edge cases (ticket 26).** `codex_blocker.usable_tracker` takes a `verb`: `--choice` on a tracker that is not a regular file of yours says "no blocker can be read", `--choose` says "no blocker can be answered", and a raise still says "no blocker can be raised", so the first stderr line no longer contradicts the command. Tests: every `--choose`/`--choice` command run in `class Choice` asserts the `boss-alert` stub's call log did not grow (one helper, not one assert per test); `same_blockers` compares the Codex down entry with `tracker.set_ask(before, "Codex down; owner chose <v>")`, so only `ask=` is shown to change; a symlinked tracker and a tracker of another owner (`os.getuid` patched, since a test cannot chown), each with a blocker open so a write would show, are malformed for both commands and nothing is written.
- **Prune of the provisional list, edge cases (ticket 25).** `_codex_rounds` catches the `RecursionError` that a round file nested too deep gives the JSON parser, so that PR keeps its entries and the prune goes on with the next. An empty round file with a later round above it is a dead claim (rounds are claimed under the PR's lock) and is skipped, so a round left empty by a failed write no longer keeps its PR's entry for good; the newest round empty still keeps it. New tests for both, for a CRLF tracker, for two identical lines of one entry and for rule 2's boundary; two tests that proved less than they said now see the `gh` timeout and the tracker-lock wait fire, and the lock test closes its descriptor. The over-4300-digit round name is declined: a file name is at most 255 bytes.
- **Hand-clear hold edge cases (ticket 24).** `codex_blocker.sync` and `choose` take a `now` as having a UTC offset only when `now.utcoffset()` is not None; a `tzinfo` whose `utcoffset()` returns None or raises `TypeError`/`ValueError` is the same `ValueError` as a naive `now`, before anything is written, instead of a `TypeError` from the future-clear comparison aborting the sync. The two-outages test also asserts both raises reached `boss-alert 0`.
- **Provisional list edge cases (ticket 23).** `review()` resolves `--track` once, so an unusable track says "no blocker can be raised" once, not again from the health sync (which is skipped for it). A line under `## Provisional GO` is an entry only in the exact form the writer produces: `owner/repo`, a 7 to 40 character head, a round of at least two digits (`%02d` writes `100` from round 100), an ISO 8601 `at=`; a hand-edited line off that form is left alone, never replaced. A test pins that an unreadable PR after the list write ends `post-failed`, exit 7, with the entry kept and nothing posted.
- **Reviewer presets' `claude` resolution, edge cases (ticket 21).** `--fallback opus|fable` looks `claude` up on a PATH without empty, relative and checkout-local entries (ticket 15), and starts it by absolute path. Only that lookup is filtered: the preset's child gets our PATH minus its empty and relative entries, so an MCP server or hook found through an activated checkout `.venv/bin` still starts. The confined fallback's child keeps the fully filtered PATH. With no `--cwd` (boss-run, boss-goal) a preset keeps absolute entries under the current directory and links into it: there is no checkout to keep out; a test pins it.
- **`claude_launch` edge cases (ticket 17).** With no `cwd` and a deleted current directory the confined fallback is "absent" instead of raising `FileNotFoundError`; a `cwd` of `/` now keeps every PATH entry out (the prefix was `//`); the docstring says a refused link is final, "absent", with no later PATH entry tried. Tests cover a relative link straight into the checkout.
- **A hand-cleared Codex down blocker stays cleared until a later failure is logged (ticket 09a).** `codex_health.health()` also returns `last_ts`, the `ts` of the newest failure; `codex_blocker.sync` raises over no open line only when `last_ts` is missing or at or after the minute start of the newest `cleared=` in the section. Type `cleared=<ISO-8601 time with UTC offset>` to close a blocker; deleting the line raises it again. A `cleared=` more than 60 s after `now` is ignored as invalid and said on stderr. The order is by `ts`, an approximation: a writer that logged a failure with a `ts` from before the clear can be read as old.
- **A dead Codex becomes an open blocker (ticket 05c).** `boss_review.py` takes `--track T` (and `review(..., track=)`): once its attempts are logged it calls `skills/boss/codex_blocker.py`, which, inside one tracker lock, adds a `Codex down` line with a ladder marker after 3 failed Codex attempts in a row (`boss-alert 0`; the ladder escalates it from rung 5 without a boss turn) and sets `cleared=` on it after 2 answered ones (`boss-alert clear`, once). A track name that is not plain is exit 2; a tracker that is not a regular file of yours, or a sync that fails, is said on stderr and the review's exit code stands. Without `--track` nothing is written to a tracker.
- **Codex health is derived from the attempts log (ticket 05b).** `skills/boss/codex_health.py` reads `pm/reviews/attempts.jsonl` in one scan and says `down` after `policy.CODEX_DOWN_AFTER` (3) failed Codex attempts in a row, `up` again after `policy.CODEX_UP_AFTER` (2) answered ones. It stores no counter and writes nothing; the blocker that uses it is ticket 05c.
- **A Done when line names its local tickets as `<feature>/<NN>`, or a range `<feature>/<NN> to <MM>`.** SKILL.md,
  `references/objective.md` and the hand-to-boss brief template say so. FleetView (agentview PR 33) shows each Done when
  line as a row on the track's card, worked on, waiting, planned or done, and finds the line's tickets by that name
  only; a goal that says "ticket 26" or "every ticket in the folder" shows every open line as planned.

## 0.23.0 — 2026-11-11

- **`/boss wrap-up` saves the state, then closes every pane the boss owns (ticket 01).** Phase E checks git itself
  for each worktree, writes one line under `## Open blockers` naming every open item (unanswered owner question,
  open PRs, unwatched CI runs, the brief to resume from), sets the objective to `paused` or `met`, and only then closes
  the panes, the concierge included even with a question open. A worker waiting on CI is closed anyway when git shows
  nothing at risk; one with uncommitted code or a commit on no remote is named and left open. The boss's own pane stays
  for the owner to close.
- **A concierge keeps its role through a reboot (ticket 43).** `claim <pane> --concierge` puts
  `@worker_role` back on a pane, and so the `[concierge]` label and the guard that protects a held question, but only
  when a process in the pane's tree started with `--append-system-prompt-file .../references/concierge-brief.md`, the
  argument `launch_claude` gives a concierge and no worker. Any other pane is refused and left unmarked, so the flag alone never gives a
  worker `AskUserQuestion`. `--concierge` on `retire`, `restart`, `move` is still refused.
- **`test_bin` removes the directories its `Tools` tests make (ticket 44).** A run left 40 `boss-bin-*` directories in `$TMPDIR`; it now leaves none.

## 0.22.0 — 2026-11-05

- **The efficiency scan takes a worker's own session ref only from a `ListAgents` result (ticket 38).** A worker that
  read a file holding a "This session is NAME [ref]" line no longer records that ref as its own, so a send to
  its real ref keeps its attribution.
- **A question through the concierge names its boss, and holds one question (ticket 39).** The boss opens
  each `ASK` with its own name and track, which the concierge cannot know; a question without them is still
  asked, with `From <name>, the boss that sent this question.` in front and the rest unchanged. One `ASK`, one question: if
  several arrive, the concierge asks them one at a time and answers each, numbered `q7.1`, `q7.2`.

- **`boss-unask` survives a torn record, and its example cannot end early (ticket 37).** `read` decodes per
  line, so an interrupted multi-byte append skips that line instead of failing `list` and the weekly
  routine; the `record` example in SKILL.md ends on `END_OF_OWNER_REPORT_8c41f7`, not `EOF`, so a line
  of the owner's words reading `EOF` no longer runs the rest as shell.
- **The owner can say a kind of question should not reach them (ticket 06).** In plain words, any
  language, after an answer or later, also through the concierge. `bin/boss-unask record <track> <kind>`
  (stdin: the question, a `--- owner ---` line, their words) writes one line to the private
  `pm/unwanted-questions.jsonl` (mode 600, never the repo); `list <track>` reads it back at session
  start, and the boss stops bringing that kind in that track. The weekly efficiency routine counts
  reports by kind and proposes a rule when a kind recurs; it prints kinds and counts, never the words,
  and filters nothing. Replaces the Jev filter the ticket first planned: the owner's 20 labels held
  two clear cases, too few to measure a threshold.

- **`restart --require-idle` re-checks the owner before `/exit`, refuses a dialog it cannot compare, and ends its wait on time (ticket 32, part 1).**
  Codex found on the merged PR 50 that pane ownership was read once, before the `--wait-idle` loop, so a
  boss that claimed or `--force`d the pane during the wait was sent `/exit` by the stale command; the owner
  is now read again just before `/exit`. With no transcript both pins read `-`, "no change" held between two
  blanks and a turn in the gap went unseen: that case now closes the exit dialog with one Escape and leaves
  the worker running (refuse on doubt). The last sleep of a wait is the time left, not the whole interval.
  The boss and team skills now define a turn as one model message, matching `ctx_over_measure.py`, and the
  self-contained dispatch says `code-review` runs once per PR.

- **Efficiency routine: the five open lines of the Codex pass on PR 49 (ticket 32, part 3).**
  `bin/boss-link` now also names a unit template with no installed unit (a timer added since
  `install.sh` last ran), but only when another boss unit is installed. The three service
  templates carry `Environment=CLAUDE_CONFIG_DIR=@CFG@` (the ladder had the same gap as the
  efficiency measure and the watchdog), and the comparison reads that line back, so a session
  under another config dir stays quiet. An alert Slack did not take is kept and resent with the
  next run instead of being lost with the baseline; a lock wait of two hours or a scan killed
  at its cap now posts an alert, and exits 3 with `ALERT NOT SENT` in the log when Slack is out
  too. Stale socket ties are not changed: a collision needs the same pid and costs the new boss's
  first two dispatches.

- **The guard no longer waves through three commands, and the version check no longer counts an orphan (ticket 33).**
  `sed -i 's/a/b/;e cmd;s/x/y/'` passed as a plain substitution, `wc --files0-from=-` passed as a plain filter, and
  `cd <owned>/missing && ...; <anything>` kept the owned directory past the `;`. All three were already so before
  PR 56. `boss-guard.py` now keeps the delimiter and newlines out of the substitution, allows only short flags per
  filter, and checks every `cd` of an `&&` chain when the chain ends. `version_gap.py` read no entrypoint from the
  real `.in_use` markers (pid and procStart only), so its orphan check never ran; it now takes the entrypoint from
  `sessions/<pid>.json` when that record's start time is the marker's, and without a record it judges on pid and
  start time alone. Comment fixes: the `.service.in` headers, `install.sh` and `bin/boss-link`.

- **A worker's report to the boss's name that fails is retried, not left in the pane (ticket 29).** Cause
  found by reproduction: the `from-name` on a boss's message (a session title) is not the name in the
  session registry, so a send to the `from-name` fails with "No agent named ... is reachable" while the
  registry name and the `from` socket address are delivered. The registry belongs to Claude Code, not
  this repo; why the two names differ (a `/remote-control` rename is one candidate) is not shown. The
  reporting contract now tells the worker to retry on the `from` address and to wait without a `pgrep`
  loop; Phase A says what `shell` means.

- **Reviews graded by risk and size (ticket 02, owner's decision of 2026-11-05).** P6 no longer
  says "every PR, up to three rounds". Under 100 added lines and not sensitive: one Codex round,
  another only for a defect of class a or b. 100 to 500 and not sensitive, or sensitive: up to
  three. Over 500: split before review. Findings that are only tests, docs, style or far-fetched
  cases become tickets and the PR closes. The standards review runs once per PR. The boss decides
  "sensitive" and records it on the PR; the worker may raise it, never lower it. The dispatch
  carries a short text of the rules.

- **Codex findings on PRs 43, 44, 45, 47 and 53 (ticket 25).** Guard classifier: a `sed` program
  other than a plain `s/…/…/` substitution, a heredoc marker in a comment or in quotes, `cat` reading a
  file beside a tracker write, a pipe filter with a file operand or `<`, and a `cd` that fails after
  `;` now count as work; `cat <<EOF >> pm/x` is read as a heredoc. Where the text cannot be read with
  certainty the call counts as work: the guard warns and logs, it is no boundary. `spawn --concierge`
  finds a concierge waiting on a permission prompt and starts no second one. The update-gap check
  counts a session live by `registry.is_live`'s rules and treats a cache dated far ahead as stale.
  The P17 proof asks for the resolved path of what runs, not only an import. `bin/boss-link` compares the
  installed systemd units with the current templates (taking `@ROOT@` and `@CFG@` from the installed unit's
  own lines) and prints one line naming a unit that differs and the command `install.sh`; it writes
  nothing and never fails a session start. `install.sh` is the one upgrade path (so `MemoryMax=1G` reaches
  installs that predate it): it copies a differing unit to `<unit>.bak-<YYYY-MM-DD-HHMMSS>` first and
  prints the path, and a template that does not render writes no unit. Old copies are not pruned. The
  first run after this release replaces each service unit once, because its header changed. A deliberate
  edit belongs in a drop-in (`<unit>.d/override.conf`), which is left alone.

- **A rule for a worker past 250k (ticket 03).** `CTX-OVER` no longer reads "overdue, ask for the
  boundary now". The owner's two tests apply: never restart a worker waiting on CI or merging with its
  PR open; otherwise ask how many turns are left and restart at the next boundary if more than about
  35, review fixes included (the estimate wins over the list). Nothing enforces the flag, it only
  shows in `list`, so the boss has to ask. New `routines/ctx_over_measure.py` reads that, per worker, into a private file
  under `<config>/pm/`.

- **The P17 dispatch text no longer asks for the database URL.** A URL can carry `user:pass@`, and the
  worker's report is copied into the boss's messages and transcripts. The worker now reports the
  database's host, port and name, never the URL as a whole and never a password or token. Found by
  Codex on PR 44.

- **`restart --require-idle` follow-ups (ticket 22).** `--wait-idle 08` is decimal, not octal (it used
  to skip the wait and refuse); `BOSS_RETRY_EVERY` must be a number (an `ERROR:` line, nothing typed)
  and is floored at 1 s; `--wait-idle` with `--expect-last` now refuses with "ran a turn during the
  wait" and SKILL.md says to leave the pin off. `shell` (background work running) stays
  refused by default, turn over or not, and `--wait-idle` keeps waiting on it: a finished turn is not a
  finished task (a worker waiting on CI with a Monitor armed reads so). The refusal tells a turn in
  flight from "turn over, background work still running" and gives the kinds and counts in the pane
  footer ("2 shells", "1 monitor"), read without typing; the jobs themselves are listed only by the
  exit dialog. New `--stop-shells` (with `--require-idle`; `--force` does not imply it) lets a `shell`
  with the turn over go through: it says so, prints each job and confirms the dialog. Look at the pane
  or ask the worker before using it. `self_register` stamps the calling pane only when the
  session in it is a boss (`boss-panes.py stamp-self`), so a worker that runs the script is no longer
  marked as a boss pane; stamps the old script left on worker panes stay until the pane is reused
  (no cleanup). `boss-panes.py --state` has a fifth field, `1`/`0` for the turn being over.

- **The watchdog reads a concierge's permission dialog on a narrow pane.** Measured on real
  renders at 74, 31 and 25 columns (`skills/boss/fixtures/watch/`): an Edit dialog at 25
  columns went unseen (header and `Tab to amend` both wrapped), and a concierge question
  worded like a dialog ("Do you want to proceed ...?" with a "Yes, and always ..." option)
  alerted at every width, because the 15-line window reaches it from 8 lines up. Now wraps are
  joined and blank rows dropped before matching; the header and option wording is read in the
  last 7 lines, the footer `Tab to amend` and the trust prompt in the last 15, and the real
  option `Yes, and switch to ...` is matched (the Edit dialog's real option 2 reads "Yes, and
  switch to accept edits", not the recalled "allow all edits"). Miss side, joined: `Tab to amend`
  is 1-2 lines from the bottom of every captured dialog, the header up to 13 lines at 25
  columns, so at 25 columns only the footer window catches the Edit dialog. Known residuals: a
  boss-written option "Yes, and always|switch to ..." in the last 7 lines of a concierge's
  question, and a captured width of 25 as the narrowest.

## 0.21.3 — 2026-11-04

- **`restart --require-idle` no longer refuses an idle worker.** With the "Background
  work is running" dialog up the session's status reads `waiting`, and the check
  after `/exit` demanded `idle`, so a worker with a leftover background task was
  refused as "a turn started" and `/exit` stayed typed in its pane. The check now
  accepts `idle`, `waiting` and `shell` there; the same session on the same input
  (the past-exit pin) is what says no turn started. `shell` stays "not idle" before
  `/exit`: it is also read mid-turn (measured), so it is retried, never typed at.
- **A refused restart is retried on a timer.** `--wait-idle <seconds>` reads the status
  every `BOSS_RETRY_EVERY` seconds (default 20) while the worker is busy, waiting or running a shell,
  types nothing meanwhile, and restarts when a read says idle. Still busy at the end
  is a refusal. The boss no longer depends on an idle notice that may never come.

## 0.21.2 — 2026-11-04

- **A weekly routine measures where the time and tokens go** (`boss-efficiency`): per
  track, wall time by state, tokens by phase, questions per day, CI waits and the
  share of the token budget, with workers found through the boss's socket. It speaks on
  Slack only when a track's own spending changes against the week before, or when the
  measuring failed; the fleet share and the coverage are in the report and never
  trigger. Reports and state stay under the config dir. See `routines/boss-efficiency.md`.

## 0.21.1 — 2026-11-04

- **A boss says when the plugin on this machine is behind.** On 2026-11-04 the
  installed plugin was 0.19.2 while 0.19.3 and 0.20.0 had been released two days
  earlier, and nothing said so. Cause: a marketplace install of a third-party
  repo is not refreshed by itself, so the version moves only when someone runs
  `marketplace update` and `plugin update`; and a live session keeps the version it
  started on, with that version's `bin/` ahead on PATH. `boss-version-gap` (the boss runs it at
  session start, SKILL.md step 1) compares installed, released (`plugin.json` on main) and running
  (live pids in the plugin cache's `.in_use` markers) and prints a line per gap, nothing
  when they agree.

## 0.21.0 — 2026-11-04

- **A question to the owner no longer stops the boss.** A new session, the
  concierge (`boss-lifecycle.sh spawn <dir> --concierge`), holds the
  `AskUserQuestion`, and the boss goes on dispatching. While one lives, the guard
  refuses the boss's own question; with none, a dead one, or no answer from tmux,
  the question goes through as before, and the same on a concierge stuck on a
  prompt. It reads its instructions from a file at every start, so a restart loses
  nothing; `restart` and `retire` refuse while it holds a question; the pulse does not
  press a boss to ask again while it has work in hand. Measured on 36 boss sessions: in 420 of 421
  questions over two minutes the boss did nothing until the answer, with 762 worker
  messages queued. See `references/concierge.md`.
- **Consent stays first-hand.** A peer message is never the owner's consent, so a
  question starting `CONSENT:` still opens in the boss's own turn.
- **It does not filter questions.** A filter was built into its brief and measured
  first: on 87 labelled past questions it sent back 14 of 50 that were the owner's and
  let through 23 of 37 that were not. It was taken out. Whether a question is the
  owner's stays the boss's judgement, and the concierge asks whatever it gets.

## 0.20.0 — 2026-11-02

- **A worker proves its run hits its own copy.** A worktree separates files, not
  what runs. Every dispatch that runs tests, a script or the app now asks for the proof: the
  path of the import, and where used the database URL and the pid on the port (P17).
- **The brief names the shared runtime.** `/hand-to-boss` writes one line per repo:
  what is shared and how a worker gets its own copy. With no own copy, workers run
  on it one at a time, on a turn the boss gives. This is a written rule; the pulse
  does not count it. The evidence, and why no slot was built, is in
  `references/incidents.md`.

## 0.19.3 — 2026-11-02

- **The guard stops flagging a boss for keeping its own tracker.** An Edit under
  `pm/` was never flagged; the same line appended from the shell was, and so was
  `export PATH=…; boss-lifecycle.sh`. A Bash call now passes when every statement
  in it is coordination: the boss's own tools, a `$(date)` stamp, or a write to
  `pm/` by `echo`, `printf`, `cat` or `sed -i`. A script is never coordination,
  even one run from `pm/`, because its reach cannot be read from its text. The
  older shortcut stands: a call whose head, after a `cd` or `VAR=` prefix, matches
  an allowed tool's name is still not read further. Replayed on the 4,968 flagged calls of 22 boss
  sessions over 14 days that could be matched to their full command, 964 no
  longer count and 4,004 still do. Those include reads of `pm/` and tracker edits
  by script, so that number is not a count of implementation work.

## 0.19.2 — 2026-11-01

- **`boss-link` never moves the stable link to an older version.** Every session
  runs it as a SessionStart hook from its own plugin version, so on 2026-11-01 a
  boss started on 0.19.0 compacted and pointed `routines/claude-boss` back from
  0.19.1: the timers ran the old rules. It now compares the `plugin.json`
  versions (`sort -V`) and prints `kept` instead. A missing or dangling link, or
  a root without a version, is still set; so is a root passed to it by
  `install.sh`, which is how a deliberate rollback moves it back.

## 0.19.1 — 2026-11-01

- **A command for the owner's hand also goes on the boss's session card.** On
  2026-11-01 a boss put three `gh run cancel` lines only in an `AskUserQuestion`,
  and the owner found nothing on the card. The rule (`references/escalation.md`,
  pointed to from P12): the question, a Paste on the card, and `$ ` in the
  team-line ask.

## 0.19.0 — 2026-10-30

- **Workers cannot ask the owner.** `boss-lifecycle.sh` starts every worker
  (spawn, restart, move) with `--disallowedTools AskUserQuestion`, so a choice
  a worker cannot make goes to the boss by SendMessage. Only the boss asks.
  The reporting contract a dispatch ends with says so. A boss started with
  `boss-start` keeps the tool.

## 0.18.1 — 2026-10-30

- **READY none no longer reads as an empty backlog.** With a ticket graph whose
  open tickets all waited on a person, the pulse said `READY NOW: none`, hid
  NEXT and offered no action, only the escape "the idle worker is deliberately
  parked". On 2026-10-30 a boss took that escape 174 times in 155 pulses while
  four side tickets in its own NEXT sat unstaffed, until the owner asked why
  one worker was busy. The pulse now shows NEXT and hands it out when nothing
  in the graph is READY, and "parked" has to name, per idle worker, the ticket
  or event it waits on.

## 0.18.0 — 2026-10-28

- **The systemd units survive a plugin upgrade.** `install.sh` wrote the
  plugin's cache directory into `ExecStart`, and a marketplace upgrade lands in
  a new one (`plugins/cache/<marketplace>/claude-boss/<version>/`), so the
  ladder and the watchdog failed on every tick from the next upgrade on.
  Measured on the author's machine: five days of `No such file or directory`,
  one tick a minute, including the morning a worker pane froze unseen. The
  units now run through `$CLAUDE_CONFIG_DIR/routines/claude-boss`, a symlink
  to the plugin root; `bin/boss-link` sets it from `install.sh` and, as a
  SessionStart hook, moves it to the new root on the first session after an
  upgrade. A real file or directory at the link path is never replaced.
  `uninstall.sh` removes the link. Five tests in `test_bin.py`.
- `install.sh` and `uninstall.sh` read an empty `CLAUDE_CONFIG_DIR` as unset,
  like the hooks since 0.17.0.

## 0.17.0 — 2026-10-27

- **An empty `CLAUDE_CONFIG_DIR` no longer breaks the hooks** (architecture
  review, candidate 1). `CLAUDE_CONFIG_DIR=""` was read as a path, not as unset,
  so the guard never fired and reap, compact and the ladder resolved `pm/` to
  `./pm` in whatever directory they ran from. An empty value now means
  `~/.claude`, in every hook.
- **The track store owns `pm/`.** `skills/boss/boss_store.py` is the one module
  that knows where things live and how they are read: the config and `pm/`
  paths, the objective and tracker reads (the pulse reads the tracker once per
  run), per-session state with a locked atomic update (one stable lock file,
  `pm/.pulse/.state.lock`, never a reap candidate), the reap candidates, the
  frontier cache path and key, and `open_tracks`. `boss-guard`, `boss-pulse`,
  `boss-compact`, `boss-reap`, `routines/boss_ladder_core.py` and `boss-panes`
  now ask it at call time; their own path constants are gone.
  `BOSS_LADDER_PM` and `BOSS_LADDER_STATE` still win in the ladder.
- **A bash agreement test.** `test_bash_agreement.py` lifts the path and cache
  key lines out of `boss-goal` and `boss-tracker`, runs them in bash and
  compares the result with the store, so the shell scripts cannot drift from it.
- `registry.py` stays a vendored copy, held equal to its original by a test;
  it and `hermetic.py` are the two documented exceptions to the store.

## 0.16.0 — 2026-10-26

- **The pulse decides as data, then words it** (architecture review,
  candidate 4). `boss-pulse.py`'s `main()` gathered the facts, decided what to
  tell the boss, built the numbered text and marked the fired rungs, all in
  one 140-line function, and its tests could only look for substrings in the
  text. `skills/boss/pulse.py` now holds `decide(facts)`, which returns the
  ordered actions, the due rungs it names and the fired marks (or nothing), and
  `render(facts, decision)`, which words them. The fired marks are part of the
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
  (ai-consultancy, example-fund, tray-indicator-state) said MET or PAUSED on
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
