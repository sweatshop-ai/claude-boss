# Plan: keep the PR gate working when Codex is down

Agreed with the owner on 2026-10-03.

## Problem

Every PR in a boss-run team merges only on a Codex GO for the exact head being merged
(`skills/boss/SKILL.md`, the Codex review section). `boss-run` already falls back from
Codex to Haiku and fails closed, but the PR gate has no fallback and no outage rule: a
worker types `codex exec` by hand. When Codex is down, every merge stops, and nothing tells
the boss whether to wait, retry or escalate. That is the silent stall the plugin's hooks
exist to prevent.

## Decisions

1. **Labelled fallback reviewer.** When Codex does not answer, the PR is reviewed by
   **Claude Opus, read-only**. Only `codex` and `claude` are installed, so the fallback is
   the same family as the Claude workers; the label and decision 2 make up for that. Its
   verdict is posted as "Fallback review (Codex unavailable)" and counts as a
   **provisional GO**: enough to merge where nothing deploys, never on a branch that
   deploys.
2. **Codex re-runs before deploy.** When Codex answers again, every PR holding only a
   provisional GO gets a Codex review on its current head. A NO-GO on a merged PR becomes
   a dispatched fix.
3. **A dead reviewer is an open blocker.** After N consecutive failed reviews (N in the
   policy module), the tracker gets a "Codex down" open blocker with a ladder marker. It
   escalates on the normal rungs and reaches the owner once through `AskUserQuestion`:
   wait, accept the fallback review, or merge on tests alone. It clears on the next
   successful Codex answer.

## Approach

Prefactor first: the reviewer chain moves out of `boss-run` into one shared module. Then
the PR review becomes a command, so an outage passes through one place that can see and
count it. The fallback, the re-run and the blocker build on that.

## Out of scope

- Adding another model family (Gemini, OpenCode). Revisit if one gets installed.
- Sandcastle-style batch merging by a merger agent. Discussed, not decided.

Tickets: `/home/tiroir/Projects/boss-plugin/.scratch/codex-down/issues/` (01–05).
