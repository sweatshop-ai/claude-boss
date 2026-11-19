# 48: NO-GO only for a serious defect, the reviewer starts from the diff

**What to build:** decisions 3 and 4 of `/home/tiroir/.claude/plans/2026-11-19-token-review-decisions.md` (owner's choice 2026-11-19: all A), in one PR on claude-boss, release 0.26.0.

- `boss_review.py` `build_brief` carries the V1 brief as measured on 2026-11-19: each finding is tagged `[SERIOUS]` or `[MINOR]`, NO-GO only when one is SERIOUS; the reviewer works from the diff and opens other files only for a specific concern, never a whole file over 300 lines. The benchmark measured exactly that text (25 rounds: 29% cheaper per review, one known serious bug fewer tagged SERIOUS out of 23).
- A GO with MINOR findings stays a GO: the worker fixes them in the same push and the PR merges with no new round.
- Ticket 46 (`--since SHA`) is part of this PR.
- The same rule in the `codex-review` skill, the boss SKILL.md and references, and the global `~/.claude/CLAUDE.md` section "One review round per PR".

**Blocked by:** None (can start immediately)

**Claimed by:** Rafael (2026-11-19)

**Status:** done (PR 159, merge eeb789b, 2026-11-19)

- [x] Test first: a review answer with only MINOR findings and `VERDICT: GO` is a GO; the brief carries the tag and diff-first rules
- [x] Ticket 46 done and merged in the same PR
- [x] Skill texts and the global CLAUDE.md say the rule
- [x] PR merged to main with green CI and one review round
