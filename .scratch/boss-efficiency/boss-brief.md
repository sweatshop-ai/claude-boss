# Boss brief: token review rules

Written 2026-11-19 by Rafael with `/hand-to-boss`. You are the boss for track `token-review`. Read this file, then every source it names, before you dispatch anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full): the decisions page, owner's answer 1A 2A 3A 4A 5A on 2026-11-19 | `/home/tiroir/.claude/plans/2026-11-19-token-review-decisions.md` |
| Earlier plan, for the one-round rule and the boss's own costs | `/home/tiroir/.claude/plans/2026-11-15-token-consumption-plan.md` |
| Tickets, one file each, in dependency order (this track: 45, 46, 47, 48, 49, 50) | `/home/tiroir/Projects/boss-plugin-wt/rafael-rocco/.scratch/boss-efficiency/issues/` |
| Handoffs | none |
| Research: the measuring scripts of 16–19 November, for ticket 50 | `/home/tiroir/.claude/plans/2026-11-19-token-scripts/` |
| Code, tickets 45–49 | `/home/tiroir/Projects/boss-plugin-wt/rafael-rocco` (claude-boss, base branch `main`; tickets live on branch `rafael/rocco-tickets`) |
| Code, ticket 50 | `/home/tiroir/.claude/routines/` (the owner's config repo `~/.claude`, single branch `main`) |

The main checkout `/home/tiroir/Projects/boss-plugin` is 322 commits behind and holds other sessions' uncommitted files: never work, claim or commit there.

## Frontier

The frontier on 2026-11-19 15:32 CET, from `frontier.py /home/tiroir/Projects/boss-plugin-wt/rafael-rocco/.scratch/boss-efficiency/issues`, lines for this track:

```
Ready now: 45, 47
  45  the boss chooses between a worker, a subagent and a Monitor by rule
  47  a missing .boss/deploy.json refusal says how to fix it
Claimed: 46 (Rafael (2026-11-19, inside ticket 48)), 48 (Rafael (2026-11-19))
Waiting on other tickets:
  49  after 48
  50  after 49
```

The same output lists older tickets of the folder (05, 06, 08, 10, 12, 13, 21, 23, 27, 28, 36, 42) as external blockers; they belong to the closed boss-efficiency track and are not yours.

Re-run `python3 $CLAUDE_PLUGIN_ROOT/skills/hand-to-boss/frontier.py /home/tiroir/Projects/boss-plugin-wt/rafael-rocco/.scratch/boss-efficiency/issues` after every ticket that closes; the output above is a snapshot.

Tickets 46 and 48 are being built now by Rafael (a subagent of the session that wrote this brief) on branch `rafael/review-rules`, worktree `/home/tiroir/Projects/boss-plugin-wt/rafael-review-rules`, as PR to main with release 0.26.0. Do not dispatch them. Rafael tells you by `SendMessage` when 48 is merged; then 49 opens.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| 50 | Where the owner writes the twice-daily `/usage` percentages during the calibration week | Thierry | not yet; ask once when 50 is dispatched |

An external blocker is a person, not a task: nobody on the team works around it. A blocker the owner holds goes into your tracker's Open blockers and up the escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting on an external blocker has Status `done` and its boxes ticked, written as one line per ticket or per run of them, named `<feature>/<NN>` (`token-review/45 and 47 at Status done`, `token-review/49 at Status done`, `token-review/50 at Status done`), so FleetView can show each line's state; the ones still waiting are listed with who holds them. Give it a `## Tickets` section holding `/home/tiroir/Projects/boss-plugin-wt/rafael-rocco/.scratch/boss-efficiency/issues`, one line: the pulse then reads the frontier itself and hands you every ready ticket each time a worker goes idle. Ignore the old tickets of the closed track it will also list.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`. `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without `--model` lands there too.
- One git worktree per worker, on its own branch off `origin/main`, under `/home/tiroir/Projects/boss-plugin-wt/<worker>`. Two workers never share a branch or a worktree. Ticket 50 works in `~/.claude` directly (single-branch repo, no worktree needed; commit only its own paths).
- At most 2 workers at once: the frontier has two ready tickets, and 49 and 50 run one after the other by the owner's decision 5A.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/boss-plugin-wt/rafael-rocco/.scratch/boss-efficiency/issues <NN> <worker>
git -C /home/tiroir/Projects/boss-plugin-wt/rafael-rocco commit -m "Claim <NN> for <worker>" -- <ticket file>
```

`claim` writes `**Claimed by:** <worker> <date time>` (replacing an existing
`Claimed by` line) and
sets `**Status:** in-progress`, under a lock, in the shared ticket file. It
refuses (exit 3, naming the claimant) a ticket that is already claimed, done or
still blocked; then nothing is dispatched. A ticket may carry `**Claimed by:**`
empty or with `none`, `nobody` or `-` (any case): all mean unclaimed. The commit names that one file by
path, so it carries nothing else in a tree other sessions share, and no edit is
left uncommitted. Both are coordination, not implementation: if the guard
remarks on them, say so in one line and carry on.

The worker never edits the claim. It reads the ticket at its path under
**Sources**, the shared file, never the copy inside its own worktree, and when
it finishes it ticks the boxes and sets Status there, committing that file by
path in the same way. To release a claim, the boss removes the line, sets
Status back to `ready-for-agent`, commits the file by path and notes it in the
tracker.

Push the tickets branch (`git -C /home/tiroir/Projects/boss-plugin-wt/rafael-rocco push`) after each claim or close: it deploys nothing.

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran
and what came back, the URL it read, the test that passed. It puts that evidence
in its report. Status becomes `done` only when every box is ticked. A box that
cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the source wins where this summary is short. claude-boss has no `CLAUDE.md` or `AGENTS.md` of its own.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`)
- Suites: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." The full suite runs in CI on t-compute. (`/home/tiroir/.claude/CLAUDE.md`)
- Git: "A branch whose workflows only run tests, lint or CI comments is not a deploy: merge or push there yourself, no question." `branch_deploys.py /home/tiroir/Projects/boss-plugin main` on 2026-11-19: tests.yml only. (`/home/tiroir/.claude/CLAUDE.md`)
- CI: "After every push, check CI for that commit … Check `.total_count` first: zero checks is not success." (`/home/tiroir/.claude/CLAUDE.md`)
- Public repo: `sweatshop-ai/claude-boss` is public. Commit as `tiroir <202564+tiroir@users.noreply.github.com>` (set in the worktree). No client name, measured client data or transcript text in a commit, a ticket or a PR. (`/home/tiroir/.claude/CLAUDE.md`)
- Reviews: "A PR gets Matt's `code-review` plus `/codex-review` once. The Opus agent runs only when Codex actually fails … A boss does not launch its own review of a PR its worker already had reviewed." From ticket 48 on, NO-GO only for a serious defect; minor findings are fixed in the same push with no new round. (`/home/tiroir/.claude/CLAUDE.md`, plan decision 3)
- Ticket 50: transcripts stay on the machine. Only counts and session names go to Slack; "Everything sent leaves the machine. Redact personal data first." Routine alerts go to Slack #claude-ops, credentials in `~/.config/tiroir/slack.env`. (`/home/tiroir/.claude/CLAUDE.md`)
- Ticket 50 creates a systemd user timer: a new standing routine the owner chose in decision 1A, so it is in scope; widening `settings.json` permissions or `autoMode` is not. (`/home/tiroir/.claude/CLAUDE.md`)

## Shared runtime

| Repo | Shared when it runs | Own copy per worker |
|---|---|---|
| claude-boss | tmux server and registry in live tests; a real `~/.claude/pm` | Unit tests are hermetic through a throwaway `CLAUDE_CONFIG_DIR`. Live tests: own tmux session named `<worker>-test`, kill it after, never a real track name |
| `~/.claude/routines` | `~/.claude/projects` (several GB of transcripts) read by ticket 50 | One at a time, at `nice` |

## Time windows

None stated on 2026-11-19.

## Language

Report to the owner in Italian. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss`: you are running it.
- `mattpocock-skills:tdd`: 45, 47, 49 and 50, test first.
- `mattpocock-skills:code-review`, then `/codex-review`: once per PR before the merge.
- `mattpocock-skills:pr`: every PR body.
