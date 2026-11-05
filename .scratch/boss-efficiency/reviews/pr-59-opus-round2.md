# PR 59 review, round 2 (Opus, read-only)

PR: sweatshop-ai/claude-boss #59, worktree `/home/tiroir/Projects/boss-plugin-wt-birgit-02`.
New commit: HEAD `3963e70` ("P6: keep the class a exception when rounds run out; name the stop
rule; dispatch gives sensitive"), `skills/boss/SKILL.md` +10/-6, on top of `c358feb`.
Round 1: `/home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/reviews/pr-59-opus-round1.md`.
Spec: `/home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/issues/02-graded-reviews.md`.

Merge state: `git diff origin/main...HEAD --stat` touches only `CHANGELOG.md` (+8) and
`skills/boss/SKILL.md` (+36/-5 net); `git merge-tree --write-tree origin/main HEAD` is clean
(VERIFIED). The two-dot diff against `origin/main` also shows reversions in `routines/` and
`.scratch/`; those are main's later commits (d0e6f33, f9c27a6, 77b58c3, a90a32b, d1ab68a,
c0ad790), not this PR, and none of them touches `SKILL.md` or `CHANGELOG.md` (VERIFIED).

## Round 1 findings: resolved or not

| Round 1 | What HEAD does | Status |
|---|---|---|
| F1 (b) no rule at the cap; collision with "No PR merges without a GO on record" | SKILL.md:598-599 adds "When the rounds run out, what is still open becomes a ticket and the PR merges, unless an open finding is of class a." (VERIFIED). The stop rule now says "it merges on its last GO" (SKILL.md:614, VERIFIED), which defers to the GO rule at :602 instead of contradicting it. Class a is wider than the old exception ("security or lost data", `origin/main` SKILL.md:600, VERIFIED): it also covers wrong behaviour on a normal path, so the change is conservative. | Resolved, with residual R2 (d) |
| F2 (b) "the PR closes" reads as `gh pr close` | Clarified in P6 only: SKILL.md:613-614 "the PR closes: it merges on its last GO, the open findings are not owed a fix" (VERIFIED). The dispatch text still ends "become tickets and the PR closes." (SKILL.md:867-868, VERIFIED), unchanged. CHANGELOG.md:9 has the same bare words (VERIFIED). | **Not resolved where a worker reads it**: R1 |
| F3 (b) no upper bound for under-100 rounds | Not addressed (SKILL.md:610 unchanged, VERIFIED). Was flagged as an owner clarification, not a deviation; spec wording identical. | Open, carried as residual, not blocking |
| F4 (d) dispatch lacks the sensitive definition | SKILL.md:865-867 now lists "login, auth, secrets, deleting or migrating data, anything on a production host, a CI workflow that runs an AI agent" and adds "in doubt it is sensitive" (VERIFIED). | Resolved, abridged: R3 (d) |
| F5 (d) "a security property" without "broken" | SKILL.md:863 "(a security property broken," (VERIFIED). | Resolved |
| F6 (d) "the stop rule below" unnamed | SKILL.md:613 "Every PR (the stop rule):" (VERIFIED); :611 "the stop rule below" now resolves by name. | Resolved |

New sentence SKILL.md:619-620 "The dispatch text in Phase B step 4 repeats these rules: change both
together." Target VERIFIED: the review text sits in Phase B (heading :839), item 4 (:847).

## New findings

**R1 (b). The dispatch still tells the worker "the PR closes", without the clarification P6 got.**
SKILL.md:867-868 (VERIFIED): *"Findings that are only tests, docs, style or far-fetched cases become
tickets and the PR closes."* The worker acts on the dispatch, not on P6; P6 is the boss's text. A
worker that ends its review loop under the stop rule can read this as "close the PR". The result is
a closed, unmerged PR: recoverable by reopening, but the work stalls until someone notices. This is
F2 left open in the one place it matters, and the commit's own new rule at :619-620 ("change both
together") is not followed for this phrase. Fix, a few words: "...become tickets and the review ends;
the PR merges on its last GO." Same edit is optional for CHANGELOG.md:9.

**R2 (d). Two edge cases of the merge rules stay unstated; neither produces a wrong merge.**
- A round that brings only c/d findings but ends in NO-GO, with no earlier GO (a small PR on round 1):
  the stop rule says "merges on its last GO" (:614) and there is none; the cap rule (:598-599) says it
  merges; :602 says no merge without a GO. Read either way, the outcome is one more round or a merge
  with tickets, both safe. Same shape as the old text for the cap case (`origin/main` :598-603,
  VERIFIED), so not introduced here. One clause would close it: "a round whose open findings are all
  c or d counts as a GO".
- An open class a at the cap: the text says the PR does not merge, not what happens next (owner?).
  The old text had the same gap.

**R3 (d). The dispatch's sensitive list is shorter than P6's.** P6 (:622-624, VERIFIED) has "access
rights", "secrets, including code that screens or redacts them", and "deleting, migrating or
overwriting stored data"; the dispatch (:865-866) drops "access rights" (arguably inside "auth"),
"code that screens or redacts" secrets, and "overwriting". The boss decides sensitive anyway and "in
doubt it is sensitive" is present, so a worker missing one only fails to raise it. Also the new
dispatch line at :865 is about 150 characters, longer than its neighbours (style).

## Contradictions in P6 or the Phase B dispatch

Read P6 (:590-626) and Phase B item 4 (:847-875) in full at HEAD. Numbers agree between the two (one
round / class a or b; up to three for 100-500 and for sensitive; split over 500), VERIFIED. The only
disagreement is R1 (dispatch lacks the "merges on its last GO" clarification). No other contradiction
found. Old flat rule "at most three rounds on one PR" is gone from SKILL.md (grep: only the
`origin/main` copy has it, VERIFIED).

## Summary

F1, F4, F5, F6 resolved. F2 resolved in P6 but not in the dispatch text a worker acts on (R1, class b,
one phrase). F3 still open as an owner clarification, not blocking. No class a finding. R2 and R3 are
class d and can become tickets.

VERDICT: NO-GO (R1 only; fixing the dispatch sentence at SKILL.md:867-868 makes it GO)
