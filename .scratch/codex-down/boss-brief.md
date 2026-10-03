# Boss brief: keep the PR gate working when Codex is down

Written 2026-10-03 by Bettina with `/hand-to-boss`. You are the boss for
track `codex-down`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/boss-plugin/.scratch/codex-down/plan.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/boss-plugin/.scratch/codex-down/issues/` |
| Handoffs | none |
| Research | Domain glossary (tracker, open blocker, marker, rung, policy): `/home/tiroir/Projects/boss-plugin/CONTEXT.md`. Current Codex gate and its prose: `/home/tiroir/Projects/boss-plugin/skills/boss/SKILL.md` (the "Codex is the external reviewer" section). Current reviewer chain: `/home/tiroir/Projects/boss-plugin/skills/boss/bin/boss-run`. |
| Code | `/home/tiroir/Projects/boss-plugin` (branch `main`) |

## Frontier

The frontier on 2026-10-03 23:52 CEST, from `frontier.py /home/tiroir/Projects/boss-plugin/.scratch/codex-down/issues`:

```
Ready now: 01
  01  One reviewer chain, shared
Waiting on other tickets:
  02  after 01
  03  after 02
  04  after 03
  05  after 02
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.9.1/skills/hand-to-boss/frontier.py /home/tiroir/Projects/boss-plugin/.scratch/codex-down/issues`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| none | — | — | — |

The one judgement the plan needed (which model is the fallback reviewer) was settled
by the owner on 2026-10-03: Claude Opus, read-only. It is recorded in the plan and in
ticket 03; do not reopen it.

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/boss-plugin-wt/`.
  Two workers never share a branch or a worktree.
- At most 2 workers at once (five is the span of control). The graph is mostly a
  chain: only 03 and 05 can run side by side, after 02.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.9.1/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/boss-plugin/.scratch/codex-down/issues <NN> <worker>
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
source wins where this summary is short. The repo has no `CLAUDE.md` or `AGENTS.md`
of its own; the owner's global rules apply.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`)
- Shared tree: "Never `git checkout` in a shared working directory when other workers are in the same project. One checkout moves everyone." (`/home/tiroir/.claude/CLAUDE.md`)
- Production: nothing in this plan touches a host. Tests run each hook as a process against a throwaway `CLAUDE_CONFIG_DIR` and must not call Codex or TypeSafe, post to a channel or move a tmux pane: "Nothing touches your real state, calls TypeSafe, posts to a channel or moves a tmux pane." (`/home/tiroir/Projects/boss-plugin/README.md`, Tests). Stub `codex`, `claude` and `gh` in tests.
- Devices and hosts the team may and may not touch: none needed. The installed plugin under `~/.claude/plugins/cache/` is not edited; work happens in the repo and its worktrees.
- Git: `main` deploys nothing (`branch_deploys.py /home/tiroir/Projects/boss-plugin main` exits 1; the repo has no `.github/workflows`). "Where nothing deploys, push." (`/home/tiroir/.claude/CLAUDE.md`)
- Git: the repo is **public** (`sweatshop-ai/claude-boss`). Commits use `tiroir <202564+tiroir@users.noreply.github.com>`, already set in the repo's git config; never a personal address. No host names, IPs, client names or personal data in code, tests or commit messages. (`/home/tiroir/.claude/CLAUDE.md`, Git identity)
- Git: commits carry only the message, no "Generated with Claude Code" or "Co-Authored-By" lines. (`/home/tiroir/.claude/CLAUDE.md`, Git Commits)
- Review: every PR still needs its Codex review on the head that merges (`skills/boss/SKILL.md`). This plan changes that gate; until ticket 03 lands, the old rule holds for this work too.
- Release: do not bump the plugin version or reinstall it as part of these tickets. Releasing is a separate step the owner asks for.

## Time windows

None stated on 2026-10-03.

## Language

Report to the owner in English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every ticket; each has tests in its acceptance boxes.
- `mattpocock-skills:code-review` — on each branch before its PR.
- `/codex-review` — the Codex review on each PR head, as the gate requires.
- `mattpocock-skills:domain-modeling` — if a ticket adds a term (provisional GO, reviewer outage) to `CONTEXT.md`.
