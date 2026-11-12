# Spec round 2 of ticket 05 (split into 05a, 05b, 05c)

Run by Joaquin (task #05X of the codex-down track), 2026-11-12. **Codex reviewed:** `codex-review.sh exec` returned an answer (no stall); brief and output in `05-spec-reviews/brief-05-2.md` and `round-2.md`, kept outside the repo. Reviewed: `issues/05a-tracker-writer.md`, `05b-policy-and-codex-health.md`, `05c-raise-and-clear-the-blocker.md`, the index `05-dead-reviewer-blocker.md`, and the citations in 04, 06, 09, 10, 13, `coverage.md` and `plan.md`, against main baf0e93. Verdict: **NO-GO**, 8 findings (6 P1, 2 P2). The split itself drew no finding except 7 (the 05b to 05a edge); no box is lost (8 before, 8 after), no citation is wrong. The 6 P1s are in the box text: two are tests that round 1's Settled table said were added and were not (2, 3).

## Codex's findings

1. [P1] `health()` returns the last failure's `repo` and `pr` and counts distinct `repo#pr`, but lines with a missing or invalid `repo` or `pr` still counted. (05b, box "codex_health")
2. [P1] A naive `when` (05a) and a naive `now` (05c) are `ValueError`s by the text but have no test; round 1's settlement promised one each.
3. [P1] The hand-cleared, shorter-streak test (round 1, finding 3) is not in 05c's tests; code that raises on `state == "down"` alone would pass.
4. [P1] "Broken" covers `scan_marker` only; the ladder also calls `validate`. A parseable-but-invalid marker could be cleared and alerted while the ladder still reports it; a valid line cleared beside a broken one could post a `clear`.
5. [P1] The id has second resolution; two outages in one second (an injected `now`) give duplicate ids.
6. [P1] `findings_block` raising `OSError` after a parsed chain answer returns `_failed` before `_keep_and_post` and logs nothing (`skills/boss/boss_review.py`, the `try: findings = findings_block(...)` block), so that Codex attempt is uncounted and there is no sync point.
7. [P2] 05b's `Blocked by` 05a is superfluous: 05b writes no tracker. 05c should depend on both.
8. [P2] With `CODEX_DOWN_AFTER = 3`, two processes each appending one failure cannot reach N from an empty log.

## Settled (Joaquin)

| # | Disposition | Where |
|---|---|---|
| 1 | Accepted. A line whose `repo` is not a non-empty string or `pr` not a positive integer (a boolean is not one) is skipped and counted; a test with `repo` missing, `pr` 0 and `pr` true. | 05b, `codex_health` box |
| 2 | Accepted. One test each: naive `when` to `mark_cleared` (file untouched), naive `now` to the raise (nothing written). | 05a, tracker box; 05c, raising box |
| 3 | Accepted. Test: a down state, a blocker cleared by hand, one answer after it: no new line, no `boss-alert`. | 05c, raising box |
| 4 | Accepted. "Broken" is a `cd` line `scan_marker` cannot read or `validate` refuses; `clear` posts only when `update` returned `done` and no open or broken `cd` line remains in the file after the write. Tests: parseable-but-invalid marker; a valid open line beside a broken one with Codex up. | 05c, raising and clearing boxes |
| 5 | Accepted. An id already on any `cd` line, cleared or not, makes the raise add one second to `now` until the id is new, in the same locked step; test: two outages with the same injected `now`. | 05c, raising box |
| 6 | Accepted. That path now appends the chain's attempts with `"round": null` as `_log_refused` does, keeps exit 7, then syncs; test added. This widens 13's NUL-only decision to this one path, in 05c's box and not in 13. | 05c, `track` box |
| 7 | **Declined (Chiara's ruling, 2026-11-12).** The edge 05a to 05b costs nothing, because 05a is blocked by nothing and goes first, and it keeps 05b's tests on one tracker writer. Her dispatch fixed 05b as "blocked by 05a and 08". | 05b, `Blocked by` |
| 8 | Accepted. Three processes (N is 3) append one failure each to an empty log and reach `down` with `failures` 3; two such processes leave it `up` with `failures` 2. | 05b, `codex_health` box |

Not a finding but a consequence of the split, said to Chiara: 06's "No track, no provisional review" box and 10's `track=T` use 05c's `review(..., track=)` box, so 06 is blocked by 05a, 05c and 08, not by 05a alone as the dispatch assumed. 05c's `track` parameter cannot move to 05a: its health sync calls 05b.

Round 3 is owed: the fixes above are mine, and no reviewer has read them.

## Round 3 (labelled Opus fallback, Codex unavailable)

**Opus fallback, Codex unavailable (usage limit; the runner said Codex returns at 3:01 PM; no retry planned, Chiara allowed the fallback for this docs PR on 2026-11-12).** `codex-review.sh exec` exited 7 on the brief `05-spec-reviews/brief-05-3.md`. A fresh Opus agent, read-only, the same brief, reviewed `git diff ae2819b..29ef5e6` for two questions: does each applied disposition close its finding, and is the merge resolution (06 blocked by 05a, 05c, 08, 14) consistent. Its output is `05-spec-reviews/round-3.md`. **Verdict GO**, no P1. Codex has not read these fixes; per the skill it can follow as a ticket-making read after the merge.

A. Findings 1, 2, 3, 4, 5, 6 and 8 of round 2: **all CLOSED**, with the gaps below. B. The merge resolution has no cycle and the letters in 04, 09, 10, 13, the index and `coverage.md` are right.

| # | Finding (round 3) | Disposition | Where |
|---|---|---|---|
| a | [P2] The deferred `clear` alert could never be posted: once the owner deletes the broken line nothing runs the clear box | Fixed by dropping the promise: no alert for that outage, stderr says why, the ladder's malformed-marker report is the notice, no state added; `mark_cleared` is not called on a line `validate` refuses | 05c, clearing box |
| b | [P2] A malformed `cd` line, even one the owner closed by hand with a typo in `cleared=`, held back every later blocker in the track | Fixed: a broken line whose text holds ` cleared=` is not counted as open; test: such a line beside a new outage raises a new blocker | 05c, raising box and its tests |
| c | [P2] `plan.md` left 14 out of 06's blockers | Fixed (14 added to 06's blockers and the order) | `plan.md` |
| d | [P3] The `findings_block` test did not pin exit 7, no round claimed and an empty `gh pr comment` log | Fixed in the test sentence | 05c, `track` box |
| e | [P3] 05a's Blocked-by note said 06 and 10 need only `update` and `add_line` | Fixed: it now says they also wait for 05c | 05a |

Finding 7 of round 2 stays declined, above.
