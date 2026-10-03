# Codex review 3 of the codex-down plan (tickets 02 to 06)

Run by Birgit (task #100), 2026-10-04 00:32-00:40 (+02:00). Reviewer: Codex (`codex exec -s read-only --skip-git-repo-check`,
model `gpt-5.6-sol`, reasoning effort high), stdin closed, working directory the checkout root, brief
`brief-codex-3.md` (7 checks). Answered after about 8 minutes; the harness did not reap it.

Reviewed: `plan.md`, tickets 02 to 06 and `coverage.md` at commit `02ee495` (main), with ticket 01, the premortem,
the goal file and the code the tickets rely on as context.

**Verdict: NO-GO**, 23 findings. Findings 1 to 22 are about the tickets and the coverage table; finding 23 is about size.

The checkout path prefix is not in the links below; Codex's text is unchanged.

## Codex's answer, verbatim

NO-GO

1. The `--check-fallback` box requires a real Claude invocation, so it cannot pass hermetically. Replace its acceptance criterion with recorded stream-JSON fixtures and a stubbed `claude`; retain the real invocation only as an optional manual smoke check. (`.scratch/codex-down/issues/03-labelled-fallback-review.md:16`)

2. A rejected fallback model cannot leave “no model name anywhere written”: every `Attempt` records the exact model and round JSON includes the attempts. Limit the prohibition to public comments while retaining the attempted model in private evidence. (`.scratch/codex-down/issues/03-labelled-fallback-review.md:21`, `.scratch/codex-down/issues/01-one-reviewer-chain.md:40`, `.scratch/codex-down/issues/02-pr-review-command.md:21`)

3. Ticket 03’s final merge rule says anything except a Codex or provisional GO cannot merge, contradicting ticket 05’s permitted `waived` GO. Require ticket 05 to replace that rule with a case explicitly allowing `provisional` or `waived` only on non-deploying branches, and test the final combined wording. (`.scratch/codex-down/issues/03-labelled-fallback-review.md:32`, `.scratch/codex-down/issues/05-dead-reviewer-blocker.md:29`)

4. Ticket 02 incorrectly says ticket 04 calls `review()` for recorded SHAs; that functionality moved to 06. It also never defines the `track` function parameter that 06 passes. Change “04” to “06” and have ticket 05 explicitly add `track: str | None` to `review()` with its default and validation contract. (`.scratch/codex-down/issues/02-pr-review-command.md:17`, `.scratch/codex-down/issues/05-dead-reviewer-blocker.md:22`, `.scratch/codex-down/issues/06-provisional-recovery.md:22`)

5. `tracker.update` has no specified return value or failure contract, yet 06 relies on a successful tracker write before allowing a provisional result. Define success/no-change/timeout/error results and require fallback posting to abort with a specified exit/status if the provisional entry cannot be written and read back. (`.scratch/codex-down/issues/05-dead-reviewer-blocker.md:18`, `.scratch/codex-down/issues/06-provisional-recovery.md:13`)

6. The proposed track-name check permits `..`, unlike the existing tracker identity rule. Add `"..” not in T` and tests for `a..b` as well as traversal-looking inputs. (`.scratch/codex-down/issues/05-dead-reviewer-blocker.md:22`, `skills/boss/bin/boss-tracker:29`)

7. `cd<yymmddHHMM>` is not guaranteed to be new: a blocker can clear and another outage can start within the same minute, causing deduplication against the cleared marker. Use seconds or a collision-resistant suffix within the 16-character marker limit and test two outages in one minute. (`.scratch/codex-down/issues/05-dead-reviewer-blocker.md:22`, `skills/boss/tracker.py:78`)

8. “Asked once” is durable only for the waiver choice; no exact tagged record or restart test is defined for “wait” or “accept fallback.” Specify one blocker-ID-keyed decision format covering all three answers and test restart behavior for each. (`.scratch/codex-down/issues/05-dead-reviewer-blocker.md:28`)

9. `boss_review.py` does not define what “identity mismatch” means or what happens when initial `gh pr view`, comment posting, or artifact writing fails. A numeric PR passed with `--repo` cannot independently “differ” without naming a returned field to verify. Specify the queried identity fields, validation, failure exit codes, round status on post failure, and stubbed tests for each failure. (`.scratch/codex-down/issues/02-pr-review-command.md:13`, `.scratch/codex-down/issues/02-pr-review-command.md:14`, `.scratch/codex-down/issues/02-pr-review-command.md:15`)

10. The merge gate does not say how malformed round JSON, missing required fields, or an unknown verdict is handled. An implementation could skip a malformed newer round and accept an older GO. Require any unreadable or schema-invalid candidate record to refuse without merging, with explicit exit/reason tests. (`.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:17`)

11. `test_paths` is optional but has no schema validation. A string, mixed list, or malformed pattern can be interpreted differently and potentially enable the test-only exception. Require `test_paths` to be a list of strings when present; otherwise refuse, with tests. (`.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:21`, `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:22`)

12. `--match-head-commit` pins only the head, not the PR’s base. A provisional PR can be retargeted from a non-deploying base to a deploying base after the check and still merge. Require a merge mechanism that pins both the observed head and base identity, or weaken the absolute safety claim and add a retarget-during-merge test. (`.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:13`)

13. Round numbers are claimed before concurrent reviews finish, but the gate trusts the highest number. A slow lower-numbered NO-GO can post after a fast higher-numbered GO and be ignored. Serialize reviews per PR or assign authoritative order at posting, then test out-of-order concurrent GO/NO-GO completion. (`.scratch/codex-down/issues/02-pr-review-command.md:22`, `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:17`)

14. “Every `gh` call carries `--repo`” conflicts with the specified `gh api` calls, whose repository is encoded in the endpoint rather than selected by `--repo`. Change this to “every `gh pr` call carries `--repo`; every `gh api` endpoint contains the validated owner/repo,” and test both. (`.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:13`, `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:21`)

15. The hard-rule acceptance commands omit mandatory `--why`, so they exit 2 before testing the rule. The regex also misses valid direct merges such as `gh --repo o/r pr merge 5` and `gh -R o/r pr merge 5`. Add `--why` to every test and cover global `gh` options in the rule and fixtures. (`.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:26`, `skills/boss/bin/boss-run:207`)

16. The provisional cleanup rule does not require the later Codex GO to cover the entry’s SHA. For a merged PR whose branch advances, a GO on the newer live head can erase the entry without reviewing the merged SHA. Require a matching `head_sha` for generic cleanup and separately define removal after a recheck of an advanced open PR. (`.scratch/codex-down/issues/06-provisional-recovery.md:14`, `.scratch/codex-down/issues/06-provisional-recovery.md:22`)

17. Coverage of R3 is false: separate timeout constants prove eventual fallback but do not bound the several-minute outage stall, and ticket 02 explicitly makes the Codex timeout longer than 120 seconds. Specify production timeout bounds and an elapsed-time acceptance test, or mark R3 as accepted residual risk. (`.scratch/codex-down/coverage.md:9`, `.scratch/codex-down/issues/02-pr-review-command.md:16`, `.scratch/codex-down/issues/03-labelled-fallback-review.md:22`)

18. Coverage of R4 is false: fencing and parser tests do not establish that hostile fenced PR text cannot induce the reviewer to emit a valid GO. Add independently verifiable review criteria, or identify prompt injection as accepted residual risk instead of claiming the box satisfies R4. (`.scratch/codex-down/coverage.md:10`, `.scratch/codex-down/issues/02-pr-review-command.md:27`)

19. Coverage of R8 is false: the redaction box covers IPv4 addresses, token shapes, e-mail, home paths and configured patterns, but not general hostnames, client identifiers, or proprietary snippets in `FINDING:` text. Define and test those redactions or stop publishing free-form findings. (`.scratch/codex-down/coverage.md:14`, `.scratch/codex-down/issues/02-pr-review-command.md:28`)

20. Coverage of R12 is false: authentication, quota, CLI, repository and prompt-format errors are labelled differently but still all permit fallback under `reason=error`. Restrict fallback to an explicit outage-class subset or record this as an owner-accepted residual risk. (`.scratch/codex-down/coverage.md:18`, `.scratch/codex-down/issues/03-labelled-fallback-review.md:20`)

21. Coverage of R14 is false for stale configuration. Reading the file from the base prevents a PR-head edit, but nothing detects a base configuration that still lists a branch after that branch begins deploying. Add an authoritative deployment-state check or mark stale configuration as an accepted limitation. (`.scratch/codex-down/coverage.md:20`, `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:21`)

22. Coverage of R25 omits the premortem’s TypeSafe resolution requirement; every named closing box guards only `codex`, `claude`, and `gh`. Add the TypeSafe stub/PATH assertion wherever it can resolve, or explicitly demonstrate that none of these tickets invokes it. (`.scratch/codex-down/coverage.md:31`, `.scratch/codex-down/issues/02-pr-review-command.md:34`)

23. Tickets 02, 03 and 05 have 14, 12 and 9 boxes respectively, while 04 and 06 each compress several independent commands, persistence mechanisms and test suites into seven large boxes. Split 02 at record-writing versus prompt/comment policy; 03 at fallback confinement versus review integration; 05 at health/tracker primitives versus owner choice/waiver; 04 at merge decision/config versus command enforcement; and 06 at provisional persistence versus recovery/blocker handling. (`.scratch/codex-down/issues/02-pr-review-command.md:11`, `.scratch/codex-down/issues/03-labelled-fallback-review.md:11`, `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:11`, `.scratch/codex-down/issues/05-dead-reviewer-blocker.md:11`, `.scratch/codex-down/issues/06-provisional-recovery.md:11`)

## Citation check

Each `file:line` Codex gave was read after the run (by a subagent, and the line numbers re-checked by Birgit).
All 49 hold the text the finding describes at that line. Nothing cited is fabricated.

| Finding | Citation | Mark |
|---|---|---|
| 1 | .scratch/codex-down/issues/03-labelled-fallback-review.md:16 | VERIFIED |
| 2 | .scratch/codex-down/issues/03-labelled-fallback-review.md:21 | VERIFIED |
| 2 | .scratch/codex-down/issues/01-one-reviewer-chain.md:40 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:21 | VERIFIED |
| 3 | .scratch/codex-down/issues/03-labelled-fallback-review.md:32 | VERIFIED |
| 3 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:29 | VERIFIED |
| 4 | .scratch/codex-down/issues/02-pr-review-command.md:17 | VERIFIED |
| 4 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:22 | VERIFIED |
| 4 | .scratch/codex-down/issues/06-provisional-recovery.md:22 | VERIFIED |
| 5 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:18 | VERIFIED |
| 5 | .scratch/codex-down/issues/06-provisional-recovery.md:13 | VERIFIED |
| 6 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:22 | VERIFIED |
| 6 | skills/boss/bin/boss-tracker:29 | VERIFIED |
| 7 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:22 | VERIFIED |
| 7 | skills/boss/tracker.py:78 | VERIFIED |
| 8 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:28 | VERIFIED |
| 9 | .scratch/codex-down/issues/02-pr-review-command.md:13 | VERIFIED |
| 9 | .scratch/codex-down/issues/02-pr-review-command.md:14 | VERIFIED |
| 9 | .scratch/codex-down/issues/02-pr-review-command.md:15 | VERIFIED |
| 10 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:17 | VERIFIED |
| 11 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:21 | VERIFIED |
| 11 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:22 | VERIFIED |
| 12 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:13 | VERIFIED |
| 13 | .scratch/codex-down/issues/02-pr-review-command.md:22 | VERIFIED |
| 13 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:17 | VERIFIED |
| 14 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:13 | VERIFIED |
| 14 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:21 | VERIFIED |
| 15 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:26 | VERIFIED |
| 15 | skills/boss/bin/boss-run:207 | VERIFIED |
| 16 | .scratch/codex-down/issues/06-provisional-recovery.md:14 | VERIFIED |
| 16 | .scratch/codex-down/issues/06-provisional-recovery.md:22 | VERIFIED |
| 17 | .scratch/codex-down/coverage.md:9 | VERIFIED |
| 17 | .scratch/codex-down/issues/02-pr-review-command.md:16 | VERIFIED |
| 17 | .scratch/codex-down/issues/03-labelled-fallback-review.md:22 | VERIFIED |
| 18 | .scratch/codex-down/coverage.md:10 | VERIFIED |
| 18 | .scratch/codex-down/issues/02-pr-review-command.md:27 | VERIFIED |
| 19 | .scratch/codex-down/coverage.md:14 | VERIFIED |
| 19 | .scratch/codex-down/issues/02-pr-review-command.md:28 | VERIFIED |
| 20 | .scratch/codex-down/coverage.md:18 | VERIFIED |
| 20 | .scratch/codex-down/issues/03-labelled-fallback-review.md:20 | VERIFIED |
| 21 | .scratch/codex-down/coverage.md:20 | VERIFIED |
| 21 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:21 | VERIFIED |
| 22 | .scratch/codex-down/coverage.md:31 | VERIFIED |
| 22 | .scratch/codex-down/issues/02-pr-review-command.md:34 | VERIFIED |
| 23 | .scratch/codex-down/issues/02-pr-review-command.md:11 | VERIFIED |
| 23 | .scratch/codex-down/issues/03-labelled-fallback-review.md:11 | VERIFIED |
| 23 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:11 | VERIFIED |
| 23 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:11 | VERIFIED |
| 23 | .scratch/codex-down/issues/06-provisional-recovery.md:11 | VERIFIED |

## Disposition (Birgit)

Every finding was weighed against the ticket text and, where it names code, the code. None is rejected outright;
four are accepted as residual risks stated in `coverage.md` (18, 19, 20, 21) and two only in part (12, 17).
Ticket 01 is not touched by any finding. The fixes are in the commit named at the end of this file.

| # | Verdict | What was done |
|---|---|---|
| 1 | Real | 03: the `--check-fallback` decision logic (init event: exactly `Glob`, `Grep`, `Read`; no MCP servers; model id) is tested against recorded stream-JSON fixtures through a `claude` stub. The real call stays an optional manual smoke check and is no box's pass condition |
| 2 | Real | 08: the prohibition now reads: nothing posted, no record that reads as a verdict, no "Opus" label anywhere; the model id the stub rejected stays only in the private `attempts` of `round<NN>.json`, which is what 01's `Attempt.model` is for |
| 3 | Real | 08 words the SKILL.md rule for any GO that is not Codex's (a provisional fallback review, or the owner's merge on tests alone) so it needs no later edit; 09 adds a text test on the final wording (once, with the tests-alone case) |
| 4 | Real | 02: "04" became "10" (the recheck calls `review()` since the split). 05 now defines `review(..., track: str \| None = None)`, its default and its validation (bad name: exit 2 / `ValueError`; missing tracker: stderr note, result unchanged) |
| 5 | Real | 05: `tracker.update` returns `done`, `done (no change)` or `failed: <reason>` (the strings `tracker_add` already returns) and never raises for those. 06: a provisional GO is posted only after `update` returned `done` and the entry reads back; else nothing is posted, round `list-failed`, exit 7 |
| 6 | Real | 05: the track check is `boss_store.valid_track` (the regex and no `..`), the same rule `boss-tracker` uses; test `a..b` |
| 7 | Real | 05: marker id `cd` plus twelve digits (`%y%m%d%H%M%S`, 14 of the 16 characters the marker allows); test of two outages in one minute with an injected clock |
| 8 | Real | 09: one record for all three answers, `- [codex-choice <blocker id>] <wait\|accept-fallback\|tests-alone> - <ts>`, and `codex_health.py --choice --track T` to read it; restart test for each answer; `--waive` needs `tests-alone` |
| 9 | Real | 02: the identity fields are named (`number`, `url`, compared with `--repo` and `--pr`), and exit 7 covers `gh pr view` failing, the comment post failing (round `post-failed`) and round files that cannot be written, each with a stubbed test |
| 10 | Real | 04: the gate walks the PR's rounds from the highest number down; an unreadable, schema-invalid or unknown-valued file met before the deciding round refuses (3, `bad-record`); it never skips one to reach an older GO |
| 11 | Real | 04: `test_paths`, when present, must be a list of strings, else the whole file is invalid and every branch counts as deploying; `fnmatch.fnmatchcase`; tests |
| 12 | Partly | `gh pr merge` has no base pin, and neither has the GraphQL `mergePullRequest` (`expectedHeadOid` only). The absolute claim is weakened: 04 re-reads the PR after the merge and exits 5 `base-changed` with `boss-alert 0` if the base is not the one checked; 11's SKILL text states that a base retargeted inside that window is detected after the fact, not prevented |
| 13 | Real | 02: the round number is claimed at completion, under a per-PR lock held from the claim to the written record, so numbers follow posting order and "highest wins" means "last posted verdict"; test: the review that starts first and finishes last gets the higher number |
| 14 | Real | 02 and 04: every `gh pr` call carries `--repo`; every `gh api` endpoint starts `repos/<owner>/<repo>/` with the validated names; both asserted from the call log |
| 15 | Real | 11: every hard-rule test passes `--why`; the pattern now matches global options (`gh --repo o/r pr merge`, `gh -R o/r pr merge`, a path to `gh`) |
| 16 | Real | 06: an entry is removed by a Codex GO whose `head_sha` equals the entry's `head=`; for an open PR also by a Codex GO on the live head. A GO on a later head never removes the entry of a merged PR |
| 17 | Partly | R3 is bounded, not removed. 02 states the production values (`REVIEW_CODEX_TIMEOUT = 600`, `REVIEW_FALLBACK_TIMEOUT = 600`: a Codex review of this plan took 8 minutes) and 03 adds an elapsed-time test with 1-second test values. The coverage row now says what stays: a hung Codex costs one timeout per review; an absent or failing Codex costs nothing |
| 18 | Right, accept | No parser can prove a reviewer was not talked into a GO. `coverage.md` R4 now says "mitigated" and lists the residual; the backstops are the fence, the last-message rule, and for provisional GOs Codex's later re-review |
| 19 | Right, accept | Hostnames, client names and proprietary wording in free-text `FINDING:` lines are caught only by IPv4, token, e-mail, home-path and the site pattern file. `coverage.md` R8 says so; the line cap (20 x 300) stays. Owner to decide whether to publish no findings at all |
| 20 | Right, accept | Plan decision 1 is "when Codex does not answer": every non-answer runs the fallback, by the owner's rule. R12 is mitigated by labelling (reason, exit code and redacted stderr tail in the record and comment), not prevented; `coverage.md` says so |
| 21 | Right, accept | A listed branch that later starts to deploy is outside what a file in the repo can know. 11's SKILL text names the limit; `coverage.md` R14 splits "covered" (missing, malformed, not listed, PR-edited) from "accepted limitation" (stale) |
| 22 | Real | Each ticket's closing test box sets `BOSS_TYPESAFE_ENV` to a missing path (the only module that reads that key is `boss-jev.py`, whose `tracker_add` 05 moves), and `coverage.md` R25 says no ticket here calls TypeSafe |
| 23 | Real | Split. 02 into 02 (command, record, rounds) and 07 (brief fence, comment, redaction, skill text); 03 into 03 (fallback confinement) and 08 (fallback review: provisional record, label, merge rule); 05 into 05 (health, tracker writer, blocker) and 09 (owner choice, waiver); 04 into 04 (gate) and 11 (test-only exception, hard rule, skill text); 06 into 06 (the list) and 10 (recheck, post-merge blocker, release stop). Ticket 01 stays as it is. Build order in `plan.md` |

Fix commit: 385f71c (tickets 02 to 11, plan.md, coverage.md; frontier.py output checked against the expected graph).
