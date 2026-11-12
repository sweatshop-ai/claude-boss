# 11: The gate's test-only exception, its second door, and the skill text (index)

Split on 2026-11-12 (Maja, on Chiara's ruling) into two tickets, accepting finding 12 of Codex spec round 1 (`plan-review-codex-04-10-11-1.md`): 11 did not fit one session. The four boxes of the old 11 now live in the ones named below, moved whole and not rewritten; this file holds none, so an old reference to "11" resolves here and a reference to a box resolves to the letter below.

What to build, in one line: 04's `boss_merge.py` decides and merges; 11 makes three things around it true: the test-only exception is executable, `boss-run` refuses a hand-typed merge, and the skill states what the gate does not cover.

| Ticket | What it holds | Old 11 box (by its first words) | Blocked by |
|---|---|---|---|
| [11a](11a-hard-rule-and-skill-text.md) | The `boss-run` hard rule `PR merge outside boss_merge`, the SKILL.md text with the three limits, the closing tests box | "`skills/boss/bin/boss-run` gains a built-in hard rule", "`skills/boss/SKILL.md`, where the boss orders a merge", "Tests use 01's stub-directory harness" | 04 (merged, PR 118) |
| [11b](11b-test-only-since.md) | `boss_merge.py --test-only-since SHA` and its rows | "The existing exception (fixes after the last GO that touch only tests)" | 04 (merged, PR 118) |

**Where other tickets point:** 11a's SKILL.md text names `--test-only-since`, which exists once 11b is merged. `coverage.md` R14 and R15 name 11's boxes by their first words; they resolve through the table above.

**Blocked by:** 11a, 11b (this file is an index; the work is in the two)

**Status:** ready-for-agent (11a, 11b)
