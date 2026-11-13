# 49: Review by risk, written into the boss skill

**What to build:** The owner's decision (ANSWER q5, 2026-11-13) in `skills/boss/SKILL.md`:
1. Codex reviews once, and only PRs whose code touches gates, security, deploys or data.
2. Tests-only or docs-only PRs merge on green CI with at most one Opus pass.
3. A second review round only after a class a/b finding, never for class c/d.
4. After main is merged into a branch: no re-settle comment, no new review; the boss checks `git diff <reviewed> <final> -- <files>` is empty.
5. Re-measure on 2026-11-27: tokens, minutes and findings per PR.

Why: Codex re-reviews of 30 merged PRs found 6 real bugs, all in gate or security code; 31 runs at about 75k tokens each used up the weekly Codex quota.

**Status:** done

- [x] SKILL.md has a "Review by risk" section and the dispatch text repeats it
- [x] CHANGELOG.md (Unreleased) has the entry
- [x] `boss_review.py` unchanged

**Follow-ups (not fixed here):**
- `boss_review.py` has no notion of risk: it asks Codex for every PR it is run on, so rule 1 and 2 rest on the boss deciding not to run it (or accepting an Opus pass) for a docs-only or tests-only PR. A flag or a path-based check would enforce it.
- The size grades in "How many rounds" (under 100 lines: one round, 100 to 500: up to three) still stand beside the new rule; the new text says it overrides them where they differ. A later pass should fold them into one.
- Rule 4 has no command: the byte-identical check is by hand. No `re-settle` text exists in the code or skills today, so nothing was removed.
- `boss_merge.py` (Opus round 1 of PR 144): a PR with no usable GO is refused (exit 3), a provisional Opus GO merges only where the branch is marked non-deploying (exit 4), and a changed head passes only through `--test-only-since` with test paths. So rules 2 and 4 cannot merge on a deploying base until the gate learns a docs-only/tests-only class and a merge-of-main exception. The text now says so.
