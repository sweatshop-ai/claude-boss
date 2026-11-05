# PR 59 review, round 1 (Opus, read-only)

PR: sweatshop-ai/claude-boss #59, branch in `/home/tiroir/Projects/boss-plugin-wt-birgit-02`,
head `c358feb` ("Reviews graded by risk and size (ticket 02)"). Diff `git diff origin/main..HEAD`:
`CHANGELOG.md` +8, `skills/boss/SKILL.md` +32/-5.
Spec: `/home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues/02-graded-reviews.md`.

## 1. Rules, classes, sensitive, who decides: against the spec

| Item | Spec | PR (SKILL.md) | Result |
|---|---|---|---|
| Under 100, not sensitive | one round; another only for class a or b | line 609, same words | VERIFIED match |
| 100 to 500, not sensitive | up to three, stop rule below can end earlier | line 610, same words | VERIFIED match |
| Sensitive | "today's regime, up to three rounds" | line 611 "up to three rounds" | VERIFIED; "today's regime" dropped, correct since the old text is gone |
| Every PR, only t/d/s/far-fetched → tickets, PR closes | same | line 612, same words | VERIFIED match |
| Over 500 | split before review | line 613, same words | VERIFIED match |
| Standards review once per PR | same | line 614, adds "(`code-review`)" | VERIFIED match |
| Classes a/b/c/d | codebook text | lines 616-619 | VERIFIED word for word (bold labels only) |
| Sensitive definition (five items) | login/auth/access; secrets incl. screening/redacting; delete/migrate/overwrite stored data; production host; CI workflow running an AI agent | lines 621-623 | VERIFIED word for word |
| Who decides | boss, per PR, from ticket and file paths, at review time, recorded on PR; worker may raise, never lower; in doubt sensitive | lines 624-626 ("You decide it", "You" = the boss throughout SKILL.md) | VERIFIED match |
| Addition not in spec | "Added lines are those of the PR's diff." (line 607) | | harmless clarification |

All numbers (100, 500, three, one) match. No wording drift found.

## 2. Dispatch sentence (Phase B step 4, SKILL.md lines 859-865)

Agrees with P6 on every number and on who decides. About 90 words, one quoted block, copyable.

## Findings

**F1 (b). The cap now has no "what happens at the cap" rule, and it collides with "No PR merges without a GO on record".**
The PR deleted (old lines 597-599, VERIFIED in the diff) "After the third, what is still open becomes a ticket and the PR merges, unless an open finding is about security or lost data." Line 601 still says "No PR merges without a GO on record" (VERIFIED). So:
- a sensitive or 100-500 PR whose third round is still NO-GO on an a or b finding: the text says nothing (merge? block? escalate?). The old security/data-loss exception is gone with no replacement;
- a PR whose round returns NO-GO with only class d findings: line 612 says the findings become tickets and "the PR closes", while line 601 forbids a merge without a GO.
The spec does not settle this either; it is a gap the old text covered. Suggest one sentence: at the cap, open c/d become tickets and the PR merges on the boss's call; an open a (or any open finding on a sensitive PR) blocks and goes to the owner. That is an owner decision, so raise it rather than invent it.

**F2 (b). "the PR closes" reads as `gh pr close` (close without merging).**
Line 612 and the dispatch (line 865) both say "the PR closes" (VERIFIED). In GitHub vocabulary a closed PR is an abandoned one. A worker taking the dispatch literally can close an otherwise good PR. The spec uses the same words, so this is faithful to it; the meaning intended (review stops, PR proceeds to merge) should be spelled out: "the review ends and the PR goes to merge".

**F3 (b). "Another only if it finds a defect of class a or b" has no upper bound for small PRs, and meets the re-run rule.**
Read literally (line 609), each round that finds an a or b buys another round, without limit, so a small PR can run longer than a sensitive one capped at three. Separately, line 599-600 (VERIFIED) requires "one more run" after fixes made after the last GO; it is not said whether that run counts toward the one-round allowance. Spec wording is identical, so again a clarification for the owner, not a deviation.

**F4 (d). The dispatch tells the worker it may raise "sensitive" but not what sensitive means.**
Lines 862-863 (VERIFIED): "I decide sensitive and record it on the PR; you may raise it, never lower it." The five-item definition and "in doubt, it is sensitive" are not in it. A worker cannot raise what it cannot recognise. Adding the five items costs one line.

**F5 (d). Dispatch class a wording.** Line 860: "(a security property, data loss, ...)" lacks "broken"; "a security property" alone is not a defect. One word.

**F6 (d). "the stop rule below" (line 610) points to an unnamed rule.** The intended target is line 612 ("Every PR: when a round brings only ..."), which is below and is the only stop rule, but nothing names it "stop rule". VERIFIED it resolves; not broken. Could read "the last-but-one rule" or name line 612 "Stop rule:". Same text as the spec. Line 598 "(below)" resolves to the new section: VERIFIED.

**F7 (d). Leftover old rule in a tracked handoff.** `handoff-Otilia-2026-11-04.md:15` (tracked, VERIFIED via `git ls-files`) says "At most 3 rounds". It is a dated handoff, not a rule; no change needed, noted for completeness.

## 3. Old "three rounds" rule elsewhere

Grepped `skills/`, `routines/`, `README.md`, `CONTEXT.md`, `skills/boss/references/` for three rounds / 3 rounds / third / at most three / up to three / twelve / Codex / review / round:
- `skills/boss/references/boss-goal-review.md:21` "At most three `MISSING:` lines": unrelated (objective review format). VERIFIED.
- `skills/boss/references/objective.md:127`: unrelated example. VERIFIED.
- `README.md:33` "three review lenses": unrelated. VERIFIED.
- `routines/boss_efficiency_core.py`: classifies tool calls as review, no rule. VERIFIED.
- `skills/boss/SKILL.md` P14 (lines 734-741), P15 merge gate (line 763-764 "every review GO"): no round count; consistent except as noted in F1.
- Hard rules list (lines 994-1014) and table (line 954): no review-round rule. VERIFIED.
No remaining statement of the old rule as a rule. NOT FOUND anywhere else.

## 4. Cross-references

"(below)" line 598: VERIFIED. "the stop rule below" line 610: resolves (F6). Section is P6 (heading line 545, VERIFIED), as the CHANGELOG says. "references/models.md" in step 4 untouched.

CHANGELOG entry matches the SKILL.md change. VERIFIED.

## Summary

No a-class finding. The text is a faithful copy of the spec. Three b findings (F1-F3) are gaps in the rule set itself, inherited from the spec or opened by deleting the old "after the third" sentence; F1 is the one a worker or the boss will hit on a normal day (a NO-GO with only d findings, versus "No PR merges without a GO on record"). F1 and F2 should be settled before merge, because they change what a worker does with its PR; both need a one-line owner call.

VERDICT: NO-GO
