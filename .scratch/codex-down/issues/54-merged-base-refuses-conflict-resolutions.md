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

## Round 2: the base can move between the check and the merge (Chiara, 2026-11-13)

Codex round 1 (NO-GO, 82,323 tokens): the compares used the branch name `main` and `gh pr merge` pins only the head, so a base that advances after the check and touches a PR file merges unchecked. Judged class c: GitHub merges the head into the base as a 3-way merge, so a later base change either merges cleanly and is kept, or conflicts and leaves the PR unmergeable; nothing is silently dropped (the drop in the defect above needs the conflict resolved inside the head, which is pinned). The blockers on PR 145 and 146 only clear on a Codex GO, so the window is narrowed anyway (the owner's decision, which does not change the rule that a second round follows a class a or b finding):

1. `merge` reads the base branch's tip once (`gh api repos/R/git/ref/heads/<base>`), records it in the `merges.jsonl` line (`base_sha`) and makes every compare against that sha (`base...head`, `base...SHA`, `SHA...base`), not the name. The deploy list is still read by branch name.
2. Right before `gh pr merge` (and before the "merging" intent line) it reads the tip again; a different sha refuses with `base-moved` (exit 3, nothing merged), and the next run re-checks.
3. After the merge, the post-merge check reads the merge commit's first parent; if it is not the recorded sha, or cannot be read, `boss-alert` says which PR, both shas and that the owner must check by hand (`base-moved-during-merge`, `unverified`, exit 5). A merge cannot be undone, but it is not silent.
4. Tests: class `BaseTip` in `test_boss_merge.py` pins each step.

**Accepted window:** between the second read and the merge there are milliseconds. A base that moves in it is merged by GitHub as a 3-way merge, which keeps the base's change or refuses on a conflict, never drops it, and step 3 reports it afterwards. Closing it entirely needs a merge call that pins the base, which `gh pr merge` does not offer.

## Rounds 3 and 4: the gate refuses merge queues and has no undo (Chiara, 2026-11-13)

Codex round 2 (NO-GO, 85,430 tokens): on a merge-queue base `gh pr merge` returns success after enqueueing, so the merge could complete later on a base tip nobody compared. Round 3 added `gh pr merge --disable-auto` plus a read-back. Codex round 3 (NO-GO, 103,122 tokens) showed it promised what it cannot keep: `--disable-auto` does not remove a PR already in a merge queue (GitHub documents it), my stub cleared `inQueue` and hid that, and the undo ran only after a successful command and a readable `pr view`, not after a timeout or an unreadable view. The undo is removed, with its tests, rather than patched. Chiara lifted the 3-round cap for this PR because it removes code.

- **Merge queues are not supported: the gate always refuses them, before `gh pr merge`.** `queue_problem` reads `repos/R/rules/branches/<base>` (a rule of type `merge_queue` refuses) and one GraphQL query (`repository.mergeQueue(branch)`, which also covers legacy branch protection, and the PR's `autoMergeRequest` and `isInMergeQueue`). A queue, an auto-merge request or a queue entry refuses with `merge-queue-unsupported` (exit 3); anything that cannot be read refuses with `gh-read-failed` (exit 4). A dry run asks the same, and no "merging" line is written for a refusal.
- **Why nothing can be left scheduled.** The gate never passes `--auto` (a test pins the argv of every `gh pr merge` and the source). Without `--auto`, on a base with no merge queue, `gh pr merge --merge --match-head-commit` either performs the merge or fails; it has no mode that schedules a merge for later. The checks above ran in the same lock before the call, and a PR with no auto-merge request and no queue entry gets none from this call. So on a timeout, an unreadable `pr view` or a PR that is not MERGED afterwards, the gate refuses (`merge-timeout`, `unverified`, `merge-not-completed`, exit 5) and alerts "check by hand", and does not try to undo anything: there is nothing scheduled to undo, and what may have been merged is for the owner to see.
- Tests: class `MergeQueue` (a merge_queue ruleset, a queue on the branch, auto-merge on, in the queue, every unreadable answer, dry run, never `--auto`, no undo). The stub is honest: a queue base is refused before the merge, and nothing clears a queue flag.

## Done when

- [x] Tests first, red, then green (`MergedBase`: the base changes a PR file, a rename, a base that has not moved, an untrusted base compare, the combination)
- [x] CHANGELOG (Unreleased), SKILL.md rule 4
- [ ] Codex GO on the PR (recorded in the PR)
