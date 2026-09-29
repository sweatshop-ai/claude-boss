# Boss brief: {{feature}}

Written {{date}} by {{your session name}} with `/hand-to-boss`. You are the boss for
track `{{track}}`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `{{plan path}}` |
| Tickets, one file each, in dependency order | `{{issues dir}}/` |
| Handoffs | `{{path}}` — or "none" |
| Research | `{{path}}` — or "none" |
| Code | `{{repo path}}` (branch `{{base branch}}`) — one line per repo |

## Frontier

The frontier on {{date time}}, from `frontier.py {{issues dir}}`:

```
{{frontier.py output, verbatim}}
```

Re-run `python3 {{plugin root}}/skills/hand-to-boss/frontier.py {{issues dir}}`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| {{NN}} | {{what}} | {{person or team}} | {{where and when, or "not yet"}} |

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them.

## Staffing

- You run on `{{boss model}}`.
- Every worker runs on `{{worker model}}`: `boss-lifecycle.sh spawn <dir> --model {{worker model}}`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `{{worktree root}}`.
  Two workers never share a branch or a worktree.
- At most {{N}} workers at once (five is the span of control).

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 {{plugin root}}/skills/hand-to-boss/frontier.py claim {{issues dir}} <NN> <worker>
git -C {{repo holding the tickets}} commit -m "Claim <NN> for <worker>" -- <ticket file>
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
source wins where this summary is short.

- Shared tree: {{rule}} (`{{CLAUDE.md path}}`)
- Production: {{rule}} (`{{source}}`)
- Devices and hosts the team may and may not touch: {{rule}} (`{{source}}`)
- Git: {{branches that deploy, who may push, where a push needs the owner}} (`{{source}}`)

## Time windows

| When | What must not happen | Why |
|---|---|---|
| {{date, from–to, timezone}} | {{what stays untouched}} | {{reason}} |

Or: "None stated on {{date}}."

## Language

Report to the owner in {{language}}. Files, commits, tickets and PRs in {{language}}.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- {{skill}} — {{when a worker needs it}}
