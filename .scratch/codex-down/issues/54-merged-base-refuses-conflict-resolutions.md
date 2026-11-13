# 54: `--merged-base-since` refuses a merge that resolved a conflict in a PR file

**What to build:** close the open defect of the Codex recheck of PR 146 (`skills/boss/boss_merge.py`, rule 4) and confirm the three PR 145 findings are fixed on main.

**Status:** done

## The defect

Both the GO'd head and the base changed a PR-owned file X. Main is merged into the branch and the conflict is resolved by keeping the reviewed text. X is then identical in the GO'd head and the live head, so it is absent from `SHA...head`, while both ownership compares (`base...head`, `base...SHA`) still list it. The sets match, nothing refuses, and the merge into the base discards the base's change to X.

## Decision

Refuse whenever the base changed a PR-owned file after it left the GO'd head: read `SHA...base` (what the base changed since the merge-base of the GO'd head and the base) and refuse if any name in it, a rename by both names, is in the union of the PR's own files at both heads (`pr-file-changed-on-base`).

Why it is sound: a merge conflict in X needs both sides to have changed X. The PR side changed X (it owns it); if the base did not, the merge cannot conflict on X, and a clean merge leaves X as the GO'd head had it, which `SHA...head` already proves. So the only way to lose a base change to a PR-owned file is a file in both sets, and that is the refusal. It fails closed: a failed, truncated (300 files) or unreadable compare refuses; `behind` or `identical` (a base that has not moved) lists nothing and passes. The check also covers resolutions that took the base's text or mixed the two (those show up in `SHA...head` and refused already), so it adds the one case nothing else saw.

Rejected: reading the merge commit's conflict markers or its second-parent diff (the compare endpoint does not list a merge's conflicts, and a per-commit read is another API surface to trust); comparing file contents at the GO'd head and the live head one by one (a new contents read per file, and it still does not know what the base changed). Cost: a PR file the base touched, even with a clean merge, gets the diff check by hand; a base that moved 300 files or more refuses too.

## The three findings of PR 145 round 4

Fixed by ticket 51 (merged, PR 146), each pinned by a test in `skills/boss/test_boss_merge.py`:

1. CI green after one success: `required_checks` in `.boss/deploy.json`, every one must have succeeded; `DocsTestsOnly` tests for required checks and for none listed.
2. Rules 2 and 4 combining on a deploying base: `MergedBase.test_a_docs_tests_only_pr_with_a_provisional_go_that_merged_main_merges_on_a_deploying_base` and `test_the_combination_keeps_every_condition_of_both_rules`.
3. Empty owned-file sets: `MergedBase.test_a_pr_that_owns_no_file_at_either_head_refuses_whatever_the_status` (`pr-owns-nothing`, `compare-no-files`).

## Done when

- [x] Tests first, red, then green (`MergedBase`: the base changes a PR file, a rename, a base that has not moved, an untrusted base compare, the combination)
- [x] CHANGELOG (Unreleased), SKILL.md rule 4
- [ ] Codex GO on the PR (recorded in the PR)
