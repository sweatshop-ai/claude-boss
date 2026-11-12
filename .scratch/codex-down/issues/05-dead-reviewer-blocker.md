# 05: A dead reviewer becomes an open blocker (index)

Split on 2026-11-12 (Joaquin, task #05X) into three tickets, on Chiara's ruling on finding 12 of spec round 1 (`plan-review-codex-05-1.md`). The eight boxes of the old 05 now live in exactly one of them; this file holds none, so an old reference to "05" resolves here and a reference to a box resolves to the letter below.

What to build, in one line: after N failed Codex attempts in a row the boss's tracker gets an open blocker "Codex down" that the ladder escalates without a boss turn, and it clears after M answered attempts in a row. How the owner is asked, and what the owner's answer allows, is 09.

| Ticket | What it holds | Old 05 box (by its first words) | Blocked by |
|---|---|---|---|
| [05a](05a-tracker-writer.md) | The tracker writer: `tracker.update`, `tracker.add_line`, `tracker.mark_cleared` | "`tracker.py` gains `update(path, fn, deadline)`" | nothing (02 is merged) |
| [05b](05b-policy-and-codex-health.md) | `CODEX_DOWN_AFTER`, `CODEX_UP_AFTER` and `codex_health.py` | "`policy.py` gains `CODEX_DOWN_AFTER = 3`", "`skills/boss/codex_health.py` derives the state" | 05a, 08 |
| [05c](05c-raise-and-clear-the-blocker.md) | `track` and `--track` of `review()`, the raise, the clear, the ladder test, the test harness | "`review(..., track: str \| None = None)`", "When the state is down", "After the write a test runs", "Clearing:", "Tests use 01's stub-directory harness" | 05b |

**Where other tickets point:** 06 and 10 call `tracker.update` and `tracker.add_line` (05a) and 06's and 10's `track` rule and health sync are 05c's `review()` box; 09a extends `codex_health.py` (05b), 09b writes with `tracker.update` (05a) and needs the blocker and its id (05c); 04 and 13 name `BOSS_ALERT` and the attempts counter (05c, 05b).

**Blocked by:** 05a, 05b, 05c (this file is an index; the work is in the three)

**Status:** done (05a, 05b and 05c are merged).
