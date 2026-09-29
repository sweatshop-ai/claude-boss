---
name: hand-to-boss
description: Hand an approved plan and its tickets to a new boss session in its own tmux session, which runs a team of workers on them.
disable-model-invocation: true
argument-hint: "<plan-path> [boss-model=opus] [worker-model=sonnet] [--dry-run <dir>]"
---

# Hand to boss

The last link of a chain:

```
grill -> plan -> to-tickets -> hand-to-boss -> boss + workers
```

You write a **brief** for a boss that does not exist yet, commit it next to the
tickets, start that boss in its own tmux session, and report its name. The boss
then works the ticket graph for hours with a team. That is why this skill fires
only when the owner types it.

**Arguments**: `$ARGUMENTS` — the plan path; then optionally the boss model
(default `opus`) and the worker model (default `sonnet`). `--dry-run <dir>` runs
steps 1 and 2 only and writes the brief into `<dir>`: nothing is committed,
nothing is launched.

## How this differs from a handoff

A handoff (`handoff`, `claude-handoff`) passes **a conversation** to **one
agent**. This passes **a plan with a dependency graph** to **a manager with a
team**. So the brief also carries what a single agent never needs: the frontier,
who holds each external blocker, staffing, how a ticket is claimed, guardrails
that must hold across days, and time windows. It ends with the boss's name, since
the owner has to reach it.

Three rules are borrowed from those handoffs and hold here:

- **Point, never copy.** Every source is referenced by path. The plan is not
  summarised into the brief; the boss reads the plan.
- **Redact.** No key, password, token or personal data in the brief. A credential
  is named by the path of the file that holds it.
- **Suggested skills.** The brief closes with the skills the boss and its workers
  will need.

## 1. Check the input

You need a plan file and a folder of ticket files in the format `to-tickets`
writes: `NN-slug.md`, each with a `**Blocked by:**` field and a `**Status:**`
line. The tickets usually sit in `.scratch/<feature>/issues/` beside the plan.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/hand-to-boss/frontier.py <issues-dir>
```

Exit 0 prints the frontier. Exit 2 names what is wrong: no tickets, a ticket
without Blocked by, a reference to a ticket that does not exist.

**No plan, no tickets, or exit 2: stop.** Tell the owner which is missing and
point to `grill` to settle the plan and `to-tickets` to cut it. The graph is the
thing the boss works from; a plan improvised here would be one nobody approved.

Done when: the plan exists, `frontier.py` exits 0, and at least one ticket is
**Ready now**. None ready means the team would start idle: say which blockers
hold everything and stop.

## 2. Write the brief

Copy `brief-template.md` (beside this file) to `boss-brief.md` in the folder
that holds the `issues/` folder, and fill every `{{placeholder}}`:

- **Sources**: the plan; the tickets folder; any handoff, research note or ADR
  the plan or tickets cite; every code repo the tickets touch, with its base
  branch. Absolute paths, each one checked with `ls`.
- **Frontier**: the `frontier.py` output verbatim. For each external blocker, the
  person or team holding it and where it was asked, from the ticket text and the
  conversation. Unknown is written as "not yet asked", never guessed.
- **Staffing**: the models from the arguments; the worktree root (beside the repo,
  `<repo>-wt/<worker>`, unless the repo's rules say otherwise).
- **Guardrails**: read the `CLAUDE.md` / `AGENTS.md` of every repo in Sources
  (and their parent folders) and the owner's `~/.claude/CLAUDE.md`. Quote the
  lines that bind this work — shared working trees, branches that deploy,
  production hosts, client devices, what needs the owner's own hand — each with
  its source path. A rule that does not touch this plan stays out.
- **Time windows**: any date and time when something must stay untouched (a demo,
  a call, a release freeze), from the plan, the tickets and the conversation, with
  the timezone. None found → "None stated on <date>."
- **Language**: the language the owner speaks in this conversation, for reports;
  the language of the plan and tickets, for files and commits.
- **Suggested skills**: what the tickets call for (`tdd` for code, `code-review`
  before a merge, a deploy or a domain skill the repo carries).

The claiming rule and the verified-done rule are in the template already. They
stay word for word: the boss protocol assigns work but keeps no owner on a
ticket file, so the claim line is what stops two workers from taking the same
ticket off one frontier.

Done when: `grep -n '{{' boss-brief.md` finds no placeholder left, every path in
it exists, and it holds no secret. In `--dry-run`, stop here and give the owner
the path.

## 3. Commit the brief

Commit `boss-brief.md` alone, by path, next to the tickets:

```bash
git -C <repo> add -- <brief path> && git -C <repo> commit -m "Boss brief for <feature>" -- <brief path>
```

Then push if the repo's rules let you push that branch without asking. When the
push cannot happen — the branch deploys and needs the owner, or the tree is shared
with other sessions' uncommitted work and a pull would carry theirs — leave it
committed, and say in one line that it is not pushed and why. The boss reads the
file from disk; the push is backup, not a precondition.

## 4. Launch

Name the tmux session `boss-<track>`, where `<track>` is the feature slug. First
check it is free: `tmux has-session -t boss-<track>` must fail, and
`boss-tracker list` must not show the track. Either exists → a boss may already
run this plan; stop and ask the owner.

```bash
tmux new-session -d -s boss-<track> -c <repo> \
  "BOSS_MODEL=<boss-model> BOSS_WORKER_MODEL=<worker-model> \
   ${CLAUDE_PLUGIN_ROOT}/skills/boss/bin/boss-start <track> \
   '/claude-boss:boss monitor — your brief is <brief path>. Read it first, then every source it names.' ; \
   exec \$SHELL"
```

The seed carries **the brief's path**, never its text: the command line of a
process is readable by every user on the machine and ends up in `ps`, shell
history and logs. `boss-start` adds the boss's effort, autocompact and fallback
settings; `BOSS_WORKER_MODEL` makes the worker model the default for every spawn
in that session. `exec $SHELL` keeps the pane open if Claude exits, so the
reason can be read.

## 5. Find the boss's name

The pane id: `tmux list-panes -t boss-<track> -F '#{pane_id}'`. Wait until
Claude has registered in it (use `Monitor` with an until-loop on the command
below, not `sleep`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-panes.py <pane-id>
```

It prints `pane  name  session  status …` once the session exists. Then confirm
with `ListAgents`: the row whose tmux location ends in `.<pane-id>` is the boss,
and that row's name is the one to report. If the pane stays at a trust or
permission dialog, that is the owner's hand: tell them to attach and answer it.

Report, in three lines:

- the boss's name (what `SendMessage` reaches),
- the tmux session `boss-<track>` and `tmux attach -t boss-<track>`,
- the brief's path, and whether it is pushed.

Done when the name comes from the `ListAgents` row, not from the pane title.
