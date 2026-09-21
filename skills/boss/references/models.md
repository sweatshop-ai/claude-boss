# Choosing a worker's model, and where the cheap model belongs

## Which model runs the boss (2026-09-08)

The boss runs on **Fable 5.1**; workers default to **Opus 5**. `boss-start`
sets the first, `boss-lifecycle.sh spawn` the second.

Apply the criterion below to the boss itself. Its deliverable is a judgement:
whether a worker's "zero found" counted the right unit, whether a plan collides
with another worker, whether the 26% asymmetry mentioned in passing is the real
finding. Nobody checks the boss's reading of a report; if it misses the defect,
the defect ships. That is the right-hand column. A worker's failure is loud by
comparison — tests, CI, the boss's own review — which is the left-hand column,
and Opus is the full model there.

**The cost argument is weaker than it looks, in both directions.** List prices
(platform.claude.com/docs/en/about-claude/pricing, read 2026-09-08):

| | input | cache write 5m | cache read | output |
|---|---:|---:|---:|---:|
| Fable 5.1 | $10 | $12.50 | **$0.25** | $50 |
| Opus 5 | $5 | $6.25 | $0.50 | $25 |

Fable is 2× Opus on every column except cache reads, where it is half — a
0.025× multiplier instead of 0.1×. The 2026-08-30 audit measured cache reads at
97–99% of a boss's context in every band. At a typical boss turn (300k context:
97% cache read, 2% cache write, 1% fresh, 1.5k output) that comes to about
$0.24 on Opus and $0.25 on Fable. The boss on Fable is not the expensive choice;
it is close to free relative to Opus, because a boss mostly re-reads.

**Where Fable is expensive is a worker.** A worker writes: code, diffs, long
tool output re-read once. Output at $50 instead of $25 and cache writes at
$12.50 instead of $6.25 are the columns a worker lives in. That is why `spawn`
defaults to Opus regardless of the global `model` setting, and why `/model
fable` typed by the owner in their own terminal must not leak into the fleet.
Override per worker with `--model` when the criterion below says so.

Same tokenizer across Fable 5.1 and Opus 4.7+, so the 400k/500k context lines
and the 60k/90k cost-per-turn lines need no re-baselining.

**Effort: `xhigh` on both**, pinned by `boss-start` and by `spawn`. Claude
Code's default is `high` on every model except Opus 4.7, so a global
`effortLevel: high` changes nothing. the owner's instruction (2026-09-08) is that
the result comes before the spend; `xhigh` is Anthropic's recommended setting
for agentic coding on this tier, and on the boss the extra thinking is output
tokens on top of a cache-read-dominated turn — the one place more tokens buy
judgement cheaply. `max` was not chosen: the docs describe it as prone to
overthinking with diminishing returns, and it cannot be set in settings.

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

## What does and does not save tokens

- **Retiring an idle session saves nothing.** An idle session costs nothing until
  it takes a turn. Retiring reduces clutter, not spend, and destroys context.
- **Recycling an old ACTIVE session saves a great deal**, because cost per turn
  scales with accumulated context. See the recycling rule in the core skill.
- **The boss's own message length** is usually a bigger line item than model
  choice.
- **A broadcast is the most expensive thing you can do.** See the core skill.
