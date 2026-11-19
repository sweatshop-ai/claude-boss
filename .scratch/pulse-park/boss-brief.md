# Boss brief: pulse park

Written 2026-11-19 by Farouk with `/hand-to-boss`. You are the boss for
track `pulse-park`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/.scratch/pulse-park/README.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/.scratch/pulse-park/issues/` |
| Domain terms | `/home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/CONTEXT.md` |
| Measurement behind the plan | `/home/tiroir/.claude/projects/-home-tiroir-Projects-boss-plugin/memory/idle-workers-pulse-measured.md` |
| Owner's rule on team size | `/home/tiroir/.claude/projects/-home-tiroir-Projects-boss-plugin/memory/no-worker-cap-for-tokens.md` |
| Handoffs | none |
| Research | none |
| Code | `/home/tiroir/Projects/boss-plugin-wt/pulse-park-desk` (branch `pulse-park/desk`, made from `origin/main` 7bc6381; base branch for PRs `main`) |

The desk worktree exists because `/home/tiroir/Projects/boss-plugin` sits on a local
`main` 336 commits behind `origin/main`, with another session's uncommitted edit to
`.scratch/codex-down/issues/12-usage-limit-means-fallback-now.md`; the tickets are not
in that tree. Work from the desk, never from that tree.

## Frontier

The frontier on 2026-11-19 17:44 CET, from `frontier.py /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/.scratch/pulse-park/issues`:

```
Ready now: 01, 02, 03, 05
  01  The pulse records why it stays silent
  02  No worker limit, an 8 GB memory floor instead
  03  Park with a checked condition (local events)
  05  Unassigned work on tracks without a ticket graph
Waiting on other tickets:
  04  after 03
  06  after 01, 03, 05
  07  after 02, 03
  08  after 01, 02, 03, 04, 05, 06, 07
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.25.0/skills/hand-to-boss/frontier.py /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/.scratch/pulse-park/issues`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| none | — | — | — |

No ticket waits on a person. Merges into `main` are yours (see Guardrails, Git).

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked, written as one line
per ticket or per run of them, named `<feature>/<NN>` (`pulse-park/01 to 08 at Status
done`), so FleetView can show each line's state; the ones still waiting are listed
with who holds them. Give it a `## Tickets` section holding
`/home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/.scratch/pulse-park/issues`, one line: the pulse then reads the frontier itself and hands you
every ready ticket each time a worker goes idle.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/boss-plugin-wt/`.
  Two workers never share a branch or a worktree.
- At most 4 workers at once (12 is the span of control): as many as the
  frontier has ready tickets (01, 02, 03, 05 now). The owner's standing rule is no cap
  for token spend, only free memory: keep 8 GB `MemAvailable`
  (`no-worker-cap-for-tokens.md` above).
- Branches and PRs: each ticket's worker branches off `origin/main` as
  `pulse-park/NN-<slug>` and opens one PR into `main`. Tickets 01, 02, 03 and 05 all
  touch the pulse (`skills/boss/pulse.py`, `skills/boss/boss-pulse.py`): merge them one
  at a time, and have the next one rebase on `main` before its merge.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.25.0/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk/.scratch/pulse-park/issues <NN> <worker>
git -C /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk commit -m "Claim <NN> for <worker>" -- <ticket file>
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

Ticket-state commits on `pulse-park/desk` reach `main` as backup: `git -C /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk pull --rebase origin main && git -C /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk push origin HEAD:main`,
only when the desk carries nothing but `.scratch/pulse-park/` changes
(check with `git -C /home/tiroir/Projects/boss-plugin-wt/pulse-park-desk diff --stat origin/main..HEAD`).

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran
and what came back, the URL it read, the test that passed. It puts that evidence
in its report. Status becomes `done` only when every box is ticked. A box that
cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the
source wins where this summary is short. The repo has no `CLAUDE.md` or
`AGENTS.md` of its own; the owner's global file binds it.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`). Never `git add -A`, `stash`, `checkout` or `pull` in `/home/tiroir/Projects/boss-plugin`.
- Tests: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." and "Kill your own test runs when you stop waiting on them" (`/home/tiroir/.claude/CLAUDE.md`). The full suite runs in CI (`.github/workflows/tests.yml`, on every PR and on push to `main`).
- Live state: the pulse reads and writes `~/.claude/pm/` and `~/.claude/pm/.pulse/`, where every running boss keeps its state. Tests point the config dir at a temporary directory; no test and no worker writes into the real `~/.claude/pm/`.
- Production: nothing in this plan touches a host.
- The plugin you run: you and your workers run the installed claude-boss 0.25.0 from the plugin cache, not this checkout (`origin/main` is at 0.27.0). Workers change code in worktrees; never edit `/home/tiroir/.claude/plugins/cache/`. The new park and block behaviour reaches running bosses only after the owner updates the plugin, which is not part of this plan.
- Git: "Before a `git push` to a branch that deploys, say what it carries and ask once. … A branch whose workflows only run tests, lint or CI comments is not a deploy: merge or push there yourself, no question" (`/home/tiroir/.claude/CLAUDE.md`). `branch_deploys.py` on `main` reports `tests.yml` only, "reads as tests only" (checked 2026-11-19): merge green PRs yourself.
- Git identity: this is a public repo; "Git identity for anything PUBLIC: `tiroir <202564+tiroir@users.noreply.github.com>`" (`/home/tiroir/.claude/CLAUDE.md`). The desk has it; check `git config user.email` in each new worktree before its first commit.
- Commits: "After creating a commit, run `git commit --amend` to remove the Claude Code footer" (`/home/tiroir/.claude/CLAUDE.md`).
- Review: "One review round per PR … A PR gets Matt's `code-review` plus `/codex-review` once. The Opus agent runs only when Codex actually fails … NO-GO only for a serious defect" (`/home/tiroir/.claude/CLAUDE.md`).
- CI: "After every push, check CI for that commit … Check `.total_count` first: zero checks is not success, it means nothing ran." (`/home/tiroir/.claude/CLAUDE.md`)
- Owner: workers never ask the owner; they ask you, and you ask through the concierge only for a decision that is his (README, last line). The design is settled; do not reopen it with him.

## Shared runtime

| Repo | Shared when it runs | Own copy per worker |
|---|---|---|
| `/home/tiroir/Projects/boss-plugin-wt/pulse-park-desk` | nothing installed or served; tests are plain `python3 -m pytest` over `skills/`, the only shared state is `~/.claude/pm/` | a temporary config dir per test (see Guardrails, Live state) |

## Time windows

None stated on 2026-11-19.

## Language

Report to the owner in English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every code ticket (01–07), each starting with its failing test.
- `mattpocock-skills:domain-modeling` — when a worker adds a term (park, wake event, memory floor) to `CONTEXT.md`.
- `mattpocock-skills:code-review` then `/codex-review` — once per PR, before the merge.
- `mattpocock-skills:pr` — each PR body.
