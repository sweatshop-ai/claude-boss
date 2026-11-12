# claude-boss — domain terms

**Boss**: a Claude session that coordinates workers and does no implementation
itself. It holds a boss file and a track.

**Boss file**: `pm/.boss-sessions/<session_id>`, which makes a session a boss;
its first line, once claimed, is the track. Written by `boss-marker register`.
_Avoid_: marker (that is the ladder's token on an open blocker)

**Worker**: any session a boss dispatches to. One task per session.

**Concierge**: a session a boss owns that holds its questions to the owner, so that
the boss's turn never stops on a question. Not a worker: no ticket is for it and the pulse does not count it. The
pane option `@worker_role` says which pane it is.

**Agent-teams teammate**: a session that a Claude Code agent-teams lead
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) spawned inside its own process. Not a
worker: it has no pane and no stamp, dies with its lead, and the boss neither
dispatches to it nor sees it. A worker may lead them; a boss never does.
_Avoid_: teammate (alone), sub-worker

**Burst**: one worker running parallel helpers for the length of one ticket —
background subagents by default, agent-teams teammates when the parts must talk.
Its cost lands in that worker's context.
_Avoid_: team (means `/team`, the peer mesh between workers)

**Ticket graph**: the tickets of a track and their Blocked-by edges — a folder
of ticket files, or the sub-issues of one GitHub issue with GitHub's own
dependencies. Named in the objective's `## Tickets`.
_Avoid_: backlog, task list (no edges)

**Frontier**: the tickets of a ticket graph that can be dispatched now: not
done, not claimed, every blocker done, nothing external open.
_Avoid_: ready list, queue

**Track**: the name of a boss's tracker (`pm/<track>.md`) and objective
(`pm/<track>.goal.md`).

**Track store**: the one module that names files under `pm/` and reads and
writes them as raw text: the boss file, the tracker, the objective,
per-session state. It knows where a file is, not what its text means; the
formats stay with `objective.py` and `tracker.py`. `skills/boss/boss_store.py`.
_Avoid_: pm paths, state dir

**Policy**: the steering numbers a boss and its workers act on — context
bands, cost lines, escalation rungs, review waits, and the exact model and
tool values of the read-only fallback. One module,
`skills/boss/policy.py`; the prose quotes it and `test_policy.py` keeps the
quotes true.

**Transcript**: a session's append-only JSONL log. Context, cost per turn and
the pin are read from its last 4 MB by one module, `skills/boss/transcript.py`.

**Pin**: the uuid of the last user, assistant or queued-command record in a
transcript. A worker that took input after the boss looked has a newer one.

**Flag**: what the policy says about one session right now, by role.
Worker: `CTX-SPLIT` (cut the task at its next boundary), `CTX-OVER` (past 250k: the "Session age" rule applies).
Boss: `CTX-EVAL`, `CTX-RESTART`. Either: `heavy`, `RECYCLE` (cost per turn).

**Stamp**: the `@boss_pane` option on a tmux pane, naming the pane of the boss
that owns it. Only the stamp makes a pane a boss's; `fleet.py` reads and writes it.

**Seat**: one tmux pane and the live session running in it, if any (`fleet.py`).
A pane with no session is an empty seat; a crashed worker leaves one.

**Shared pane**: a pane that more than one live session names in its registry
record. The oldest is the pane's own session; the flag `shared-pane` and the line
under the row in `list` name the others.

**Handoff**: the file a worker writes before a restart — branch, what was tried
and rejected, live constraints, next step.

**Rung**: a point on the escalation ladder, in minutes since a blocker's T+0,
at which the blocker is raised to the owner again.

**Tracker**: `pm/<track>.md`, the boss's live state. Its formats — the Open
blockers section, the marker, the lock — live in `skills/boss/tracker.py`.

**Open blocker**: a bulleted line under the tracker's first `## Open blockers`
heading. Something is blocked on the owner.

**Marker**: the `[ladder id=… t0=… last=… next=… ask="…"]` token on an open
blocker. The ladder escalates that line from it, with no boss turn.

**Pulse decision**: what the pulse tells a boss at a Stop, as data before it
is worded: the ordered actions (`ask`, `fix-graph`, `dispatch-ready`,
`spawn n`, `dispatch-next`, `refill-next`, `run-rung n`), the due rungs it
names (`overdue`, three at most) and the fired marks (`fired`: each rung
already said) saved once the text is out; or nothing, and the boss is left
alone. `skills/boss/pulse.py` decides and words it; `boss-pulse.py`
gathers the facts and owns the gate and the state file.

**Objective status**: the first `_Status: …_` line of `pm/<track>.goal.md`,
wherever it sits; `boss-goal status` rewrites that same line. A track is open
when it starts with OPEN. The objective's format — status, sections, ticket
source — lives in `skills/boss/objective.py`; `boss-goal` reads and writes it
through that module's command line.

**Reviewer chain**: the order in which a second model is asked for an answer:
Codex first, then an optional fallback model through `claude`, otherwise
nobody answered. One module, `skills/boss/reviewer_chain.py`, three callers:
`boss-run` (a `VERDICT:` of APPROVE/REJECT, fallback `opus`), `boss-goal review`
(COMPLETE/INCOMPLETE, fallback `opus`) and `boss-goal premortem` (eight or more
`RISK:` lines, fallback `fable`). `boss-run` runs nothing unless it returns a
whole answer. Its result says which reviewer answered (`codex`, the fallback's
name, or `none`) and keeps every attempt.

**Acceptance rule**: what the chain counts as a usable answer. Either a
`VERDICT:` line carrying one of the caller's words, or at least N lines under
one label (`RISK:`), returned with the label stripped. A fallback runs only when
Codex's answer fails the rule.

**Attempt reason**: why one reviewer's turn ended as it did, from a closed set:
`answered` (a usable verdict), `absent` (not on PATH), `timeout`, `error`
(non-zero exit), `noverdict` (it answered with no usable `VERDICT:` line). A
usable verdict always wins, whatever the exit status.

**Fallback**: the spec of the model asked when Codex fails: a name, an exact
model id, a timeout (twice Codex's unless set), an optional tool restriction, variables
the child does not inherit (`env_unset`), extra `claude` flags
(`extra_args`, put ahead of `-p` because `--tools` and its kind take any number
of values and `-p` ends them), and which Codex reasons let it run. Optional;
without one the chain is Codex only. Callers name one by **preset**
(`opus` = `claude-opus-5-5`, `fable` = `claude-fable-5-1`), so the model ids are
written in `reviewer_chain.py` alone. A preset's `claude` is looked up on our PATH
without empty, relative and checkout-local entries and started by absolute path; its child
gets our PATH minus the empty and relative entries only. With no `--cwd` a preset keeps nothing out for being
under the current directory (the confined spec still does). `claude_argv` builds its call, the one
place, and `fallback_flags` renders a whole spec as command-line flags for a
caller that starts the chain as a child process.

**Waiver**: a PR merged on tests alone while Codex is down, only through `boss_review.py --waive`. The owner chose it
for the open `Codex down` blocker (`codex_blocker.py --choose T tests-alone`) with a `CONSENT:` question asked in the boss's
own turn; the guard's PostToolUse hook turned the owner's yes (one button, one question, the track and the exact test
command named) into a **consent token**, `pm/consent/<session_id>.json`, good for `policy.CONSENT_TTL` seconds and
withdrawn by any later Ask. Both commands read the token themselves and fail closed (exit 2 for `--choose`, 5 for
`--waive`). `--waive` runs the command in a clean checkout and records a `kind: waived` round (reviewer `tests`) only if the
head, base and checkout did not move and the choice and token still stand under the PR's lock. A forged token, a
hand-written round or another route to a merge by a process of the same user is outside it (accepted by the owner).

**Read-only fallback**: the PR gate's fallback, `boss_review.fallback_spec()`:
`claude` on the policy's exact model, `--tools Read,Grep,Glob`,
`--strict-mcp-config` (without it `--tools` alone leaves every MCP tool in),
`--disable-slash-commands`, `--restricted`, `--safe-mode` and
`--permission-mode dontAsk`.
`--restricted` keeps the user, project and local settings files out (`claude -p` skips the workspace
trust dialog, so without it a hook in the PR checkout's `.claude/settings.json`
runs, and so do the owner's own hooks and plugins) and confines the file tools
to the working directory. `--safe-mode` also turns off the checkout's agents,
output styles, workflows, skills and CLAUDE.md. The `claude` child also does not
inherit the variables in `policy.REVIEW_FALLBACK_ENV_UNSET` (`env_unset` on the
spec: plugin directories, managed and remote settings paths, launchers and loaders): a plugin directory named there loads its hooks even under `--restricted`
(found 2026-11-12 by the real check). The review does not run it yet.
`boss_review.py --check-fallback --checkout DIR` runs it once from DIR with a
one-word prompt, with `--include-hook-events` so that every kind of hook shows, and passes only if the stream holds no hook event and the init
event shows exactly Glob, Grep and Read, no MCP servers, no slash commands,
only plugins that are part of claude, that permission mode and that model id.
It is a smoke test on the real CLI; the suite checks the argv and the decision
on a stub.

**Merge gate**: `skills/boss/boss_merge.py --repo OWNER/REPO --pr N [--dry-run] [--test-only-since SHA]`, the one merge path the skill names.
It reads the PR once with `gh`, walks the PR's review rounds from the highest number down (`decide`) and merges with
`gh pr merge --merge --match-head-commit <head it read>` only if the first round that decides allows it: a `codex` GO on
any base, a `provisional` or `waived` GO only on a base listed in the repo's `.boss/deploy.json` (`non_deploying`, exact
names, read from the base branch through `gh api`, never from the PR's head). It fails closed: a round it cannot read, a
provisional or waived GO that any later round supersedes, a missing or invalid deploy file (every branch then deploys) all
refuse. `--test-only-since SHA` (ticket 11b) lets fixes after the last GO through without a new review when `SHA` is the head of a GO that `decide` allows, no NO-GO stands above it, and every file changed since matches the base branch's `test_paths` (`fnmatch.fnmatchcase` on the whole path, where `*` also crosses `/`, so anchor a pattern to a directory: `tests/*`, not `*test_*.py`); it is looked at only when the live head has no deciding round. Exit 0 merged, 2 usage or not open, 3 no usable GO, 4 a weak GO on a deploying branch, 5 the merge or the check
after it failed, 7 a `gh` read failed; every decision is one line in `pm/reviews/merges.jsonl`. It does not stop a merge
typed by hand in a shell: `boss-run` refuses one under the hard rule `PR merge outside boss_merge` (ticket 11a: `gh pr merge` with a repo
option on either side of `pr`, a path to `gh`, the REST `PUT .../pulls/N/merge` and the `mergePullRequest` mutation; the
default-GET "is it merged?" call is not refused), and only branch protection closes the rest. SKILL.md states that and
two more limits (a base retargeted in the window, a listed branch that later deploys).

**Review round**: one run of `skills/boss/boss_review.py` on one PR head. The
review runs first (Codex only, in a child process told `--cwd` the checkout, as
named and made absolute, never folded);
the round is claimed at the end of the run, under the PR's lock, whatever the
review said (GO, NO-GO, nothing, a head that moved), so numbers follow posting
order and each comment's number is its file's. A failure before the claim
leaves nothing behind. Kept under
`$CLAUDE_CONFIG_DIR/pm/reviews/<owner>/<repo>/pr<N>/`, never in a checkout,
private (0700 and 0600). Its status is `posted`, `head-moved` (the head or the
base moved during the review), `no-verdict`, `post-failed` or `list-failed` (a provisional GO that could not be
listed in the track's tracker is not posted).

**Provisional entry**: one line `- [prov owner/repo#N] head=<7 to 40 hex> round=<NN, two digits at least> base=<branch> at=<ISO
8601 time>` under `## Provisional GO` in a track's tracker, written before a provisional GO is posted. A line off
that form (a short head, a round of one digit or not a number, an `at=` that is no time, a repo without `owner/repo`) is
no entry: the reader and the replace-by-tag step both skip it, so a hand-edited line is never taken over. An entry
means "must recheck", not "a comment exists": it is kept when the PR cannot be read after the write or the comment
fails, because a kept entry is rechecked by ticket 10 and a dropped one is a provisional GO nobody revisits.
The prune (ticket 06b) keeps an entry whose PR has a round file it cannot read as a record (a half-written one, one
nested too deep for the JSON parser, one whose own repo, pr or round are not its file's). A round file that is empty
and has a later round above it is a dead claim, not an unreadable record: the prune skips it, so the next review of
that PR (the recheck of ticket 10 included) clears the entry it kept; the newest round left empty still keeps it.
A merged PR's entry is cleared by a Codex GO on the head it merged at (rule 4) or, when that is the entry's own head, by rule 1; a Codex GO on the entry's head never clears it when the PR merged at another head (ticket 35).

**Recheck**: `skills/boss/boss_recheck.py --track T --repo OWNER/REPO --checkout DIR [--author NAME]` (ticket 10a), the pass
that has Codex alone review again each entry of a repo under `## Provisional GO`. It runs `prune_provisional` first and after
each review, and reviews each entry in a detached worktree of its own (`boss-recheck-*` in the temp dir, fetched from
`refs/pull/<N>/head`, never `--checkout` itself): an open PR at its live head, a merged PR at its merged `headRefOid`
(not the entry's `head=`), a PR closed without a merge not at all. A Codex NO-GO on an open PR prints `NO-GO <repo>#<N>
round <NN> author=<name>` and keeps the entry. A Codex NO-GO on a merged PR writes an open blocker (`fx` and 8 hex of the
sha1 of "<repo>#<N> round <NN>", so one id per round; `boss-alert 0` once), removes that exact entry line, and prints
`DISPATCH <repo>#<N> author=<name> round=<NN>`; a crash between the two is resumed from the round on disk, with no new review,
no second blocker and no second alert, even after the blocker was cleared. No Codex answer leaves the entry. `--list` and
the release stop are ticket 10b.

**Round record**: `round<NN>.json`, what a gate reads. A round is `posted` only
after `gh pr comment` returned success, so a comment on the PR with no `posted`
record behind it authorizes nothing. A round claimed and never finished is an
empty file; the next round supersedes it and no round file is edited after its
final write. `round<NN>.out` beside it holds the reviewer's full answer.

**Repo key**: `<owner>/<repo>` lowercased by `repo_key`, the one spelling used
for a PR's directory, lock and records, because GitHub does not tell the cases
apart. It refuses anything but two plain names.
