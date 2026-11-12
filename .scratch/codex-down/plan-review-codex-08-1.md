# Codex spec round 1 of ticket 08 (the fallback review, labelled and provisional)

Run by Solveig (task #08S of the codex-down track), 2026-11-12. Reviewer: Codex via `codex-review.sh exec`, read-only, brief `/home/tiroir/Projects/boss-plugin-wt/08-spec-reviews/brief-08-2.md`, answer `/home/tiroir/Projects/boss-plugin-wt/08-spec-reviews/round-1.md`. Reviewed: `issues/08-fallback-review.md` after the 2026-11-12 update, against main adceea8 and PR 87 (ref `zola/03-fallback-confined`, head f7892c2). Verdict: **NO-GO**, 5 findings; the brief's checks 3, 4, 5, 6 and 8 (heading decision, 08 to 06 handoff, SKILL.md sentences, the 13 round-null path, privacy of the text) produced no finding. Codex's answer is kept in the round file; findings in brief:

1. [P1] The Codex stderr tail in the comment passes `redact()` only: live Markdown, mentions and HTML survive.
2. [P1] The deadline test passes even without `fallback_timeout` in the deadline (an immediate fallback fits in the old one).
3. [P1] "`comment_body` gains the fallback variant" leaves its signature open; 07's test pins five parameters.
4. [P1] "Every case asserts the `claude` argv" contradicts the cases that assert an empty `claude` log.
5. [P2] 06 enables the fallback in `main()`, whose output still says "Codex review N".

## Settled (Solveig)

All five are right; none declined.

| # | Disposition | Where |
|---|---|---|
| 1 | Accepted. The stderr tail is published as an indented code block built like `findings_block` (last 5 lines, `redact`, `_written_out`, cut to 300), with adversarial tests (mention, link, image, HTML, fence, control character, token). | 08, heading box |
| 2 | Accepted. The deadline is asserted exactly on `_spawn`'s argument, and a second test with `REVIEW_CHAIN_SLACK` patched to 6 and a fallback that takes 3 s fails without `fallback_timeout` in the deadline. The slack stays 30 s and is stated to cover the chain's two `TERM_GRACE` stops. | 08, third box |
| 3 | Accepted. The five parameters keep their order; `fallback` is a keyword-only addition; the Codex path is byte-identical (test); `ReviewResult` gains `kind`. | 08, heading and verdict boxes |
| 4 | Accepted. Reworded to "every case that runs the fallback"; the other cases assert an empty `claude` log. | 08, tests box |
| 5 | Accepted. 06's `main()` box now words the line "Fallback review N" for `kind` `provisional`, reads `kind` from `ReviewResult`, with a test; `--help` says so. | 06 |

Confirmed in this round, as the dispatch asked: the fallback switch moved from 08 to 06 and nothing is left unowned (06's "No track, no provisional review" box sets `allow_fallback`; 08 leaves `main()` Codex-only). coverage.md R1 is marked "Pause-when, owner"; every R and finding mapping to 08 is intact.

Not done: a second Codex round. The fixes are Codex's own proposals; the code review of the build is where the ticket is looked at again.
