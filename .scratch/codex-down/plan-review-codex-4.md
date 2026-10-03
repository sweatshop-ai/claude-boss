# Codex review 4 of the codex-down plan (structure of tickets 02 to 11, and ticket 02 in full)

Run by Birgit (task #100), 2026-10-04 00:58-01:05 (+02:00). Reviewer: Codex (`codex exec -s read-only --skip-git-repo-check`,
model `gpt-5.6-sol`, reasoning effort high), stdin closed, working directory the checkout root, brief
`brief-codex-4.md` (6 checks). Answered after about 7 minutes; launched as a foreground command with
`run_in_background: true`, activity confirmed in the first minute.

Reviewed at commit `8b08f1a` (main): `plan.md`, `coverage.md`, the headers and boxes of tickets 02 to 11 as context for
the structure, and ticket 02 in full, with ticket 01, the earlier records, the premortem, the goal file and the code the
tickets rely on as context. Scope set by the boss (task #100): (a) the structure (the split, the Blocked-by graph, the
coverage table R1 to R25 and findings 4, 5 and 7 mapped to ticket boxes) and (b) ticket 02 in full; tickets 03 to 11 get
their own Codex round just before each is built.

**Verdict: NO-GO**, 11 findings. Findings 1 to 5 are about ticket 02, 6 to 10 about the coverage table (6 to 9 about
what it claims, 10 about R25's text and the tickets' closing boxes), 11 about ticket 10's call to 02's function.
Codex found no problem with the Blocked-by graph, and no host name, IP address, client name or home path.

The checkout path prefix is not in the links below; Codex's text is unchanged.

## Codex's answer, verbatim

NO-GO

1. Ticket 02 names `review(...)` without defining its base parameters, return type, or how callers obtain the claimed round and outcome; tickets 05 and 10 therefore cannot extend or consume one unambiguous interface. Add the complete signature and a structured return contract containing at least exit outcome, round number, status, and record path. `.scratch/codex-down/issues/02-pr-review-command.md:15`

2. The review execution context is undefined. Ticket 01’s fixed `run_chain` interface has no working-directory parameter, ticket 02 only verifies `--checkout`, and ticket 03 requires Claude to run there. Specify how `review()` makes both reviewers run with `--checkout` as their working directory, define ticket 02’s minimal pre-07 prompt, and test the stub’s recorded cwd. `.scratch/codex-down/issues/01-one-reviewer-chain.md:49` `.scratch/codex-down/issues/02-pr-review-command.md:14` `.scratch/codex-down/issues/03-labelled-fallback-review.md:13`

3. The round and global-attempt schemas are incomplete. Ticket 02 does not define the values of top-level `reviewer` and `model` for a Codex answer or no answer, and “exit code for error” does not name the JSON key or say whether it is absent or null otherwise. Later tickets depend on those distinctions. Add an exact schema for every 02 outcome, including required/null fields and exact attempt-log key names. `.scratch/codex-down/issues/02-pr-review-command.md:19` `.scratch/codex-down/issues/08-fallback-review.md:14`

4. The claimed round/comment consistency is not maintained on specified failures. A comment call can fail or time out after GitHub accepted it, and a successful comment followed by final-JSON failure leaves the public verdict paired with an empty claimed record. Define a durable pre-post state plus an idempotency marker and read-back reconciliation, or explicitly define and test an unknown-post state that the gate rejects and a retry reconciles. `.scratch/codex-down/issues/02-pr-review-command.md:20` `.scratch/codex-down/issues/02-pr-review-command.md:21`

5. Ticket 02’s tests do not exercise several promised observable branches: initial checkout-HEAD mismatch, a `gh` timeout, lock-wait timeout, attempts-log append failure, output-file failure, or final replacement failure after posting. Add hermetic cases for each, with asserted exit code, comment calls, record status/content, and attempts-log state. `.scratch/codex-down/issues/02-pr-review-command.md:14` `.scratch/codex-down/issues/02-pr-review-command.md:21` `.scratch/codex-down/issues/02-pr-review-command.md:25`

6. R5 is not fully covered as claimed. The head is re-read before attempts and output are written and before the comment call, so it can still move in that window and receive a stale-SHA comment. Change the coverage row to describe this as bounded, and name 04’s exact-live-head gate as what prevents that stale comment from authorizing a merge; add the intervening-move test. `.scratch/codex-down/coverage.md:13` `.scratch/codex-down/issues/02-pr-review-command.md:20`

7. R1’s pause is not truthful: the row acknowledges that fallback availability moved to ticket 08 while the controlling goal still stops only before ticket 03. After 03 and before 08, an outage is therefore not covered by that pause. Change the pause threshold to “before 08 lands” and then update this row accordingly. `.scratch/codex-down/coverage.md:9` `.scratch/codex-down/plan.md:48`

8. R13 is not covered. The automated check uses stubbed stream events, the real check is explicitly not a pass condition, and normal fallback records label the model from the requested `Attempt.model`, not from runtime-reported identity. A CLI that silently runs another model can still be labelled as Opus. Either validate the runtime model on every fallback invocation or mark R13 as mitigated/residual rather than covered. `.scratch/codex-down/coverage.md:21` `.scratch/codex-down/issues/03-labelled-fallback-review.md:19` `.scratch/codex-down/issues/08-fallback-review.md:14`

9. R21 is not covered: ticket 05 explicitly combines all repositories, which preserves the premortem’s false-global-blocker case from consecutive unrelated failures. Either scope streaks appropriately or mark cross-repository aggregation as a residual risk and explain the accepted false-positive behavior. `.scratch/codex-down/coverage.md:29` `.scratch/codex-down/issues/05-dead-reviewer-blocker.md:14`

10. The R25 row falsely says every closing box provides `codex`, `claude`, and `gh` stubs. Tickets 03, 04, and 11 omit one or more of those stubs while still requiring the guard to reject any resolution outside the stub directory, making the stated guard ambiguous or permanently failing. Require no-op stubs for every guarded executable in every ticket. `.scratch/codex-down/coverage.md:33` `.scratch/codex-down/issues/03-labelled-fallback-review.md:27` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:26` `.scratch/codex-down/issues/11-gate-enforcement.md:25`

11. Ticket 10 introduces `head_sha` specifically for recorded commits, but its specified recheck call omits that argument even for merged PRs. State explicitly that merged entries call `review(..., head_sha=<entry head>, allow_fallback=False, track=T)` and that open entries omit `head_sha`. `.scratch/codex-down/issues/10-recheck-and-release-stop.md:13` `.scratch/codex-down/issues/10-recheck-and-release-stop.md:17`

## Citation check

Each `file:line` Codex gave was printed from the files at `8b08f1a` before any fix was written, and read against the
finding that cites it. All 26 hold the text the finding describes at that line. Nothing cited is fabricated.

| Finding | Citation | Mark |
|---|---|---|
| 1 | .scratch/codex-down/issues/02-pr-review-command.md:15 | VERIFIED |
| 2 | .scratch/codex-down/issues/01-one-reviewer-chain.md:49 | VERIFIED |
| 2 | .scratch/codex-down/issues/02-pr-review-command.md:14 | VERIFIED |
| 2 | .scratch/codex-down/issues/03-labelled-fallback-review.md:13 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:19 | VERIFIED |
| 3 | .scratch/codex-down/issues/08-fallback-review.md:14 | VERIFIED |
| 4 | .scratch/codex-down/issues/02-pr-review-command.md:20 | VERIFIED |
| 4 | .scratch/codex-down/issues/02-pr-review-command.md:21 | VERIFIED |
| 5 | .scratch/codex-down/issues/02-pr-review-command.md:14 | VERIFIED |
| 5 | .scratch/codex-down/issues/02-pr-review-command.md:21 | VERIFIED |
| 5 | .scratch/codex-down/issues/02-pr-review-command.md:25 | VERIFIED |
| 6 | .scratch/codex-down/coverage.md:13 | VERIFIED |
| 6 | .scratch/codex-down/issues/02-pr-review-command.md:20 | VERIFIED |
| 7 | .scratch/codex-down/coverage.md:9 | VERIFIED |
| 7 | .scratch/codex-down/plan.md:48 | VERIFIED |
| 8 | .scratch/codex-down/coverage.md:21 | VERIFIED |
| 8 | .scratch/codex-down/issues/03-labelled-fallback-review.md:19 | VERIFIED |
| 8 | .scratch/codex-down/issues/08-fallback-review.md:14 | VERIFIED |
| 9 | .scratch/codex-down/coverage.md:29 | VERIFIED |
| 9 | .scratch/codex-down/issues/05-dead-reviewer-blocker.md:14 | VERIFIED |
| 10 | .scratch/codex-down/coverage.md:33 | VERIFIED |
| 10 | .scratch/codex-down/issues/03-labelled-fallback-review.md:27 | VERIFIED |
| 10 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:26 | VERIFIED |
| 10 | .scratch/codex-down/issues/11-gate-enforcement.md:25 | VERIFIED |
| 11 | .scratch/codex-down/issues/10-recheck-and-release-stop.md:13 | VERIFIED |
| 11 | .scratch/codex-down/issues/10-recheck-and-release-stop.md:17 | VERIFIED |

## Disposition (Birgit)

Every finding was weighed against the ticket text and, where it names code, the code. None is rejected; two are accepted
in part (4, 7) and two (8, 9) are right and become entries in the residual risks of `coverage.md`.

| # | Verdict | What was done |
|---|---|---|
| 1 | Real | 02: the function is now defined: `review(repo, pr, checkout, author, *, codex_timeout, io_timeout) -> ReviewResult`, with `ReviewResult = (exit_code, round, status, verdict, record)`, `None` where no round was claimed. An argument that fails its check raises `ValueError` (the CLI's exit 2); every other outcome is a result, never an exception. 05, 08 and 10 extend it with named keyword-only parameters that have defaults |
| 2 | Real | 02: `run_chain` has no working-directory parameter and 01 is not touched, so `review()` runs the chain in a child process whose working directory is `--checkout` and both reviewers inherit it; the brief at this ticket is a fixed `build_brief(head_sha, base)` with no PR text (07 replaces it). Test: the `codex` stub's recorded cwd; 08 adds the same for the `claude` stub |
| 3 | Real | 02: one box now gives every key of `round<NN>.json` and of an `attempts.jsonl` line, the value sets, which values are `null` and what `reviewer` and `model` hold for a Codex answer and for no answer (`"codex"` / `"none"`, `model` null); 08 and 09 name the values they add (`"opus"`, `"tests"`) |
| 4 | Partly | Codex's second alternative taken: 02 defines and tests the unknown-post states instead of an idempotency marker. The record, not the comment, is what the gate reads; a round is `posted` only after the comment call returned success; a comment call that failed after GitHub accepted the comment (`post-failed`) and a final write that failed after a good post (empty claimed file) are both refused by 04; a retry is a new round. Writing this exposed a gap in 04: a `post-failed` NO-GO was passed over, so an older GO could allow the merge. 04 now refuses a `post-failed` NO-GO on the live head (3, `unposted-no-go`) and passes over a `post-failed` GO, with a test row for each |
| 5 | Real | 02's closing box adds the missing cases: checkout HEAD different from the PR head, a `gh` call past `io_timeout`, the lock held past the wait, an unwritable attempts log, an unwritable `.out`, a comment call that times out after the stub recorded it, a final write that fails after the post, and the head moving during the post; each asserts the exit code, the comment calls, the record and the attempts log |
| 6 | Real | R5 is now "bounded": the window between the re-read and the comment is narrowed, not closed. The comment and the record name the head reviewed; 04's gate needs a posted GO on the live head and `--match-head-commit` pins the head at the merge. Coverage row changed, a residual row added, 02 states the window and tests the head moving during the post |
| 7 | Partly | The goal file's "Pause when" line is the boss's file and still says 03; this review's fix is the truthful row (it says the line must say 08), a sentence in `plan.md` that the track pauses until 08 lands, and a request to the boss to change the line |
| 8 | Right | R13 is "mitigated", not "covered": the label is the id the fallback was asked to run, not an identity the CLI reports on every call, and the stream-JSON check is a manual smoke test. Residual row added; no per-call check is possible in the text answer channel 01 pins for the fallback |
| 9 | Right | R21 is "mitigated by design": one Codex per config dir, so a streak counts across repos and an answer anywhere ends it. Three failed attempts in a row from unrelated causes with no answer between them still raise a false blocker, which costs one owner question. Residual row added |
| 10 | Real | 03, 04 and 11 now list a logging stub for each of `codex`, `claude` and `gh` (plus `boss-alert` where used), with the log empty for a tool the ticket never calls; coverage R25 says so. The tickets that already listed all three are unchanged |
| 11 | Real | 10: a merged entry is reviewed with `head_sha=<the entry's head=>`, an open entry without `head_sha`, both with `allow_fallback=False` and `track=T` |

Fix commit: 17be14e (tickets 02, 03, 04, 08, 10, 11, plan.md, coverage.md; frontier.py output unchanged and checked).
