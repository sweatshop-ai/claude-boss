# The objective, and the pulse that reads it

Load this when you are writing an objective, when a Done-when criterion is hard to
phrase, or when the pulse is firing and you think it should not be.

## Turning what the owner said into an objective

They give an outcome in a sentence. Deriving the fields is the boss's job, and
reading them back is what stops a whole night of work aimed at the wrong thing.

Worked example. What the owner asked for, in one sentence: *"land PR #36 so Priya can approve it, and
Northwind works with two users."*

```markdown
## Outcome
PR #36 is merged on acme/memory-service and a second Northwind user can read
and write memories without seeing the first user's.

## Done when
- [ ] gh:acme/memory-service#36 merged
- [ ] checks:acme/memory-service@main green
- [ ] `pytest tests/test_two_connectors.py` passes on `main`
- [ ] `docs/runbooks/owner-backfill.md` exists and Priya has read it

## Deliverables
- merged PR #36, and the follow-ups it spawned (#39, #43)
- the runbook, in the repo

## Constraints
- no push to `main`; every fix is its own PR from `main`
- CatalogEntry.owner stays as designed — reopening it is Priya's call, not ours

## Pause when
- Priya's approval on the API shape
- the lab-0 deploy: the owner's explicit go, per the runbook

## Next, in priority order
1. rebase #39 onto main and merge it
2. triage the two remaining red runner-env tests on acme-voice #6
3. close out the merge inventory: compute-node #8, acme-docs #18
```

Every line of that was already known at 23:15. None of it was written down where
anything could read it — and the first two criteria are now things `boss-goal
verify` answers by itself, without anyone forming an opinion.

## Done-when criteria

The test: **could somebody else run this and get the same verdict?**

| Wish | Criterion |
|---|---|
| PR 36 is in good shape | `gh:acme/memory-service#36 merged` — and `verify` resolves it |
| CI is happy | `checks:acme/memory-service@main green` |
| the deploy worked | `curl -s lab-0:8642/v1/health` returns 200 |
| the docs are updated | `docs/runbooks/owner-backfill.md` exists and names the backfill command |
| two users are isolated | `pytest tests/test_two_connectors.py` passes on `main` |

`boss-goal check` flags a criterion with no command, no issue number, no URL and no
filename. It is a warning, not a refusal — some real criteria are human reads, and
"Priya has read the runbook" is one. But if half the list is warnings, the objective
is not finished being written.

Three to six criteria. One is usually a milestone pretending to be an objective;
a dozen is the tracker's job.

## The Next list

**Three deep, refilled the moment it empties.** It is the answer to "a worker just
went idle, what does it get", and answering that without a round-trip to the owner is
most of what a boss is for.

Sources, in order: the objective's own remaining criteria, the GitHub board, the
tracker's pending items. Never invented (safety rule 12).

When the list is genuinely empty and the criteria are genuinely met, the track is
over — close it rather than leaving the boss circling.

## When the pulse fires and you disagree

It fires because your objective is OPEN and a worker of yours is idle, or a rung
came due. Exactly one of four things is true, and each has a different move.

| What is actually the case | Do this |
|---|---|
| There is work and you had not noticed the worker was free | dispatch it. This is the case it exists for |
| The Next list is empty | refill it (`boss-goal next`), then dispatch |
| The worker is parked on purpose — waiting on a review, holding a worktree | say so in one line and stop. The pulse re-fires at most once a minute and will not argue |
| The objective is finished | `boss-goal status <track> met "<evidence>"`. Name what met it |

If it fires when the team is genuinely busy, the ownership stamps are wrong: the
pulse counts a pane as yours when `@boss_pane` says so, and `boss-lifecycle.sh
list` shows the same. A worker you adopted without `claim` is invisible to both.

To stop it entirely for a track: `boss-goal status <track> paused "<why>"`. To stop
it for good, delete the goal file — no objective, no pulse.

## Where this comes from

The shape is not invented here. Harnesses that keep an agent on a long-running task
converged during 2026 on the same three parts: a durable objective with an explicit
definition of done, a check that runs when the agent tries to finish, and a
re-injection of the objective into a fresh context so it survives summarisation.
Hermes's `/goal` names the fields; the "Ralph loop" names the re-injection. Claude
Code gives the third part natively — a `Stop` hook's `additionalContext` is
delivered to the model and the turn continues — so `boss-pulse.py` is twenty lines
of policy over a mechanism that was already there.

What is specific to this fleet is what the pulse counts as a reason: an idle worker
that this boss owns, and an escalation rung that has come due. Both are things a
boss should never have needed a human to notice.

## The three gates, and what each one cannot do

| Gate | Answers | Blind to |
|---|---|---|
| `check` | Is it well formed? Placeholders, criteria present, size, pulse armed | Whether any of it is true or relevant |
| `review` | Is anything structurally missing? | Anything only the owner knows |
| `verify` | Which criteria are true right now, by query | Criteria with no machine anchor |
| the one question | What the owner is actually afraid of | Nothing else — ask it every time |

They are cheap in that order and none substitutes for another. A worked case,
measured on 2026-09-09 against the objective as it stood the night before:

- `check` passed it. One criterion, no placeholders, under cap. A lint cannot
  tell that one criterion is too few.
- `review` returned INCOMPLETE with three MISSING lines, all real: the runbook
  deliverable had no criterion, the lab-0 deploy had no verification and
  nothing about the data already there, and Pause-when was empty on work that
  touches production.
- `review` did **not** find the two-user isolation gap — the Curator cross-owner
  vector. Nothing in the file pointed at it. That is the shape of what a reviewer
  structurally cannot supply, and it is why the one question is not optional.

## GitHub is the anchor, not the store

The objective lives on disk, not in an issue. Agent `gh issue` writes are blocked
by the classifier on this machine — it is why Matt Pocock's tracker skills are
configured against a local markdown tracker rather than GitHub — so an objective
in an issue is one the boss can read and cannot maintain. A boss handing the owner a
clipboard command to update its own objective is the failure this whole file
exists to remove.

Reads are a different matter and are already allowed: read-only `gh` is in the
boss's permitted set. So point the criteria at GitHub and let `verify` do the
asking.

```
- [ ] gh:owner/repo#39 merged        # PR merged, not just closed
- [ ] gh:owner/repo#35 closed        # issue state
- [ ] checks:owner/repo@main green   # every check-run on that ref
```

`verify` never executes text from the file. A backticked command in a criterion is
documentation for a human, and stays that way — the objective is a file a worker
can write to, and a verifier that ran what it found there would be a way to make
the boss run anything.

The `checks:` rule encodes a trap from `~/.claude/CLAUDE.md`: **zero checks is not
success, it means nothing ran.** `verify` reports that ref as UNKNOWN, never MET.
