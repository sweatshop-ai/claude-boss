# Codex plan review 1 of tickets 04, 10 and 11 (PR 106)

Review by Codex (gpt-5.6-sol, read-only sandbox), run 2026-11-12 by Otilia on head bf3f45b (main 7535db9) with the brief `brief-1.md`. Codex read the working directory at that head, i.e. before PR 116 (ticket 09c, merge 08dfd71) was merged in. The first run (exit 7) was a usage-limit message and the second stalled at 540 s (exit 6); the third answered. The verdict and its 13 findings are below, verbatim.

## Findings (Codex, verbatim)

NO-GO

1. [P1] The post-merge check reads `state` but never requires `MERGED`. `gh pr merge` may return successfully while leaving an open/queued PR, which would incorrectly exit 0. Require `state == "MERGED"`; otherwise exit 5 as `unverified` and alert. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:14`

2. [P1] Crash recovery recognizes only a “posted” Codex NO-GO, while the preceding box treats both `posted` and `post-failed` NO-GOs as actionable. A crash after a `post-failed` round but before blocker creation causes a second review. Resume from the highest `posted` or `post-failed` Codex NO-GO above the entry and add that crash test. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:17` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:18`

3. [P1] The blocker text describes obsolete `add_line` behavior: cleared markers are deliberately ignored, so retrying the same round after its blocker was cleared adds another blocker and alert, contradicting the promised idempotency. Use a round-event write that treats any occurrence of that exact per-round ID—including cleared—as handled; retain per-round IDs so later NO-GO rounds remain distinct. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:18` `skills/boss/tracker.py:417` `skills/boss/tracker.py:422`

4. [P1] The post-merge removal is not specified as a compare-and-remove operation. If the provisional line is replaced between the snapshot and removal, deleting by PR tag can erase the newer entry; a failed blocker write could also lose the only release stop. Require one `tracker.update` that removes only the exact `ProvEntry` originally read, and only after blocker creation returned `done` or durable same-round evidence was found. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:17` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:18`

5. [P1] The bad-record rule omits `repo`, `pr`, and `base` from its required-field list even though the same paragraph immediately reads them. Implementations can therefore crash or disagree on missing fields. List all eight consumed fields and add missing-`repo`, missing-`pr`, and missing-`base` rows, including exact integer checks for `pr` and `round`. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18`

6. [P1] The `boss-run` regex is both over- and under-inclusive. Bare `pulls/[0-9]+/merge` refuses the non-mutating default-GET “is merged” API call, while `gh pr --repo o/r merge 5` places a valid global option after `pr` and misses the `pr + merge` alternative. Scope the REST rule to PUT and allow global options on both sides of `pr`; test both commands. `.scratch/codex-down/issues/11-gate-enforcement.md:17`

7. [P2] The walk contradicts “a codex GO … is not bound by this box.” With Codex GO round 1, provisional GO round 2, and any round 3, the descending walk stops at round 2 with `superseded-go` and never reaches the Codex GO. State explicitly whether this fail-closed precedence is intended and add the row; ticket 11’s earlier-GO call must follow the same decision. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:20` `.scratch/codex-down/issues/11-gate-enforcement.md:13`

8. [P2] The 4,301-digit filename test cannot be constructed on the target filesystem; ticket 25 explicitly records that filename limits prevent `int()` from seeing it. Remove that disk test and claim. Keep the `RecursionError` row and, if desired, unit-test a filename parser directly with synthetic input. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18` `.scratch/codex-down/issues/25-prune-provisional-edge-cases.md:9`

9. [P2] Ticket 10 calls `usable_tracker(T)` after ticket 26 added the `verb` parameter. The call remains signature-valid, and mapping `None` to exit 2 is correct, but it emits the misleading default “no blocker can be raised.” Specify an appropriate verb and test the exit-2 diagnostic. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:17` `skills/boss/codex_blocker.py:81`

10. [P2] Several refreshed line citations are stale. In 04, `_keep_and_post` is 1237, `_post` is 260, and `_codex_rounds` starts at 1109 with its ownership check at 1135. In 10, `prune_provisional`, `provisional_entries`, `_live_state`, `review`, `_keep_and_post`, and `render_marker` are now 1185, 1008, 1142, 1291, 1237, and 207. Update the cited refresh SHA and all these references. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:5` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:14` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:5` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:13` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:18`

11. [P2] Ticket 04 contains the highest-numbered-round acceptance box twice, verbatim. Delete one copy so implementation and test accounting remain unambiguous. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:20` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:22`

12. [P2] Tickets 10 and 11 are too large for one implementation session. Cut 10 after the recheck/post-merge core, moving `--list`, release stopping, and SKILL activation to a follow-up. Cut 11 by moving `--test-only-since` into its own gate-extension ticket, leaving the hard rule and final SKILL text together. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:24` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:28` `.scratch/codex-down/issues/11-gate-enforcement.md:13` `.scratch/codex-down/issues/11-gate-enforcement.md:17`

13. [P2] The no-`head_sha` conclusion is operationally sound only for a PR already in `MERGED`: it cannot be reopened, and later pushes or force-pushes to the former source branch do not retarget the historical merged-PR head. The verified pull-ref fetch plus detached worktree therefore satisfies `_prepare`, `_keep_and_post`, and the reviews-directory check. Replace the single-PR observation with that scoped invariant; no parameter needs to return. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:13`

NO-GO

## Settled (Otilia, after merging main 08dfd71)

Line numbers below are for `main` 08dfd71, which moved them again after Codex read the text (PR 116 added code to `boss_review.py` and `codex_blocker.py`).

| # | Finding | Settled | Where |
|---|---|---|---|
| 1 | Post-merge check never requires `MERGED` | Accepted. Exit 5, reason `not-merged`, alert; test with state `OPEN` after a `gh pr merge` that returned 0 | 04 |
| 2 | Crash resume counts only `posted` NO-GO | Accepted. Resume from the highest `codex` round with status `posted` or `post-failed`; test row added | 10 |
| 3 | `add_line` text obsolete (cleared lines are ignored) | Accepted. Per-round id kept; the recheck itself treats any occurrence of the exact id, cleared or not, as handled before it calls `add_line`; tests: a retry after `mark_cleared` adds no line and no alert | 10 |
| 4 | Removal is not compare-and-remove | Accepted. One `tracker.update` removing the exact `ProvEntry` line read, only after the blocker write answered `done`/`done (already there)` or the id was found; a failed write leaves the entry; tests added | 10 |
| 5 | Bad-record field list omits `repo`, `pr`, `base` | Accepted. All eight fields listed, exact-integer check for `round` and `pr`, test rows added | 04 |
| 6 | `boss-run` regex over- and under-inclusive | Accepted. Repo option allowed on both sides of `pr`; the REST rule needs `PUT`; tests: `gh pr --repo o/r merge 5` refused, default-GET `.../pulls/5/merge` and `gh pr comment ... 'merge when green'` allowed | 11 |
| 7 | Walk contradicts "a Codex GO is not bound by this box" | Accepted as written by Codex's own alternative: the fail-closed precedence is intended and stated; row added; 11's earlier-GO call follows it | 04, 11 |
| 8 | 4,301-digit file name cannot be created | Accepted. Disk test removed; the name parser is tested with a synthetic string; the `RecursionError` row stays | 04 |
| 9 | `usable_tracker(T)` misleading default diagnostic | Accepted. `usable_tracker(T, "rechecked")`, stderr read in a test | 10 |
| 10 | Stale line citations | Accepted, redone against 08dfd71 (not Codex's numbers: PR 116 moved them again). `_keep_and_post` 1248, `_post` 271, `default_alert` 80, `_codex_rounds` 1120 (ownership check 1135), `prune_provisional` 1196, `provisional_entries` 1019, `_live_state` 1153, `review` 1302, `_prepare` 934, `render_marker` 207, `repo_key` 101, `_reviews_dir` 663, SKILL.md Phase E 1091, `boss_merge.py` sentence 675, the P14 paragraph 840-849. The "two sentences" about `boss_merge.py` in SKILL.md is now one (the :612 one is gone) | 04, 10, 11 |
| 11 | Duplicate acceptance box in 04 | Accepted. The verbatim copy is deleted | 04 |
| 12 | 10 and 11 too big for one session | **Not done: proposal to Chiara.** 10: cut after the recheck and post-merge core; `--list`, the release stop and the SKILL.md activation go to a follow-up. 11: `--test-only-since` becomes its own ticket, the hard rule and the final SKILL.md text stay together. Chiara decides; the tickets are unsplit in this PR | none |
| 13 | `head_sha` drop right only for a `MERGED` PR | Accepted. Parameter stays dropped; the invariant is scoped to a PR read as `MERGED` | 10 |

Also done in this round, from Chiara's message after the Codex run: PR 116 (ticket 09c, merge 08dfd71) merged into the branch with no conflict; 09c's three waiver boxes ticked as done by PR 116; 04's text now cites what 09c built (`boss_review.py --waive`, `consent.py`, the `waived` round kind). Codex did not read the merge of PR 116; its changes to 04, 10 and 11 are the citation updates above and the 09c wording.

Codex's answer to the head_sha question (brief question 2) and to the "does 10 fit one session" question (finding 12) are the two the handoff asked for: `head_sha` stays dropped; 10 does not fit one session by Codex's reading and the cut is proposed above.
