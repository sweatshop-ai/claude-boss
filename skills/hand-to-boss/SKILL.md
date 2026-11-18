---
name: hand-to-boss
description: Hand a plan and its ticket graph to a new boss session in its own tmux session, which runs a team of workers on them. Drafts the graph from the conversation when there is none yet, and launches only after the owner approves it.
user_invocable: true
disable-model-invocation: true
argument-hint: "[plan-path] [boss-model=opus] [worker-model=sonnet] [--dry-run <dir>]"
---

# Hand to boss

The last link of a chain:

```
grill -> plan -> to-tickets -> hand-to-boss -> boss + workers
```

The chain may stop early. When the owner types this after a discussion, with no
plan file or no tickets yet, you draft what is missing from the conversation and
show it for approval (steps 1 and 2). When the plan and its tickets already exist,
they were approved when they were cut, and you go straight on.

You write a **brief** for a boss that does not exist yet, commit it next to the
tickets, start that boss in its own tmux session, and report its name. The boss
then works the ticket graph for hours with a team. That is why this skill fires
only when the owner types it.

**Arguments**: `$ARGUMENTS` — optionally the plan path (left out: find it, or
draft it, step 1); then optionally the boss model (default `opus`) and the worker
model (default `sonnet`). `--dry-run <dir>` runs steps 1 to 3 only and writes
everything it drafts, and the brief, into `<dir>`: nothing is committed, nothing
is launched.

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

## 1. Find the plan and the ticket graph, or draft them

The boss needs a plan file and a folder of ticket files in the format
`to-tickets` writes: `NN-slug.md`, each with a `**Blocked by:**` field and a
`**Status:**` line, in `.scratch/<track>/issues/` beside the plan. `<track>` is the
feature slug: short, lowercase, hyphens; it names the tmux session, the window,
the boss's tracker and its Remote Control sessions.

Look in this order, and take the first that holds:

1. **A plan path in the arguments.** Its `issues/` folder beside it, if any.
2. **This conversation.** A plan or ticket folder written or named in it, above
   all by `to-tickets` or `to-spec` just now.
3. **The repo.** `.scratch/*/issues/` and `.scratch/*/*.md` changed in the last
   day (`find .scratch -newermt '-1 day'`). More than one candidate and the
   conversation does not say which: ask the owner with `AskUserQuestion`, one
   option per candidate.

Then one of three cases:

- **A. Plan and tickets exist.** Check the graph:

  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/hand-to-boss/frontier.py <issues-dir>
  ```

  Exit 0 prints the frontier: skip step 2, the graph was approved when it was
  cut. Exit 2 names what is wrong (no tickets, a ticket without Blocked by, a
  reference to a ticket that does not exist, a cycle): fix what is mechanical
  (a missing `**Blocked by:** None`), name the rest to the owner and stop.
- **B. A plan, no tickets.** Cut them as `to-tickets` would. Read its skill file,
  `ls ~/.claude/plugins/cache/*/mattpocock-skills/*/skills/engineering/to-tickets/SKILL.md`
  (the newest version), and follow its slice rules and its local ticket template;
  its quiz is step 2 here. Missing: the format in the `frontier.py` docstring.
  Write them to `.scratch/<track>/issues/`.
- **C. Only the conversation.** The decisions are in it but no file holds them.
  Write the plan to `.scratch/<track>/plan.md`: goal, the decisions taken (each
  with who took it, from the conversation), scope and what is out of scope, the
  repos and branches, open questions. Point to what exists (files, ADRs, PRs);
  never copy it. Then cut the tickets as in B.

**Enough material** for B or C means: the goal is stated, the scope is settled,
and every ticket you write has acceptance criteria you took from the
conversation or the plan, not invented. Missing any of them: draft nothing, tell
the owner what is missing in one line each, and point to `grilling` to settle it.
A graph built on guesses is one the owner would approve without having decided it.

Done when: `frontier.py` exits 0 on the folder, and at least one ticket is
**Ready now**. None ready means the team would start idle: say which blockers
hold everything and stop.

## 2. Show the graph and wait for approval (cases B and C)

What you drafted goes to the owner before anything is committed or launched.
Write `.scratch/<track>/review.md` in the owner's language, as a project
document (the sheaf house rules: an H1 naming the subject, a lead of 1–3
sentences, `##` labels from the trade):

- the plan's path and, in 3–5 lines, what the boss will build and what it will
  not touch;
- the graph, from `frontier.py --mermaid <issues-dir>`, in a ` ```mermaid ` block;
- the frontier as text, from `frontier.py <issues-dir>`;
- a table of the tickets: number, title, blocked by, what it delivers;
- the open points: every external blocker and who holds it ("not yet asked" when
  nobody was), every guess you had to make.

Render it and open it for the owner:

```bash
sheaf .scratch/<track>/review.md
```

Give the `http://127.0.0.1:…` URL it prints. No `sheaf` on the machine: show the
plan's path, the frontier and the ticket table in the chat instead.

Then ask once, with `AskUserQuestion`: **launch the boss on this graph**
(recommended), **change it first** (they say what, or edit the page), or **stop**.
On "change it": re-read the plan, the tickets and `review.md` from disk (the owner
may have edited them on the page), apply what they asked, run `frontier.py`
again, re-render, and ask again. Nothing goes further on any answer but "launch".

## 3. Write the brief

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
- **Shared runtime**: for every repo in Sources, read the compose files, fixed
  ports, database settings and the venv's editable install, then write what is
  shared and the exact setting that gives a worker its own copy. Prove the import
  path in a throwaway `git worktree add --detach`, then `git worktree remove` it.
  Where no own copy exists, write "none: one at a time"; where the repo runs nothing
  shared, write "nothing shared".
- **Time windows**: any date and time when something must stay untouched (a demo,
  a call, a release freeze), from the plan, the tickets and the conversation, with
  the timezone. None found → "None stated on <date>."
- **Language**: the language the owner speaks in this conversation, for reports;
  the language of the plan and tickets, for files and commits.
- **Suggested skills**: what the tickets call for (`tdd` for code, `code-review`
  before a merge, a deploy or a domain skill the repo carries).

The claiming rule and the verified-done rule are in the template already. They
stay word for word: the boss protocol assigns work but keeps no owner on a
ticket file, so the claim, written by the boss with `frontier.py claim` and
committed by path, is what stops two workers from taking the same ticket off
one frontier.

Done when: `grep -n '{{' boss-brief.md` finds no placeholder left, every path in
it exists, and it holds no secret. In `--dry-run`, stop here and give the owner
the path.

## 4. Commit the brief

Commit `boss-brief.md` by path, next to the tickets, with what you drafted in
steps 1 and 2 (the plan, the ticket files, `review.md`), never anything else:

```bash
git -C <repo> add -- <paths> && git -C <repo> commit -m "Boss brief for <feature>" -- <paths>
```

Then push if the repo's rules let you push that branch without asking. When the
push cannot happen — the branch deploys and needs the owner, or the tree is shared
with other sessions' uncommitted work and a pull would carry theirs — leave it
committed, and say in one line that it is not pushed and why. The boss reads the
file from disk; the push is backup, not a precondition.

## 5. Launch

The boss starts through `boss-start`, never a bare `claude`: that is where the
boss's effort, autocompact and fallback settings live, and a boss started
without them compacts only at the 1M ceiling. Given the track, `boss-start` also
names the tmux window `<track>` and puts the boss on Remote Control as
`<track> (boss)`; the concierge the boss spawns joins as `<track> (concierge)`.
So the owner can follow the track and answer its questions from claude.ai/code
or the phone. `BOSS_REMOTE_CONTROL=0` in the launch line turns both off, only when
the owner asks for that.

Name the tmux session `boss-<track>` and its window `<track>`. Two checks before
anything starts:

- **Free.** `tmux has-session -t boss-<track>` must fail, and `boss-tracker list`
  must not show the track. Either exists → a boss may already run this plan;
  stop and ask the owner.
- **Trusted.** Claude Code asks "Do you trust this folder?" on its first run in
  a folder, and a boss stuck on that question never registers. The folder is
  trusted when it or a parent has `hasTrustDialogAccepted: true` in
  `~/.claude.json`:

  ```bash
  python3 -c 'import json,sys; from pathlib import Path; p=json.loads((Path.home()/".claude.json").read_text()).get("projects",{}); d=Path(sys.argv[1]).resolve(); print(any(p.get(str(q),{}).get("hasTrustDialogAccepted") for q in [d,*d.parents]))' <repo>
  ```

  `False` → ask the owner with `AskUserQuestion` whether to launch anyway and
  answer the prompt in the pane themselves (the tab opened at launch, or
  `tmux attach -t boss-<track>`), or to stop. Only their hand answers it.

```bash
tmux new-session -d -s boss-<track> -n <track> -c <repo> \
  "BOSS_MODEL=<boss-model> BOSS_WORKER_MODEL=<worker-model> \
   ${CLAUDE_PLUGIN_ROOT}/skills/boss/bin/boss-start <track> \
   '/claude-boss:boss monitor — your brief is <brief path>. Read it first, then every source it names.' ; \
   exec \$SHELL"
```

The seed carries **the brief's path**, never its text: the command line of a
process is readable by every user on the machine and ends up in `ps`, shell
history and logs. `BOSS_WORKER_MODEL` makes the worker model the default for
every spawn in that session. `exec $SHELL` keeps the pane open if Claude exits,
so the reason can be read.

Then open the boss in a new terminal tab, so the owner sees it without typing
the attach command. In WezTerm (`$TERM_PROGRAM` is `WezTerm`, or `wezterm cli
list` answers):

```bash
wezterm cli spawn --cwd <repo> -- tmux attach -t boss-<track>
```

It prints the new pane id. The tab is a tmux client like any other: closing it
detaches, and the boss keeps running. Any other terminal, or `wezterm cli`
fails: open nothing, and the report's attach line is the way in. Never let a
failed tab stop the launch.

## 6. Find the boss's name

The pane id: `tmux list-panes -t boss-<track> -F '#{pane_id}'`. Wait up to 90
seconds for Claude to register in it, with `Monitor` on an until-loop, never
`sleep`:

```bash
for i in $(seq 90); do
  row=$(python3 ${CLAUDE_PLUGIN_ROOT}/skills/boss/boss-panes.py <pane-id>)
  [ -n "$row" ] && { echo "$row"; exit 0; }; sleep 1
done; echo TIMEOUT; tmux capture-pane -p -t <pane-id> | tail -40
```

A row reads `pane  name  session  status …`. Then confirm with `ListAgents`:
the row whose tmux location ends in `.<pane-id>` is the boss, and that row's
name is the one to report.

**TIMEOUT**: report what the captured pane shows, verbatim, and stop. A trust
or permission dialog there is the owner's hand: ask them through
`AskUserQuestion` to attach and answer it, then run the wait once more. Any
other screen (an error, a shell prompt) is the finding; report it rather than
relaunching.

Check Remote Control on the same screen: `tmux capture-pane -p -t <pane-id>`
shows `/remote-control is active` and the session's `https://claude.ai/code/…`
link. Missing: say so in the report; the boss runs anyway.

Report, in four lines, in the owner's conversation language:

- the boss's name (what `SendMessage` reaches),
- the tmux session `boss-<track>`, window `<track>`, whether its tab opened, and
  `tmux attach -t boss-<track>`,
- Remote Control: `<track> (boss)` and its link, or that it is off and why; the
  concierge joins as `<track> (concierge)` when the boss starts it,
- the brief's path, and whether it is pushed.

Done when the name comes from the `ListAgents` row, not from the pane title.
