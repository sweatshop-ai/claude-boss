# 52: `boss_review.py --opus-direct`: the Opus pass without asking Codex first

**What to build:** `skills/boss/boss_review.py --opus-direct` runs the confined Opus review straight away for a PR that changes only tests and narrow docs, so the owner's review-by-risk rule 2 stops spending Codex quota (follow-up of ticket 50).

**Status:** done

## Decisions

- **One classification, shared.** The flag refuses unless every file the PR changes is a test or narrow docs, asked of `boss_merge`'s own code: `read_deploy` (test_paths of the base), `read_compare` (the PR's files, base...head, a rename by both names) and a new `files_problem` that `docs_tests_problem` now calls too. `boss_review` imports `boss_merge` inside `_direct_problem` (boss_merge imports boss_review, so a top import would be a cycle). The refusal is exit 5 with the files named; nothing is claimed, posted or logged.
- **Fail closed.** No deploy list or no `test_paths`, a compare that failed, gave no JSON, no file list, was cut short (300), is not the PR's own status, or lists no file: all refuse, each says why.
- **The chain learns `--skip-codex`.** `run_chain(skip_codex=True)` / `reviewer_chain.py --skip-codex` start no Codex and ask the fallback alone (one attempt); it needs a fallback. `_sound(direct=True)` accepts exactly one attempt, Opus's, and a Codex attempt in a direct run is a contradiction (exit 7).
- **The round** is `kind: provisional`, `reviewer: opus`, bound to the head and base, with the Opus attempt in the record, plus `review: "opus-direct"`. `decide` therefore reads it as any provisional GO (`deploying-base` on a deploying base, which is rule 2's entry point).
- **Not a Codex failure, not a loan.** The Opus attempt is not appended to `attempts.jsonl` (Codex's health counts that file), the Codex health is not synced, and the GO is posted unlisted: no `## Provisional GO` line, so `boss_recheck` owes no Codex re-review (rule 2 wants none). A refused or unreadable answer is not logged either.
- **The comment** is headed `Direct Opus review N (<model>, review by risk, not a fallback; run by <author>)`, says `Verdict: provisional GO` for a GO, and ends with that Codex was not asked and no re-review is planned.
- **No `--track`**, no `--waive`, no `--check-fallback` with it (exit 2); the API raises `ValueError` for `track` or `allow_fallback`.

## Done when

- [x] Tests first: `test_boss_review_direct.py` (review, record, gate reading, comment, refusals, `_sound`, command), `SkipCodex` and a Cli test in `test_reviewer_chain.py`, `files_problem` in `test_boss_merge.py`
- [x] CHANGELOG (Unreleased), SKILL.md rule 2
- [x] CI green (1513881), review round recorded (round 1, provisional Opus GO on 0028f9e)
