# 51: Follow-ups of the round-3 review of ticket 50 (merge gate, review by risk)

**What to build:** fix the findings left open on PR 145 (ticket 50, merged as 829e978) in `skills/boss/boss_merge.py`.

**Status:** done

## Decisions

1. **An empty own-files list is refused whatever the status.** `read_compare` refused "ahead and no file" only; it now refuses an empty list for every status but `identical` (`diverged` too). `merged_base` also refuses an empty list at either head, `identical` included (`pr-owns-nothing`), at the GO'd head too: a PR that owns nothing has nothing the compare can prove unchanged.
2. **CI is "every check the repo declares has succeeded", not "every check that exists now".** A list of the runs that exist at the moment cannot see a workflow that has not started or a dependent job not yet created, and nothing on the head says which runs are still to come. The rule is the base's `.boss/deploy.json` key `required_checks` (check-run names): each must be among the head's runs, `completed` and `success`; every run that exists must still be green, and one success at least. Fail closed: no key, or an empty list, means rule 2 does not apply (exit 4, said in the note); a non-list or non-string value makes the file invalid (every branch deploying), like `test_paths`. Rejected: branch protection's required checks (an admin-scoped read the boss's token may not have, and a second source of truth); the checks that ran on the base's head (a path-filtered workflow legitimately skips on a docs PR, so it would refuse good PRs and still not know what is yet to start); the combined status (legacy statuses only, Actions does not write there). Cost: a repo must list its checks once before it gets rule 2; this repo's own `main` does not deploy, so it is unaffected.
3. **Rules 2 and 4 combine.** A docs/tests-only PR with a provisional GO that later merged main is exactly the case both rules were written for, and refusing it made the boss do the diff check by hand with no gate. In `merged_base`, a provisional GO that `decide` refused as `deploying-base` continues through the merge checks (which prove the PR's files are the same at both heads), then needs the PR's own files at the live head to be docs and tests and the required checks to have succeeded on the live head (`docs_tests_problem`, shared with rule 2). A waived GO never qualifies. Exit 4 with the reason when the docs/tests part fails, 3 when a merge check fails.
4. **`%2F` works.** Checked read-only: `gh api repos/sweatshop-ai/claude-boss/compare/feat%2F02-pr-review...main` and the unencoded form both answered `diverged`, 700 commits. No code change; a test now pins the encoded path for `release/1.0`.
5. **SKILL.md rules 2 and 4** say what the code does: `required_checks`, the "owns at least one file" condition, which GO kinds the merged-base flag accepts on a deploying base, and that a merge that resolved a conflict in a PR file is refused and gets the manual diff check.

## Done when

- [x] Tests first, red, then green: DeployList (`required_checks` parse and bad values), DocsTestsOnly (required checks, none listed), MergedBase (owns nothing at either head and every status, slash base, the combination and its refusals, waived)
- [x] CHANGELOG (Unreleased), SKILL.md rules 2 and 4
