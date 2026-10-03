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
   deploys. The skill's two absolute merge sentences ("every PR gets a Codex review on the
   head that merges", "No PR merges without a GO on record") are replaced by one rule with
   three cases, not added to.
2. **Codex re-runs before deploy.** When Codex answers again, every PR holding only a
   provisional GO gets a Codex review on the head that was reviewed (an open PR) or merged
   (a merged PR, reviewed in a detached worktree). A NO-GO on a merged PR becomes a
   dispatched fix, or an open blocker when no author session can take it. The list of
   those PRs lives in the tracker, and a release or wrap-up stops while it is not empty.
3. **A dead reviewer is an open blocker.** After N consecutive failed Codex attempts (N in
   the policy module, counted from the attempts log even when the fallback answered), the
   tracker gets a "Codex down" open blocker with a ladder marker. It escalates on the
   normal rungs and reaches the owner once through `AskUserQuestion`: wait, accept the
   fallback review, or merge on tests alone. "Merge on tests alone" is never on a branch
   that deploys. The blocker clears after M consecutive Codex answers (M in the policy
   module, at least 2), so one answer amid failures does not clear it.
4. **One merge path.** `boss_merge.py` is the merge command the skill names. It checks the
   review record and the repo's own `.boss/deploy.json` (read from the base branch, failing
   closed: a branch is non-deploying only if listed) and refuses a provisional or waived
   GO on any branch not listed. `boss-run` refuses a hand-typed `gh pr merge`. A merge
   typed by hand in a shell is outside the gate; only branch protection closes that.

## Approach

Prefactor first: the reviewer chain moves out of `boss-run` into one shared module. Then
the PR review becomes a command, so an outage passes through one place that can see and
count it. The fallback, the merge gate, the re-run and the blocker build on that. Until 08 lands there is no fallback and no outage rule, so the track pauses if Codex is down before then and a PR waits on it (premortem R1; the goal file's "Pause when" line).

Build order: 01, 02, then 07 (the brief and the comment) and 03 (the fallback's confinement) side by side, 08 (the fallback review; it needs both), 05 (the health state, the tracker writer and the blocker; blocked by 02 and 08 because the owner's option "accept the fallback review" does not exist before 08), then 09 (the owner's choice and the waiver) and 06 (the provisional list) side by side, then 04 (the gate, which tests against 08's and 09's real records) and 10 (the recheck and the release stop) side by side, and last 11 (the test-only exception, the `boss-run` hard rule and the skill text). In ticket numbers: 01, 02, {07, 03}, 08, 05, {09, 06}, {04, 10}, 11.

## Out of scope

- Adding another model family (Gemini, OpenCode). Revisit if one gets installed.
- Sandcastle-style batch merging by a merger agent. Discussed, not decided.

Tickets: `.scratch/codex-down/issues/` (01-11). The old ticket 04 was split on 2026-10-04: 04 is the merge gate, 06 the provisional list and the recovery. After Codex review 3 of the plan the same day, 02, 03, 04, 05 and 06 were split again into 07 (the review brief and the comment), 08 (the fallback review), 11 (the gate's test-only exception, hard rule and skill text), 09 (the owner's choice and the waiver) and 10 (the recheck and the release stop). `coverage.md` maps every premortem risk and the findings that matter to a ticket box and lists the residual risks.
