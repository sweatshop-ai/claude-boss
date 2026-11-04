# Boss brief: boss efficiency

Written 2026-11-04 by Otilia with `/hand-to-boss`. You are the boss for track `boss-efficiency`. Read this file, then every source it names, before you dispatch anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full): the section "Cosa cambierei, in ordine di effetto" | `/home/tiroir/Documents/brain/01-projects/claude-code/2026-11-04-audit-efficienza-boss.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues/` |
| Handoffs | none |
| Research, orchestrators and evidence | `/home/tiroir/Projects/boss-plugin/.scratch/boss-audit/reports/Orchestratori alternativi al boss.md` |
| Research, review findings sample | `/home/tiroir/Projects/boss-plugin/.scratch/boss-audit/research_notes/review-yield-sample.md` |
| Audit scripts, for tickets 04 and 07 | `/home/tiroir/Projects/boss-plugin/.scratch/boss-audit/scripts/` |
| Code | `/home/tiroir/Projects/boss-plugin` (branch `main`) |
| Code, ticket 01 | `/home/tiroir/Projects/render-doc` (branch `main`) |
| Code, ticket 01 | sheaf: clone from `sweatshop-ai/sheaf` under `/home/tiroir/Projects/sheaf-wt/<worker>`; no main checkout found on this machine on 2026-11-04 |

## Frontier

The frontier on 2026-11-04 20:45 CET, from `frontier.py /home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues`:

```
Ready now: 01, 04, 07, 09, 10, 11
  01  One Python version on PRs, the full matrix on main only
  04  A weekly routine that measures where the time goes
  07  What happens in the gaps under two hours
  09  Why the installed plugin fell behind main
  10  Codex pass on PR 45
  11  boss-workers-watch reads a concierge's question as a permission prompt
Waiting on other tickets:
  05  after 04
External blockers:
  02: Thierry settles a grilling round on what counts as sensitive; not yet asked
  03: Thierry settles a grilling round on when not to restart; not yet asked
  05: three finished tracks run with a concierge
  06: Thierry labels a sample of past questions; not yet asked
  08: Thierry names a suitable ticket graph; not yet asked
Done: none
```

Re-run `python3 $CLAUDE_PLUGIN_ROOT/skills/hand-to-boss/frontier.py /home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues` after every ticket that closes; the output above is a snapshot.

External blockers: who holds each one, and what unblocks it.

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| 02 | A grilling round: what counts as sensitive | Thierry | not yet |
| 03 | A grilling round: when not to restart a worker | Thierry | not yet |
| 05 | Three finished tracks run with a concierge, and ticket 04 | nobody to ask; time | not applicable |
| 06 | Labels on a sample of past questions | Thierry | not yet |
| 08 | A suitable ticket graph | Thierry | not yet |

An external blocker is a person, not a task: nobody on the team works around it. A blocker the owner holds goes into your tracker's Open blockers and up the escalation ladder. Raise 02, 03, 06 and 08 together once the ready tickets are done, not one by one during the run: `/grilling` needs the owner at the keyboard.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting on an external blocker has Status `done` and its boxes ticked; the ones still waiting are listed with who holds them. Give it a `## Tickets` section holding `/home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues`, one line: the pulse then reads the frontier itself and hands you every ready ticket each time a worker goes idle.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`. `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/boss-plugin-wt/<worker>`, or `<repo>-wt/<worker>` for the other repos. Two workers never share a branch or a worktree.
- At most 4 workers at once. The audit this track comes from measured that more workers on a busy pool buy waiting, and track `action-list` is running on this machine with its own team.
- You are the first boss on 0.21.0: start your concierge as the session-start step says. Report anything in it that does not work: that is evidence for ticket 05.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues <NN> <worker>
git -C /home/tiroir/Projects/boss-plugin commit -m "Claim <NN> for <worker>" -- <ticket file>
```

`claim` writes `**Claimed by:** <worker> <date time>` above the Status line and sets `**Status:** in-progress`, under a lock, in the shared ticket file. It refuses (exit 3, naming the claimant) a ticket that is already claimed, done or still blocked; then nothing is dispatched. The commit names that one file by path, so it carries nothing else in a tree other sessions share, and no edit is left uncommitted. Both are coordination, not implementation: if the guard remarks on them, say so in one line and carry on.

The worker never edits the claim. It reads the ticket at its path under **Sources**, the shared file, never the copy inside its own worktree, and when it finishes it ticks the boxes and sets Status there, committing that file by path in the same way. To release a claim, the boss removes the line, sets Status back to `ready-for-agent`, commits the file by path and notes it in the tracker.

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran and what came back, the URL it read, the test that passed. It puts that evidence in its report. Status becomes `done` only when every box is ticked. A box that cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the source wins where this summary is short. None of the three repos has its own `CLAUDE.md` or `AGENTS.md`.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name." (`/home/tiroir/.claude/CLAUDE.md`)
- Production: "Never write to the gateway VPS". No ticket here touches a host; a worker that thinks otherwise stops and reports. (`/home/tiroir/.claude/CLAUDE.md`)
- Suites: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." (`/home/tiroir/.claude/CLAUDE.md`)
- Git: "Before a `git push` to a branch that deploys, say what it carries and ask once." Check with `~/.claude/routines/branch_deploys.py <checkout-path> <branch>`. In these repos main runs tests. (`/home/tiroir/.claude/CLAUDE.md`)
- Public repos: `sweatshop-ai/claude-boss` is public. Commit as `tiroir <202564+tiroir@users.noreply.github.com>`. No client name, measured client data or transcript text in a commit, a ticket or a PR. (`/home/tiroir/.claude/CLAUDE.md`)
- Transcripts stay on the machine: tickets 04 and 07 read `~/.claude/projects`, and nothing from it goes to Codex, Jev or GitHub. "Everything sent leaves the machine. Redact personal data first." (`/home/tiroir/.claude/CLAUDE.md`)
- Other team: track `action-list` (boss Janusz) has workers on `render-doc` and `sheaf` and uses the same three runners. Ticket 01 changes those repos' CI: tell Janusz by `SendMessage` before it merges, and apply P16's three push rules. Never cancel its runs. (`skills/boss/SKILL.md`)
- Reviews: every PR gets a Codex review on the head that merges; if Codex is out, the Opus fallback, and its follow-up becomes owed. (`skills/boss/SKILL.md`)
- Ticket 09 may not change `~/.claude.json` or `settings.json`: propose, do not widen. Installing the plugin on this machine is the owner's call. (`/home/tiroir/.claude/CLAUDE.md`)

## Shared runtime

What a running worker shares beyond its files, one line per repo in Sources, and how it gets its own copy.

| Repo | Shared when it runs | Own copy per worker |
|---|---|---|
| boss-plugin | tmux server and registry in live tests; a real `~/.claude/pm` | Unit tests are hermetic through a throwaway `CLAUDE_CONFIG_DIR`. Live tests: own tmux session named `<worker>-test`, kill it after, and never a real track name |
| render-doc | Editable install with a src layout; a run can import the main checkout | Prove the import path (P17); `conftest` guard is in place |
| sheaf | Editable install with a src layout, as render-doc | Prove the import path (P17) |
| `~/.claude/projects` | Read by 04 and 07 at about 5 GB | One at a time, at `nice`: both scan the transcripts |

A resource with no own copy goes one at a time: writing code stays parallel, and you give one worker the turn to run on it, then the next.

## Time windows

None stated on 2026-11-04.

## Language

Report to the owner in the language of their last message: Italian or English. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss`: you are running it.
- `mattpocock-skills:tdd`: 01, 04, 09 and 11, for code.
- `mattpocock-skills:code-review`, then `/codex-review`: before every merge.
- `mattpocock-skills:diagnosing-bugs`: 09.
- `mattpocock-skills:pr`: every PR body.
