# Boss brief: the track store

Written 2026-10-27 by Otilia with `/hand-to-boss`. You are the boss for
track `track-store`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/boss-plugin/.scratch/track-store/plan.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/boss-plugin/.scratch/track-store/issues/` |
| Domain terms | `/home/tiroir/Projects/boss-plugin/CONTEXT.md` |
| Handoffs | none |
| Research | none (the architecture review that led here was a temp page, not kept) |
| Code | `/home/tiroir/Projects/boss-plugin` (base branch `main`; integration branch `feat/track-store`, see Staffing) |

## Frontier

The frontier on 2026-10-27, from `frontier.py /home/tiroir/Projects/boss-plugin/.scratch/track-store/issues`:

```
Ready now: 01
  01  An empty `CLAUDE_CONFIG_DIR` means `~/.claude` in every hook
Waiting on other tickets:
  02  after 01
  03  after 02
  04  after 01
  05  after 01
  06  after 02, 03, 04, 05
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.11.5/skills/hand-to-boss/frontier.py /home/tiroir/Projects/boss-plugin/.scratch/track-store/issues`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| 06 | the merge of the PR into `main` | the owner (Thierry) | not yet; ticket 06 opens the PR |

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them. Give it a `## Tickets` section holding
`/home/tiroir/Projects/boss-plugin/.scratch/track-store/issues`, one line: the pulse then reads the frontier itself and hands you
every ready ticket each time a worker goes idle.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/boss-plugin-wt/`.
  Two workers never share a branch or a worktree.
- Branches: create `feat/track-store` off `main` first. Each ticket's worker
  branches off it as `feat/track-store-NN` and its work is merged back into
  `feat/track-store` when the ticket is done. Ticket 06 opens the one PR,
  `feat/track-store` → `main` (plan, decision 12).
- At most 3 workers at once (12 is the span of control): after 01, the frontier
  never holds more than 02, 04 and 05 together.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.11.5/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/boss-plugin/.scratch/track-store/issues <NN> <worker>
git -C /home/tiroir/Projects/boss-plugin commit -m "Claim <NN> for <worker>" -- <ticket file>
```

`claim` writes `**Claimed by:** <worker> <date time>` above the Status line and
sets `**Status:** in-progress`, under a lock, in the shared ticket file. It
refuses (exit 3, naming the claimant) a ticket that is already claimed, done or
still blocked; then nothing is dispatched. The commit names that one file by
path, so it carries nothing else in a tree other sessions share, and no edit is
left uncommitted. Both are coordination, not implementation: if the guard
remarks on them, say so in one line and carry on.

The worker never edits the claim. It reads the ticket at its path under
**Sources**, the shared file, never the copy inside its own worktree, and when
it finishes it ticks the boxes and sets Status there, committing that file by
path in the same way. To release a claim, the boss removes the line, sets
Status back to `ready-for-agent`, commits the file by path and notes it in the
tracker.

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran
and what came back, the URL it read, the test that passed. It puts that evidence
in its report. Status becomes `done` only when every box is ticked. A box that
cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the
source wins where this summary is short. The repo has no `CLAUDE.md` or
`AGENTS.md` of its own; the owner's global file binds it.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`). `/home/tiroir/Projects/boss-plugin` on `main` holds other sessions' untracked files under `.scratch/codex-down/` and the CONTEXT.md edits of this plan (uncommitted, see below): never `git add -A`, never `git stash` or `checkout` in that tree.
- Tests: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." and "Kill your own test runs when you stop waiting on them" (`/home/tiroir/.claude/CLAUDE.md`). The full suite runs in CI (`.github/workflows/tests.yml`).
- Production: nothing in this plan touches a host. "Never write to the gateway VPS (`137.74.12.211`, tiroir.me)." (`/home/tiroir/.claude/CLAUDE.md`)
- The plugin you run: you and your workers run the installed claude-boss 0.11.5 from the plugin cache, not this checkout. Workers change code in worktrees; never edit `/home/tiroir/.claude/plugins/cache/`.
- Git: "Before a `git push` to a branch that deploys, say what it carries and ask once." (`/home/tiroir/.claude/CLAUDE.md`). `main` runs only `tests.yml` here; no push to `main` is part of this plan: the PR merge is the owner's. Pushing `feat/track-store*` branches is backup and needs no ask.
- Git identity: this is a public repo; "The personal `tiroir@gmail.com` and the work `thierry@thinkingtoo.com` must not end up in a public repo's history." (`/home/tiroir/.claude/CLAUDE.md`). The repo config already sets `202564+tiroir@users.noreply.github.com`; worktrees inherit it, check with `git config user.email` before the first commit.
- Commits: "After creating a commit, run `git commit --amend` to remove the Claude Code footer" (`/home/tiroir/.claude/CLAUDE.md`).
- Review: "When a diff needs a bug hunt, run `/codex-review` (a different model) after it. If Codex is unavailable (usage limit, outage), fall back to a fresh Opus agent at once" (`/home/tiroir/.claude/CLAUDE.md`).
- CI: "After every push, check CI for that commit … Check `.total_count` first: zero checks is not success, it means nothing ran." (`/home/tiroir/.claude/CLAUDE.md`)
- CONTEXT.md: the **Track store** and **Boss file** entries are edited but uncommitted in `/home/tiroir/Projects/boss-plugin` on `main`. Ticket 01's worker carries them onto `feat/track-store` (copy the file's diff, commit it there by path), then restores the main tree's copy with `git -C /home/tiroir/Projects/boss-plugin restore -- CONTEXT.md` only after the commit on the branch exists.

## Time windows

None stated on 2026-10-27.

## Language

Report to the owner in English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every code ticket (01–05); ticket 01 starts with its failing test.
- `mattpocock-skills:domain-modeling` — when a worker names something CONTEXT.md does not define yet.
- `mattpocock-skills:code-review` then `/codex-review` — ticket 06, before the PR.
- `mattpocock-skills:pr` — ticket 06, the PR body.
