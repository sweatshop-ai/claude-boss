# 11b: The gate's test-only exception (`--test-only-since`)

**What to build:** `boss_merge.py ... --test-only-since SHA`: the owner's standing rule that fixes after the last GO which touch only tests need no new review, made executable.

**Scope:** split out of 11 on 2026-11-12 (Maja, on Chiara's ruling that accepts Codex spec finding 12 of `plan-review-codex-04-10-11-1.md`). The one box below was moved from 11 whole, not rewritten; 11's original scope paragraph follows, unchanged, because it states what the box cites. The `boss-run` rule and the SKILL.md text are 11a's; the SKILL.md text names this flag.

**Scope:** new on 2026-10-04, split out of the original 04 after Codex review 3 of the plan (findings 12, 15, 21, 23), with the owner-accepted premortem (R15, R25). Finding 21 (a listed branch that later starts to deploy) is accepted as a residual risk in `coverage.md`; this ticket's skill text names it. Refreshed 2026-11-12 (Basil, spec round 1 of 04, 10 and 11) against `main` 08dfd71: nothing of this ticket exists yet (`boss_merge.py` is 04's), `boss-run`'s `--why` check is at :229 and its hard-rule list is the heredoc in `hard_rules()` (:86-100), matched by `check_hard_rules` (:101) with `nocasematch` against `FLAT="$*"` (:239), and SKILL.md already names `boss_merge.py` in a sentence that is ahead of the code (:675, "which `boss_merge.py` decides"): this ticket's text must agree with them. Why a skill text and not more code: no file in the repo can know whether a branch has since begun to deploy, and only branch protection on the repo closes a hand-typed merge, which the plugin cannot set.

**Blocked by:** 04 (The merge gate for deploying branches; merged, PR 118, 9fa994e). 11a is independent and can be built side by side.

**Status:** ready-for-agent

The test-only exception (`test_paths` has its schema in 04):

- [ ] The existing exception (fixes after the last GO that touch only tests) is made executable: `boss_merge.py ... --test-only-since SHA` is honoured only when `SHA` matches `^[0-9a-f]{40}$` (it goes into an endpoint), is the head of a posted GO round of this PR (and that round passes 04's `decide(rounds, SHA, live base, non_deploying)`, the same function with `SHA` as the head, so a provisional or waived GO that a later round of any status supersedes (22) does not qualify (04 settles the precedence: a Codex GO with a provisional or waived GO above it on the same head is refused `superseded-go`, one more test row here), and neither does a provisional or waived GO on a deploying base), and every file changed between `SHA` and the live head matches an entry of `test_paths` (`fnmatch.fnmatchcase` patterns). The files come from `gh api repos/R/compare/<SHA>...<head>` with both the new name and the previous name of a rename counted. The compare must answer `status` `ahead` or `identical` (`behind` and `diverged`, a force-push, refuse). Without `test_paths`, with any other file, with a compare that fails, or with a page of 300 files (the API's limit) it is refused (3) and the `merges.jsonl` line says why. Tests for each, one that shows the rule is not honoured on a deploying base for a provisional or waived round, and one where a later round (`head-moved`) on the new head supersedes a provisional GO on `SHA`, so the exception is refused (3, `superseded-go`) but a `codex` GO on `SHA` still allows. Without this the gate would silently break the owner's standing rule

Tests (the closing box of 11, which holds for this half as it does for 11a; its harness is 11a's last box):

- [ ] Tests use 01's stub-directory harness with its PATH guard, as 11a's last box says: each test asserts its stub call logs and fails if `codex`, `claude` or `gh` resolves outside the stub directory [R25].
