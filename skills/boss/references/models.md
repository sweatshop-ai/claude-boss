# Choosing a worker's model, and where the cheap model belongs

## Which model runs the boss (2026-11-15; Fable from 2026-09-08)

The boss runs on **Opus 5.5**, and so do workers by default. `boss-start` sets
the first, `boss-lifecycle.sh spawn` the second.

Apply the criterion below to the boss itself. Its deliverable is a judgement:
whether a worker's "zero found" counted the right unit, whether a plan collides
with another worker, whether the 26% asymmetry mentioned in passing is the real
finding. Nobody checks the boss's reading of a report; if it misses the defect,
the defect ships. That is the right-hand column, and it rules out Sonnet for the
boss even at half the price.

**Why not Fable any more.** List prices
([platform.claude.com pricing](https://platform.claude.com/docs/en/about-claude/pricing), read 2026-11-15):

| | input | cache write 5m | cache read | output |
|---|---:|---:|---:|---:|
| Fable 5.1 | $10 | $12.50 | $0.25 | $50 |
| Opus 5.5 | $4 | $5 | **$0.20** | $20 |
| Opus 5 | $5 | $6.25 | $0.50 | $25 |
| Sonnet 5.5 | $2 | $2.50 | $0.10 | $10 |

The 2026-09-08 choice rested on Fable re-reading at half the price of Opus 5
($0.25 against $0.50), since a boss mostly re-reads. Opus 5.5 re-reads at $0.20
(a 0.05× multiplier) and is cheaper on every other column too. On a measured boss
turn (chat-box boss, 2026-11-13..15: 239k cache read, 1.7k cache write, 527 output)
a call costs $0.067 on Opus 5.5, $0.108 on Fable and $0.034 on Sonnet 5.5.

**Where Fable is expensive is everywhere now**, a worker above all: output at
$50 and cache writes at $12.50 are the columns a worker lives in. `spawn`
defaults to Opus regardless of the global `model` setting, and `/model fable`
typed by the owner in their own terminal must not leak into the fleet. Override
per worker with `--model` when the criterion below says so.

Same tokenizer across Fable 5.1 and Opus 4.7+, so the context lines (150k/250k
for workers, 150k/250k for the boss) and the 60k/90k cost-per-turn lines need no
re-baselining. The boss's pair was 400k/500k until 2026-11-15.

**Effort: `medium` on the boss and on every worker**, pinned by
`boss-start` and by `spawn`. Claude Code's default is `high` on every model
except Opus 4.7, so a global `effortLevel` would otherwise decide it. The boss
ran at `xhigh` until 2026-10-20 on the argument that its turns are
cache-read-dominated; that holds for token counts, not dollars: on six measured
boss sessions, output (thinking included) was 17-30% of the cost. It ran at
`high` from then until 2026-11-15, when the owner set it to `medium` with the
move to Opus 5.5. Workers, Opus and Sonnet
alike, run at `medium` (the owner, 2026-10-20; `xhigh` from 2026-09-08): a
worker lives in the output columns, and its work is checked by the boss and
the review chain. `BOSS_WORKER_EFFORT` overrides it for the machine. `max` was
not chosen anywhere: the docs describe it as prone to overthinking with
diminishing returns, and it cannot be set in settings.

---

`spawn` takes `--model <name>` (e.g. `--model haiku`, `--model sonnet`). The model
is stamped on the pane as `@worker_model`, so `list` shows it and `restart` keeps
it — a worker silently downgraded on restart is worse than one that was never
downgraded.

**The criterion is not how hard the task looks. It is who can tell whether the
output is right.**

| Cheaper model | Full model |
|---|---|
| Someone else already specified the work completely | The worker is the one who has to notice the defect |
| The output is checkable by a rule that already exists | The only person who can tell it is wrong is the person producing it |
| Failure is loud — it crashes, or a test goes red | Failure is silent and looks like success |
| Rendering from a frozen list, clearing lint, writing a systemd unit, transcription, moving files, wiring a UI to a known schema | Designing a measurement, auditing a corpus, deciding what a null result authorises, anything whose deliverable is a judgement |

**The trap: tasks look mechanical before you do them, and the expensive failures
live inside the ones that looked easy.** "Measure events per second" looked
mechanical and hid a measurer that ignored 46% of the corpus. "Write a dataset
lock" looked mechanical and produced a lock that froze the anomaly it existed to
catch. Both ran, passed their tests, and were wrong in a direction that flattered
the hypothesis.

The practical test before downgrading: **write down how you would catch it if this
worker got it subtly wrong.** If the answer is a command, a test, or another
worker's review, go cheap. If the answer is "I would have to redo the work",
don't — you are not buying a cheap task, you are buying an unverifiable one.

**Never downgrade a worker mid-track.** Context and standard are continuous; a
track that has been finding defects for hours will stop finding them, and the
stopping is invisible.

## The mechanical lane — where the saving actually is

The model criterion answers *which model runs the worker*. It is not the main
saving, and downgrading a judgment worker to buy tokens is the one economy that
hides its own cost.

**The saving is inside the worker's task, not in the worker.** Most tracks are a
thin layer of judgment over a thick layer of mechanical steps: rendering six PDFs,
grepping a field across 1717 files, counting occurrences per group, `systemctl
is-enabled`, assembling a table. Those are verifiable by looking at them, so a
wrong answer is caught by the person who asked.

**Keep the judgment worker on the capable model, and tell it to delegate its own
mechanical steps to cheap subagents.** Put it in the dispatch, because a worker
will not think of it:

> Use a cheap subagent for the mechanical parts — greps, counts, renders, file
> censuses. Keep for yourself only the steps where a plausible-looking wrong
> answer would pass.

Spawning a whole cheap **worker** (`--model haiku`) is right only for a track that
is mechanical end to end and whose output someone else checks.

## Bursts — when a worker runs helpers in parallel (2026-10-05, 2026-10-21)

A worker can spend one ticket running parallel helpers: a **burst**. The
worker decides, not you; it is the one that has read the code and can tell
whether the angles are really separate. You only put the criteria and the
ceiling in the dispatch (Phase B).

**Background subagents by default.** They load MCP tools and can call any skill,
but start without Claude Code's full system prompt, cost less than agent-teams
teammates (Anthropic's agent-teams guide: "Lower: results summarized back to main
context"), and need no setting. A subagent that edits gets its own worktree
(`isolation: "worktree"`). **Agent-teams teammates only when the parts must talk**
— hypotheses that should try to disprove each other — and only where
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.

A ticket is worth a burst when its parts can be worked **without talking and
without touching the same files**: a review along separate lenses (security,
performance, tests), a bug with competing hypotheses that should try to disprove
each other, a research question with independent angles. Anything sequential,
anything editing one set of files, stays a single session: two helpers on one
file overwrite each other.

**Start with 3 helpers, at most 5.** Anthropic's guide: "Start with 3-5 teammates
for most workflows" — and "three focused teammates often outperform five
scattered ones", often, not always. Every helper's report lands in the worker's
context, so a burst spends the worker's 150k `CTX-SPLIT` budget, not a separate
one; that, not the count, is what caps a burst.

Never the boss. A teammate lives inside its lead's process, has no pane and no
stamp, and dies with it; a boss's teammates would be invisible to `list --mine`,
the pulse and the workers watch. `boss-start` turns agent teams off for the boss,
and the guard names any teammate spawn a bare-`claude` boss makes.

## What does and does not save tokens

- **Retiring an idle session saves nothing.** An idle session costs nothing until
  it takes a turn. Retiring reduces clutter, not spend, and destroys context.
- **Recycling an old ACTIVE session saves a great deal**, because cost per turn
  scales with accumulated context. See the recycling rule in the core skill.
- **The boss's own message length** is usually a bigger line item than model
  choice.
- **A broadcast is the most expensive thing you can do.** See the core skill.
