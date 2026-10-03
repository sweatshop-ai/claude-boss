# Codex review 5 of the codex-down plan (structure of tickets 02 to 11, and ticket 02 in full)

Run by Fabio (task #100, restarted after Birgit's handoff), 2026-10-04 01:09-01:15 (+02:00). Reviewer: Codex (`codex exec -s read-only --skip-git-repo-check`,
model `gpt-5.6-sol`, reasoning effort high), stdin closed, working directory the checkout root, brief `brief-codex-5.md`
(`brief-codex-4.md` plus a round-5 paragraph: check that round 4's fixes landed and hold, and look for what they broke).
Answered after about 6 minutes; foreground command with `run_in_background: true`, activity confirmed in the first minute.

Reviewed at commit `9f2dc53` (main). Scope as in round 4: the structure and ticket 02 in full.

**Verdict: NO-GO**, 3 findings (1 on the R1 row, 2 and 3 on ticket 02). Codex raised nothing on the Blocked-by graph, the
other coverage rows, the residual-risk rows, ticket sizes or the privacy check, and did not reopen any round-4 finding.

The checkout path prefix is not in the links below; Codex's text is unchanged.

## Codex's answer, verbatim

NO-GO

1. The round-4 R1 fix is incomplete: coverage admits the controlling goal still pauses only before 03, while the plan says the track pauses until 08. Change the goal threshold to 08 and make the coverage status unconditional, or mark R1 pending and make the plan agree. `.scratch/codex-down/coverage.md:9` `.scratch/codex-down/plan.md:46`

2. Repository identity is compared case-insensitively, but the storage path and per-PR lock use the supplied `<owner>/<repo>` spelling. Concurrent reviews using `Owner/Repo` and `owner/repo` can therefore claim separate `round01` files and post duplicate round numbers, so R6 is not covered. Define one canonical repository key for paths, locks, records and logs, and add a concurrent casing-variant test. `.scratch/codex-down/issues/02-pr-review-command.md:18` `.scratch/codex-down/issues/02-pr-review-command.md:23` `.scratch/codex-down/issues/02-pr-review-command.md:27` `.scratch/codex-down/coverage.md:14`

3. The claimed-round failure contract remains incomplete. The file is claimed before the attempts append and `.out` write, but failures of either operation have no defined `status`; the `ReviewResult` contract nevertheless requires the claimed round’s status, and the closing box requires tests to assert it. Final-JSON failure likewise leaves an empty record without defining the returned status. Add an explicit non-posted infrastructure status and its gate behavior, or specify exactly which failures leave an empty record and allow `status=None` with a non-null round/path; update every affected test expectation. `.scratch/codex-down/issues/02-pr-review-command.md:14` `.scratch/codex-down/issues/02-pr-review-command.md:27` `.scratch/codex-down/issues/02-pr-review-command.md:28` `.scratch/codex-down/issues/02-pr-review-command.md:32`

## Citation check

Each `file:line` Codex gave was printed from the files at `9f2dc53` (`git show 9f2dc53:<path>`) and read against the
finding that cites it. All 10 hold the text the finding describes at that line. Nothing cited is fabricated.

| Finding | Citation | Mark |
|---|---|---|
| 1 | .scratch/codex-down/coverage.md:9 | VERIFIED |
| 1 | .scratch/codex-down/plan.md:46 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:18 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:23 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:27 | VERIFIED |
| 2 | .scratch/codex-down/coverage.md:14 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:14 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:27 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:28 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:32 | VERIFIED |

## Disposition (Fabio)

| # | Verdict | What was done |
|---|---|---|
| 1 | Right, in part | The goal file's "Pause when" line is the boss's file and still says 03 (checked at 01:20); a ticket cannot change it. `coverage.md` R1 is now stated as pending: not covered until that line says 08, no box can cover it. `plan.md` says the pause lives in that line, which must say 08, and that R1 is open in `coverage.md` until it does. The boss has been asked twice (interim message, final report). When the line says 08 the row becomes unconditional |
| 2 | Real | 02: one function, `repo_key(repo)` (`<owner>/<repo>` lowercased), gives the key for the directory name, the per-PR lock, the `repo` value in `round<NN>.json`, `attempts.jsonl` and `merges.jsonl`, and 06's entry tag; `gh` calls carry the spelling given. 04, 06 and 10 call it and never build a path from `--repo` as typed. 02's tests add two concurrent runs given as `Owner/Repo` and `owner/repo`: one directory, two different round numbers |
| 3 | Real | 02: the failure contract is exact. A failed `gh pr view` or a failed claim claims nothing (`round`, `status`, `record` are `None`). A failure after the claim, in the attempts append, the `.out` write or the final write, leaves the claimed file empty (04: `bad-record`, superseded by the next round); the result has `status` `None` with `round` and `record` naming the file. No new status value, so 04's list of known statuses is unchanged. The `ReviewResult` text and every affected test expectation say so |

Fix commit: 0853b63
