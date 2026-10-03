# Codex review 6 of the codex-down plan (structure of tickets 02 to 11, and ticket 02 in full)

Run by Fabio (task #100, restarted after Birgit's handoff), 2026-10-04 01:16-01:25 (+02:00). Reviewer: Codex (`codex exec -s read-only --skip-git-repo-check`,
model `gpt-5.6-sol`, reasoning effort high), stdin closed, working directory the checkout root, brief `brief-codex-6.md`
(`brief-codex-4.md` plus a round-6 paragraph: check that the fixes of rounds 4 and 5 landed and hold, R1 is stated as pending
on purpose). Answered after about 9 minutes; foreground command with `run_in_background: true`, activity confirmed in the first minute.

Reviewed at commit `e86eb9c` (main). Scope as in round 4: the structure and ticket 02 in full.

**Verdict: NO-GO**, 8 findings (1 to 5 on ticket 02, 6 on the build order, 7 and 8 on coverage rows). Codex did not reopen any
round-4 or round-5 finding and raised nothing on the Blocked-by graph, ticket sizes or the privacy check; it accepted R1 stated as pending.

The checkout path prefix is not in the links below; Codex's text is unchanged.

## Codex's answer, verbatim

NO-GO

1. Repository validation contradicts its own test: the component `..` matches `^[A-Za-z0-9._-]+$`, so `../x` passes the stated rule and `repo_key()` can escape the reviews directory. Explicitly reject `.` and `..` for both repository components and test `../x`, `x/..`, and `./x`. `.scratch/codex-down/issues/02-pr-review-command.md:13`

2. Reviews are not bound to the base they examined. The initial base enters the brief and record, but the under-lock re-read checks only the head, while ticket 04 does not require the record’s `base` to equal the live base. A retargeted PR can therefore merge using a GO produced against another base. Re-read both head and base before posting, define the non-posted base-change outcome, make 04 require an exact live-base match, and test retargeting during and after review. `.scratch/codex-down/issues/02-pr-review-command.md:19` `.scratch/codex-down/issues/02-pr-review-command.md:27` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18`

3. The round-5 `ReviewResult` fix remains incomplete: after an attempts-log, output-file, or final-record failure, `status` is defined as `None` but `verdict` is not defined. Add an outcome table specifying every `ReviewResult` field for each failure and assert `verdict` in the affected tests. `.scratch/codex-down/issues/02-pr-review-command.md:14` `.scratch/codex-down/issues/02-pr-review-command.md:28` `.scratch/codex-down/issues/02-pr-review-command.md:32`

4. The promised write-failure coverage is not hermetic: its permission-based cases explicitly skip when run as the superuser, leaving required branches neither passing nor failing. Replace permission-dependent injection with deterministic injected failures of append, output write, and final rename, with no environment-dependent skip. `.scratch/codex-down/issues/02-pr-review-command.md:32`

5. R9 is not covered at the claimed level. Ticket 02 promises directory mode 0700 and file mode 0600, but its test list contains no permission assertions, including behavior when an existing directory or log is wider. Add explicit mode tests and require existing artifacts to be tightened. `.scratch/codex-down/issues/02-pr-review-command.md:23` `.scratch/codex-down/issues/02-pr-review-command.md:32` `.scratch/codex-down/coverage.md:17`

6. The build order creates provisional GOs that recovery can permanently miss. Ticket 08 explicitly allows unlisted provisional records before 06; ticket 06 only lists newly recorded provisional GOs, and ticket 10 walks that tracker list. Add a durable, track-keyed pending record in 08 that 06 migrates, or prohibit posting provisional results until durable tracking exists and adjust the pause/build contract accordingly. `.scratch/codex-down/issues/08-fallback-review.md:5` `.scratch/codex-down/issues/06-provisional-recovery.md:13` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:17` `.scratch/codex-down/coverage.md:27`

7. The R6 mapping was not updated for the round-5 casing fix. Its cited box covers claim order but not the canonical repository key or casing-variant concurrency test that now makes the “covered” status true. Add the exact first words of ticket 02’s command box and closing test box to that row. `.scratch/codex-down/coverage.md:14` `.scratch/codex-down/issues/02-pr-review-command.md:13` `.scratch/codex-down/issues/02-pr-review-command.md:32`

8. Three coverage entries do not identify ticket boxes by their first words as the table promises: R12 cites “the closed reason set,” R13 cites `Attempt.model`, and R15 cites “the command.” Replace them with the actual box openings: “Each attempt carries a reason…”, “The result records the exact model id…”, and “`boss_merge.py --repo OWNER/REPO --pr N [--dry-run]` is the one merge path…”. `.scratch/codex-down/coverage.md:20` `.scratch/codex-down/coverage.md:21` `.scratch/codex-down/coverage.md:23` `.scratch/codex-down/issues/01-one-reviewer-chain.md:77` `.scratch/codex-down/issues/01-one-reviewer-chain.md:81` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:13`

## Citation check

Each `file:line` Codex gave was printed from the files at `e86eb9c` (`git show e86eb9c:<path>`) and read against the
finding that cites it. All 24 hold the text the finding describes at that line. Nothing cited is fabricated.

| Finding | Citation | Mark |
|---|---|---|
| 1 | .scratch/codex-down/issues/02-pr-review-command.md:13 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:19 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:27 | VERIFIED |
| 2 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:14 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:28 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:32 | VERIFIED |
| 4 | .scratch/codex-down/issues/02-pr-review-command.md:32 | VERIFIED |
| 5 | .scratch/codex-down/issues/02-pr-review-command.md:23 | VERIFIED |
| 5 | .scratch/codex-down/issues/02-pr-review-command.md:32 | VERIFIED |
| 5 | .scratch/codex-down/coverage.md:17 | VERIFIED |
| 6 | .scratch/codex-down/issues/08-fallback-review.md:5 | VERIFIED |
| 6 | .scratch/codex-down/issues/06-provisional-recovery.md:13 | VERIFIED |
| 6 | .scratch/codex-down/issues/10-recheck-and-release-stop.md:17 | VERIFIED |
| 6 | .scratch/codex-down/coverage.md:27 | VERIFIED |
| 7 | .scratch/codex-down/coverage.md:14 | VERIFIED |
| 7 | .scratch/codex-down/issues/02-pr-review-command.md:13 | VERIFIED |
| 7 | .scratch/codex-down/issues/02-pr-review-command.md:32 | VERIFIED |
| 8 | .scratch/codex-down/coverage.md:20 | VERIFIED |
| 8 | .scratch/codex-down/coverage.md:21 | VERIFIED |
| 8 | .scratch/codex-down/coverage.md:23 | VERIFIED |
| 8 | .scratch/codex-down/issues/01-one-reviewer-chain.md:77 | VERIFIED |
| 8 | .scratch/codex-down/issues/01-one-reviewer-chain.md:81 | VERIFIED |
| 8 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:13 | VERIFIED |

## Disposition (Fabio)

All eight are real. None is rejected.

| # | Verdict | What was done |
|---|---|---|
| 1 | Real | 02: `<owner>` and `<repo>` must also be neither `.` nor `..` (the pattern lets `..` through, so `../x` split into owner `..` and repo `x` passed). Tests `../x`, `x/..`, `./x`, `a/b/c`. 04 states the same rule for its names |
| 2 | Real | 02: the under-lock re-read now reads head and base (`headRefOid`, `baseRefName`); either differing from what the review ran on is exit 6, nothing posted, round `head-moved` (the status covers both, so no new status value). 04: a round whose `base` is not the live base is passed over like one on another head, so a retargeted PR has no usable GO (3). Tests: a base retargeted during the review (02) and a GO whose base differs from the live base (04) |
| 3 | Real | 02: an outcome table gives `exit_code`, `round`, `status`, `verdict` and `record` for every outcome, the failures after the claim included (the verdict is the chain's whenever it gave one, `status` is `None`); the affected tests assert `verdict` |
| 4 | Real | 02: the writes go through five module-level functions (`open_lock`, `claim_round`, `append_attempts`, `write_out`, `replace_record`) and every write-failure case patches one to raise `OSError`. The permission-based injection and its superuser skip are gone |
| 5 | Real | 02: an existing directory or file with wider modes is tightened to 0700/0600 when the command uses it, and the closing box has mode tests (directories, round files, `.lock`, `attempts.jsonl`, under a permissive umask, and with pre-existing wide modes). Coverage R9 cites them |
| 6 | Real | A real hole in the build order: 08 could post provisional GOs before 06 builds the list that records them, and 10 walks only that list. Fix: in 08 the fallback is opt-in (`allow_fallback`, default false, the CLI's `--fallback`), so before 06 the command is Codex-only and no provisional GO can exist; 06 makes it the default where a usable `--track` is given and keeps no-track-no-fallback; 10 now only passes `allow_fallback=False` and adds `head_sha`. Consequence stated in `plan.md` and `coverage.md`: the effective fallback arrives with 06, so R1's pause in the goal file must say 06, not 08 (the boss is told) |
| 7 | Real | Coverage R6 now also cites 02's command box ("`boss_review.py --repo ... Exit codes", the `repo_key` rule) and its closing test box (the order test and the casing-variant concurrency test) |
| 8 | Real | Coverage R12, R13, R15, R9 and R24 now cite the boxes by their actual first words ("Each attempt carries a reason", "The result records the exact model id", "`boss_merge.py --repo OWNER/REPO --pr N [--dry-run]` is the one merge path", ...); every quoted fragment in the table was re-checked by script against the ticket files |

Fix commit: 6d5b81c
