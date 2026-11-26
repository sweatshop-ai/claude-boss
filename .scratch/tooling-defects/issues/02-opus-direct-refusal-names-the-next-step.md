# 02: A refused `--opus-direct` names the review to run instead

**What happened (2026-11-26):** a worker ran `boss_review.py --opus-direct` on a content-only PR (site text files) into a
base that deploys a static site and has no `.boss/deploy.json`. It exited 5 with "no test_paths in the deploy list of
<base> (deploy list missing)". The worker then ran a plain Opus agent; that review was never recorded, so the merge
gate had no round to read.

**Diagnosis:** the refusal is right. The direct pass is review-by-risk rule 2, for PRs whose every file is a test or
narrow docs; content files are neither, and a base with no deploy list cannot say what a test is (fails closed). The
defect is that the refusal stops there: it does not say that the ordinary review with `--track` records a round, and
that while Codex is at its usage limit (`pm/reviews/codex-limit.json`) that review skips Codex and runs the same
confined Opus reviewer at once.

**What to build:** every `--opus-direct` refusal ends with the next step: the ordinary
`boss_review.py --repo R --pr N --checkout DIR --author NAME --track <your track>` of this PR, whether Codex is skipped for
its limit (and until when) or asked first, and that a plain Opus agent leaves no record. A missing or `test_paths`-less
deploy list says that only a base listing `test_paths` lets a tests-or-docs PR take the direct pass.

**Status:** done (this PR)

- [x] Tests: `test_boss_review_direct.py`, `TheRefusalSaysWhatToRunInstead`
- [x] SKILL.md, review-by-risk rule 2: what to do on a refusal
