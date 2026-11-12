# Spec round 1 of ticket 06 (provisional GOs tracked in a durable list)

Run by Lucia (task #06S of the codex-down track), 2026-11-12, against main c0a25e7 (PR 96 merged). **Codex was out of tokens** (`codex-review.sh exec` exited 7, "out of tokens until 3:01 PM"; brief `06-spec-reviews/brief-1.md`, stderr `round-1.stderr` beside it, in the worktree directory next to the spec worktree). The round is therefore the **labelled Opus fallback** (a fresh read-only Opus agent, same brief), not Codex: Codex owes a follow-up spec review of the settled ticket after 15:01. Verdict: **NO-GO**, 11 findings (1 P1, 5 P2, 5 P3). Every file:line the ticket cites was VERIFIED except the then-missing `plan-review-codex-06-1.md` (this file).

## Smoke check

Owed before 06 switches the fallback on. Run 2026-11-12 from a worktree of origin/main c0a25e7: `python3 skills/boss/boss_review.py --check-fallback --checkout <throwaway git checkout whose .claude/settings.json holds a SessionStart hook touching a marker file>`. Output: `fallback check passed: tools Glob, Grep, Read; permission mode dontAsk; model claude-opus-5-5; no MCP servers, no slash commands, no hooks, no plugins but claude's own`. Exit code 0. The marker file did not exist afterwards.

## Findings

1. P1: SKILL.md :631-633 (pinned by `test_skill_text.py` :21-26) and :621 still send a worker with no usable track to run the fallback by hand, producing a provisional GO the list does not know.
2. P2: the removal rule contradicts itself on an unreadable PR state (rule 1 needs no state; the text says unreadable keeps).
3. P2: rule 2 has no ordering condition, so an older Codex GO removes a newer provisional entry when the live head is the entry's head.
4. P2: a CLOSED unmerged PR keeps its entry forever; 10's release stop never lifts.
5. P2: the "unwritable tracker" test does not fail `update` (a 0444 file is replaced via a temp file); a read-back-fails case is missing.
6. P2: no deadline for the tracker write; the ladder holds the lock across `boss-alert` calls.
7. P3: `_keep_and_post` has no `track` parameter and the ticket does not add one.
8. P3: section text under-specified (CRLF section creation, hand appends landing in the section, exact line form).
9. P3: line 27 overstates what `update` turns into `failed`.
10. P3: stale docstrings and test name; who prints the "needs a track" message; `usable_tracker` call inside the `ValueError` try.
11. P3: too big for one session; cut 06a (list write, no-track-no-fallback, `main()`, SKILL.md) / 06b (`prune_provisional` and its rows).

Checked and no defect: lock order PR lock then tracker lock; `list-failed` (04 :18 already lists it, `codex_health` ignores rounds); no test pins the `main()` print or `--help`; 10's use of `prune_provisional(track, repo)` fits; no private names in the ticket.

## Settled

| # | Disposition | Where |
|---|---|---|
| 1 | Accepted. The replacement says a PR's fallback is never run by hand; the pinned sentence is reworded to plan reviews only, its pin moves, and :621 gains `--track T`. | 06, third box |
| 2 | Accepted. An unreadable state keeps the entry under every rule, rule 1 included; test row added. | 06, removal box |
| 3 | Accepted. Rule 2 applies only when the live head differs from the entry's `head=`; test row added. | 06, removal box |
| 4 | Accepted. Rule 3: a CLOSED unmerged PR loses its entry; test row. | 06, removal box |
| 5 | Accepted. Three ways to fail `update` named; the 0444 trap stated; the read-back-fails case added. | 06, tests box |
| 6 | Accepted. Deadline `time.monotonic() + policy.REVIEW_IO_TIMEOUT` (60 s), with the reason. | 06, list box |
| 7 | Accepted. `_keep_and_post` gains the tracker path as a keyword parameter; `_Job` stays without a track. | 06, list box |
| 8 | Accepted. `fn` matches the exact line form only; section creation keeps the file's line ending; hand appends are named. | 06, list box |
| 9 | Accepted. Text now matches `update`. | 06, removal box |
| 10 | Accepted. Stale text listed; `review()` says the message once; `main()` calls `usable_tracker` inside its `ValueError` try. | 06, list box |
| 11 | Accepted on Chiara's ruling (2026-11-12): 06 is an index; 06a holds the list write, `list-failed`, no track no fallback, the `main()` switch, SKILL.md and the tests (five boxes); 06b holds `prune_provisional` with the removal rows of the old Tests box (one box). Six boxes before, six after. Ticket 10 is blocked by 06b. | 06, 06a, 06b, 10, coverage.md, plan.md |

## Round 2 (on the split: 06a and 06b)

Run by Lucia, 2026-11-12 after 15:02. **Codex stalled** (`codex-review.sh exec` exit 6, "stalled past 540s", no output; brief `brief-2.md`), so again the **labelled Opus fallback** (fresh read-only Opus agent, same brief); Codex still owes a spec review of 06a and 06b. Verdict **NO-GO**, 11 findings (1 P2, 10 P3). Brief question 1: the cut is clean but for one clause (finding 2); box count six before and after (five in 06a, one in 06b), every clause of the old Tests box in exactly one place; 10 is correctly blocked by 06b. Brief question 2: findings 1 to 6 of round 1 are closed in text and, checked against code, in fact (F5: a 0500 `pm/` makes `mkstemp` fail at tracker.py:334, a 0444 file does not).

| # | Finding | Disposition |
|---|---|---|
| 1 | P2: one entry per PR; a provisional GO on an older head (force-push back, reopened CLOSED PR, replaced entry) can merge or be rechecked at the wrong commit (R17). | **Deferred to ticket 22, not applied to 06.** It changes 04's gate rule (a provisional or waived GO decides only when it is the PR's highest-numbered posted round) and 10's recheck (a merged PR is reviewed at its merged `headRefOid`); both are other tickets' scope, and a keep-the-entry rule here would not close case A. 22 holds the three cases and the two fixes; 06b's rule 3 stays as written. |
| 2 | P3: 06a's `fn` rule left only in 06b. | Accepted: the clause is in 06a's list box; 06b names its caller (`boss_recheck`). |
| 3 | P3: who prints the "needs a track" message. | Accepted: `main()` passes `allow_fallback=args.track is not None`; `review()` alone resolves and says it. |
| 4 | P3: deadline ignores `io_timeout`. | Accepted: `job.io_timeout`. |
| 5 | P3: who creates the section. | Accepted: `fn`. |
| 6 | P3: empty or unreadable round file. | Accepted: skipped, entry kept. |
| 7 | P3: the index would show as ready work. | Accepted: status "index only". |
| 8 | P3: home path in this file. | Accepted: removed above. |
| 9 | P3: two imprecise citations. | Accepted: `kind` :76, `SENTENCE` :21-23. |
| 10 | P3: "never run by hand" vs the plan's PR line. | Accepted: "a PR head's fallback review". |
| 11 | P3: no tracker path in `_keep_and_post`. | Accepted: `list-failed`, exit 7. |
