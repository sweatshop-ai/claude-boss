# Incidents — why some rules in the core skill are stricter than they look

Each rule in the core skill that seems paranoid was bought. This is the receipt.
Nothing here needs reading unless you are wondering why a rule exists, or you are
about to relax one.

## 2026-08-11 — a shared tracker erased a whole track

One boss's entire track state (the Klium A2 section) was silently erased by
another boss's wholesale rewrite of the shared `~/.claude/pm-tracker.md`. No
conflict, no warning, total loss.

**What it bought:** one tracker file per track, claimed at session start rather
than at first write. A conflict found in the first minute is a question; the same
conflict found in the sixtieth is a temptation. And: never regenerate a tracker
wholesale — read before write, always. The loss happened because a boss wrote its
own state without reading what was there.

## 2026-08-28 — a bare tmux format string reported the wrong pane

Three workers self-reported a wrong pane coordinate, two of them returning
`3:0.0` — the boss's own coordinate, not theirs.

Cause: `tmux display-message -p '<format>'` with no target does not resolve from
the caller. It resolves from client and focus state, so the worker reports
**whoever has focus**, which in a multi-boss tmux is routinely the boss's pane.
`$TMUX_PANE` is set by tmux per pane and is trustworthy.

**What it bought:** `-t "$TMUX_PANE"` is load-bearing in any pane self-report.
The bare form is not reliably wrong, which is what makes it dangerous — it
returns the right answer often enough to look correct.

**The general lesson, worth more than the command:** a reading that is wrong in a
plausible direction is worse than an error. An error gets investigated; a
plausible wrong answer gets acted on.

## 2026-08-28 — three names, one session (now structurally impossible)

`ListAgents` showed `Kian [a7c3ab]`; the same session self-reported as
`klium-link-quality-audit [a7c3ab]` and signed every message "Samir". Three names,
one session. A send to `klium-link-quality-audit` bounced while `Kian` succeeded —
the machine reported the collision an hour before the worker did, and it was read
as a lookup quirk.

**What it bought, historically:** reconcile a signature against the `ListAgents`
row before treating two names as two workers; the `[ref]` settles it. And: never
let a corroboration structure rest on names — two workers agreeing is evidence
only if two distinct `[ref]`s produced the figures, or the same session has been
asked twice and returned two answers that look independent and are not.

**Why this is now historical.** The cause was two naming systems: the
`claude-agent-names` plugin named the session, and `boss-lifecycle.sh` kept a
separate `@worker_name` invented from a spawn hint. Since 2026-08-30 the plugin is
the single store — `boss-lifecycle.sh` reads the name from it and mirrors it onto
the pane for the watchdog, and `spawn`/`claim` with a name write *through* the
plugin. The names cannot diverge, so the reconciliation dance is gone.

**The corroboration rule survives on its own merits.** Check the refs before you
call anything replicated, regardless of naming.

## 2026-08-30 — the token audit

15 boss sessions measured. 983 Bash calls of which 35 were the lifecycle script;
413 `cd`, 182 `cat`, 74 `python3`, 39 `npx`, 37 `grep`, 36 `sed`, 11 `git`; 238
Edits, 47 Writes, 64 Reads, of which only 136 file ops touched a tracker; edits to
real source (`telemasterclass/src/lib/agente/i18n.ts`, `klium/scripts/a2-*.py`);
46 Chrome calls; 29 subagent spawns.

Three pages of bold FORBIDDEN prose, and the boss did the work anyway.

**What it bought:** the cardinal rule is now four lines plus a hook that warns and
logs (`boss-guard.py` → `~/.claude/pm/boss-guard.log`), instead of prose that was
long enough to read as background. And the skill was split so that rules which
must fire unprompted stay in the core, while procedure moved here.

The same audit measured the cost of session age: cost per turn rose 3.9× over the
boss's life and 4.7× over a worker's, priced. That is the recycling rule.

Full analysis: `~/.claude/plans/2026-08-30-boss-team-token-audit.md`.

## 2026-09-09 — the boss went quiet and the owner dispatched four workers by hand

At 10:16, `ListAgents` showed six sessions on track `memorizer-r8`: Anselm, Lina,
Tiago and Anika idle, Petra busy, Dmitri in a shell. In every one of the four idle
panes the last prompt was the owner's own, typed directly:
*"mergia la 18"*, *"add those two points to the PR body"*. The boss had merged
four PRs overnight and was still working. It had simply stopped being the thing
that fed the team.

Two causes, both structural, neither a lapse of judgement.

**The objective was not an object.** `boss-tracker init` takes `<track>` and
`<boss-name>`; the mission had been written into the *name* argument, so the
header read `_Boss: Dmitri (12:0.4), started ... Mission: land PR #36 ... , started
2026-09-08._` — with the date printed twice, because the template appended its own.
There was no definition of done anywhere, so nothing could be checked off, nothing
could be finished, and the priority order lived only in the boss's context.

**Nothing armed the events Phase D waited for.** The phase said "event-driven. No
polling loop" and listed *worker goes idle* as a row in its response table. But
`notify_when_idle` appeared **zero times** in the entire skill — the subscription
that produces that event was never armed. Workers reported when they remembered to;
when the owner spoke to the workers in their own panes, they answered the owner and the boss never
learned they were free.

**What it bought:** `boss-goal` — Outcome, Done when, Deliverables, Constraints,
Pause when, Next in priority order, in one 4 KB file per track that the compaction
hook restores and the pulse reads. `notify_when_idle: true` on every dispatch, plus
the reporting contract in the dispatch text. And `boss-pulse.py`, a `Stop` hook: at
the moment the boss would go quiet, if the objective is OPEN and one of its workers
is idle, it hands back the outcome, the unmet criteria and the names, and the turn
continues.

**The general lesson:** an event-driven design is only as good as whatever arms the
events. "No polling loop" was the right instinct and it was implemented as nothing
at all. Silence that is correct by the letter of the design, while four workers sit
idle, is still the failure the design existed to prevent.
