# Codex review 7 of the codex-down plan (structure of tickets 02 to 11, and ticket 02 in full)

Run by Kaveh (task #100, restarted fresh after Fabio's handoff part d), 2026-10-04 08:53-09:04 (+02:00). Reviewer: Codex (`codex exec -s read-only --skip-git-repo-check`,
model `gpt-5.6-sol`, reasoning effort high), stdin closed, working directory the checkout root, brief `brief-codex-7.md`
(`brief-codex-6.md` plus a round-7 paragraph: check that the round-6 fixes landed and hold, R1 is pending on purpose, R4/R8/R12/R14 are accepted
residuals, R13/R21 are residual rows pending the owner). Answered after about 11 minutes; run in the background, activity confirmed in the first minute.

Reviewed at commit `c03b83a` (main), which is `6d5b81c` (the round-6 fixes) plus the record of round 6 and the owner's acceptance of R4, R8, R12 and R14. Scope as in round 4: the structure and ticket 02 in full.

**Verdict: NO-GO**, 6 findings (1 to 3 on how 04, 06, 08 and 09 relate to 02's interfaces, 4 on a sentence in ticket 02, 5 and 6 on coverage rows). Codex did not
reopen any earlier finding and raised nothing on the Blocked-by graph, ticket sizes, the dependencies of 05 and 10 or the privacy check. Only finding 4 touches ticket 02, and it is a wording
fix to a summary sentence; none of the six touches 02's mechanics.

The checkout path prefix is not in the links below; Codex's text is unchanged.

## Codex's answer, verbatim

NO-GO

1. Ticket 08 still exposes `--fallback` before ticket 06 exists, so it can post exactly the unlisted provisional GO the round-6 fix claimed to prevent. Remove the production CLI opt-in until 06 can write the tracker entry, or add durable pending storage in 08 and migration in 06; update R19 accordingly. `.scratch/codex-down/issues/08-fallback-review.md:5` `.scratch/codex-down/issues/08-fallback-review.md:13` `.scratch/codex-down/coverage.md:27`

2. Ticket 04’s provisional-record test passes `--track` but not `--fallback`; that enables fallback only after 06 changes the default, yet 04 is not blocked by 06. Add 06 to `Blocked by` and update the frontier expectation, or explicitly pass `--fallback` if finding 1 is resolved while retaining that flag. `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:7` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18` `.scratch/codex-down/issues/06-provisional-recovery.md:14`

3. Ticket 09 says its under-lock re-read works “as in 02” but checks only the head, whereas 02 now requires both head and base and returns exit 6 if either moved. Require the waiver path to re-read both fields, define base movement as exit 6, and add the corresponding test. `.scratch/codex-down/issues/02-pr-review-command.md:27` `.scratch/codex-down/issues/09-owner-choice-and-waiver.md:18`

4. Ticket 02 says “highest wins” means the last posted verdict, but ticket 04 makes a newer bad record or unposted `post-failed` NO-GO override that verdict. Replace the summary in 02 with the exact fail-closed scan rule used by 04. `.scratch/codex-down/issues/02-pr-review-command.md:27` `.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18`

5. The R8 and R12 coverage rows no longer name ticket 08’s box by its first words: the box now begins “`review()` gains two keyword-only parameters,” while both rows cite an interior clause. Replace both citations with the current box opening. `.scratch/codex-down/coverage.md:3` `.scratch/codex-down/coverage.md:16` `.scratch/codex-down/coverage.md:20` `.scratch/codex-down/issues/08-fallback-review.md:13`

6. The R8 residual still says the owner may choose to publish no findings, although the recorded decision is that R8 stays as written and ticket 07 requires findings to be published after redaction and capping. Remove that pending-choice sentence and state the accepted residual. `.scratch/codex-down/coverage.md:44` `.scratch/codex-down/coverage.md:51` `.scratch/codex-down/issues/07-review-brief-and-comment.md:17`

## Citation check

Each `file:line` Codex gave was printed from the files at `c03b83a` (`git show c03b83a:<path>`) by a cheap subagent and read against the
finding that cites it.

All 17 citations hold the text the finding describes at that line. Nothing cited is fabricated.

| Finding | Citation | Mark |
|---|---|---|
| 1 | .scratch/codex-down/issues/08-fallback-review.md:5 | VERIFIED |
| 1 | .scratch/codex-down/issues/08-fallback-review.md:13 | VERIFIED |
| 1 | .scratch/codex-down/coverage.md:27 | VERIFIED |
| 2 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:7 | VERIFIED |
| 2 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18 | VERIFIED |
| 2 | .scratch/codex-down/issues/06-provisional-recovery.md:14 | VERIFIED |
| 3 | .scratch/codex-down/issues/02-pr-review-command.md:27 | VERIFIED |
| 3 | .scratch/codex-down/issues/09-owner-choice-and-waiver.md:18 | VERIFIED |
| 4 | .scratch/codex-down/issues/02-pr-review-command.md:27 | VERIFIED |
| 4 | .scratch/codex-down/issues/04-codex-rerun-before-deploy.md:18 | VERIFIED |
| 5 | .scratch/codex-down/coverage.md:3 | VERIFIED |
| 5 | .scratch/codex-down/coverage.md:16 | VERIFIED |
| 5 | .scratch/codex-down/coverage.md:20 | VERIFIED |
| 5 | .scratch/codex-down/issues/08-fallback-review.md:13 | VERIFIED |
| 6 | .scratch/codex-down/coverage.md:44 | VERIFIED |
| 6 | .scratch/codex-down/coverage.md:51 | VERIFIED |
| 6 | .scratch/codex-down/issues/07-review-brief-and-comment.md:17 | VERIFIED |

## Disposition (Kaveh)

All six are real. None is rejected.

| # | Verdict | What was done |
|---|---|---|
| 1 | Real | 08 exposed `--fallback` before 06 could write the list, so the command could post an unlisted provisional GO; the round-6 wording ("no provisional GO can exist before 06") was true only if nobody passed the flag. Fix (Codex's first option): 08 has no command-line switch. `review()` keeps `allow_fallback` (default false) and `main()` does not pass it; 08's tests call `review(..., allow_fallback=True)` in process, plus a command-line test with Codex absent (exit 4, `claude` log empty). 06 sets it from the command line when `--track` is usable, and `review(allow_fallback=True)` without a usable `track` runs Codex only; its sentence on amending earlier tests now covers 04, 05 and 09. R19 cites 08's box and the new test; the R1 row and `plan.md` say "the command line cannot enable the fallback until 06". I grepped 04, 05, 09, 10, 11 for a test that needs a command-line fallback: none does (05's `codex_health` table uses attempt lines; 10 passes `allow_fallback=False`). |
| 2 | Real, fixed without a graph change | 04's end-to-end provisional test now calls `review(..., allow_fallback=True, track=<throwaway tracker>)` in process; with both arguments it holds whether or not 06 has landed, and the test needs only the record the writer produces. "Blocked by" stays 08, 09: adding 06 would be a dependency 04 does not need. Frontier output unchanged. |
| 3 | Real | 09's `--waive` re-reads head and base under the lock as in 02; a moved base is exit 6 with a `head-moved` round; the waived round's `head_sha` and `base` are the values read before the tests ran; the test list has a moved base. |
| 4 | Real | 02's "highest wins means last posted verdict" is replaced by "numbers follow posting order and each comment's number equals its file's; which round decides is 04's scan, not a rule of this ticket". No other text used the phrase. |
| 5 | Real | R8 and R12 now cite 08's box by its opening words ("`review()` gains two keyword-only parameters"). I ran a script over every quoted fragment in `coverage.md`: each one begins a box of its named ticket (four abbreviated with "..." checked by their prefix). |
| 6 | Real | The sentence "The owner may choose to publish no findings at all" is removed from the R8 residual; the row states the accepted residual and ticket 07 line 17 agrees. In the same commit, on the boss's message: R13 and R21 are "accepted by the owner 2026-10-04" (table rows and the Residual risks paragraph). |

Fix commit: e9394a6

## Settled (Birgit)

Written by Kaveh on the boss's stop rule of 2026-10-04: the agent asking for the review decides whether the reviewer is right. My judgement on the spec (structure + ticket 02): **settled, no round 8.**

Dispositions of the open findings: 1 to 6 right, all fixed in `e9394a6` (table above). None is declined. Nothing from rounds 3 to 7 is open.

Why no round 8:

- **Ticket 02 has converged.** Round 6 raised five findings on its mechanics; round 7 raised one, a summary sentence that disagreed with 04's scan rule. No finding of round 7 is about the round-claiming order, the record schema, the exit codes or the `ReviewResult` table.
- **The structure has not moved.** The Blocked-by graph is unchanged since round 3, no round after round 4 raised it, and `frontier.py` prints the same output after every fix commit (below). Ticket sizes and the privacy check were not raised in rounds 5, 6 or 7.
- **What round 7 found were seams between tickets** (08 against 06, 04 against 06, 09 against 02, a coverage citation). Each of tickets 03 to 11 gets its own Codex round by its builder before it is built, which is where seam findings of this kind are checked against the ticket's own text.
- **What I did not do:** Codex has not re-read the `e9394a6` fixes. The one with design weight is finding 1: the command-line switch for the fallback moves from 08 to 06 (an interface detail between two tickets, not the graph or an ownership change). I checked it by grep across 04, 05, 09, 10, 11, `plan.md` and `coverage.md`; the builders of 08, 06 and 04 should confirm it in their own rounds.

Frontier after the fixes: `Ready now: none; Claimed: 01; 02 after 01; 03 after 02; 07 after 02; 08 after 03, 07; 05 after 02, 08; 06 after 05, 08; 09 after 05, 08; 04 after 08, 09; 10 after 06; 11 after 04`.

Open for the boss, outside the spec: the goal file's "Pause when" line (`~/.claude/pm/codex-down.goal.md`) still says "before 03 lands" and must say 06; R1 stays "pending" in `coverage.md` until it does.
