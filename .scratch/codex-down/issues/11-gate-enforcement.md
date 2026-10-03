# 11: The gate's test-only exception, its second door, and the skill text

**What to build:** 04's `boss_merge.py` decides and merges. This ticket makes three things around it true. The owner's standing rule that fixes after the last GO which touch only tests need no new review becomes executable (`--test-only-since`). `boss-run` refuses a hand-typed merge, so the boss's own other door is closed. And the skill names the command and states, in plain words, what the gate does not cover.

**Scope:** new on 2026-10-04, split out of the original 04 after Codex review 3 of the plan (findings 12, 15, 21, 23), with the owner-accepted premortem (R15, R25). Finding 21 (a listed branch that later starts to deploy) is accepted as a residual risk in `coverage.md`; this ticket's skill text names it. Why a skill text and not more code: no file in the repo can know whether a branch has since begun to deploy, and only branch protection on the repo closes a hand-typed merge, which the plugin cannot set.

**Blocked by:** 04 (The merge gate for deploying branches)

**Status:** ready-for-agent

The test-only exception (`test_paths` has its schema in 04):

- [ ] The existing exception (fixes after the last GO that touch only tests) is made executable: `boss_merge.py ... --test-only-since SHA` is honoured only when `SHA` matches `^[0-9a-f]{40}$` (it goes into an endpoint), is the head of a posted GO round of this PR (and that round passes 04's decision for the base), and every file changed between `SHA` and the live head matches an entry of `test_paths` (`fnmatch.fnmatchcase` patterns). The files come from `gh api repos/R/compare/<SHA>...<head>` with both the new name and the previous name of a rename counted. Without `test_paths`, with any other file, with a compare that fails, or with a page of 300 files (the API's limit) it is refused (3) and the `merges.jsonl` line says why. Tests for each, and one that shows the rule is not honoured on a deploying base for a provisional or waived round. Without this the gate would silently break the owner's standing rule

The other door (R15, finding 15):

- [ ] `skills/boss/bin/boss-run` gains a built-in hard rule named `PR merge outside boss_merge` with the pattern `(^|[[:space:]/])gh[[:space:]]([^&|;]*[[:space:]])?pr[[:space:]]+merge|pulls/[0-9]+/merge|mergePullRequest`, so global `gh` options (`--repo`, `-R`) and a path to `gh` do not hide a merge. Every test passes `--why`, since `boss-run` exits 2 without it (`skills/boss/bin/boss-run:207`). Tests: `gh pr merge 5 --merge`, `gh --repo o/r pr merge 5`, `gh -R o/r pr merge 5`, `/usr/bin/gh pr merge 5`, `gh api -X PUT repos/o/r/pulls/5/merge` and a `gh api graphql` call naming `mergePullRequest` all exit 5 with `--dry-run`; a `boss_merge.py` command line and `gh pr view 5` are not refused; every existing hard-rule test passes unchanged

The skill:

- [ ] `skills/boss/SKILL.md`, where the boss orders a merge (the paragraph that ends "no merge order is given on a GO that exists only in a message"), names `boss_merge.py` and its outcomes (0 merged, 3 and 4 refused, 5 failed or unverified, 7 a read failed) and `--test-only-since`. It states that a refusal (3 or 4) is an instruction to get the right review, not to work around it. It states three limits, each in one plain sentence: a `gh pr merge` typed by hand in a worker's or the owner's own shell is outside the gate, and only branch protection on the repo closes that, which the plugin cannot set; a base retargeted between the check and the merge is detected after the fact (exit 5, `base-changed`) and not prevented; the gate trusts the repo's `.boss/deploy.json`, so a listed branch that later starts to deploy is outside what the gate can see. A text test finds the command name and each of the three limits

Tests:

- [ ] Tests use 01's stub-directory harness with its PATH guard (`gh` and `boss-alert` stubs, a temp `CLAUDE_CONFIG_DIR` and `HOME`, `BOSS_TYPESAFE_ENV` pointing at a missing file): each test asserts its stub call logs and fails if `codex`, `claude` or `gh` resolves outside the stub directory [R25].
