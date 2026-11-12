# 09: The owner's choice, and the waiver (index)

Split on 2026-11-12 (Astrid, task #09S) into three tickets after Codex spec round 1 (`plan-review-codex-09-1.md`, finding 13, and Chiara's ruling of that day). The boxes of the old 09 now live in exactly one of them; this file holds none, so an old reference to "09" resolves here and a reference to a box resolves to the letter below.

What to build, in one line: when the `Codex down` blocker (05c) is open, the owner chooses once what to do (wait, accept the fallback review, or merge on tests alone), the choice is kept under the blocker's id, and "merge on tests alone" is only ever `boss_review.py --waive`, which records a `waived` round when the owner chose it, the tests pass and the head has not moved. 04's gate lets a waived round merge only on a branch the repo lists as non-deploying. A waived merge is the owner's explicit acceptance of no review; it is not put on 06's list and Codex does not re-review it.

| Ticket | What it holds | Old 09 box (by its first words) | Blocked by |
|---|---|---|---|
| [09a](09a-hand-clear-holds.md) | A hand clear holds until a later failure is logged (`health()` gains `last_ts`; `sync` compares it with the newest `cleared=`) | new (20's class b) | 05c (merged) |
| [09b](09b-owner-choice.md) | The choice record, its writer and reader in `codex_blocker.py`, the concierge ask for wait / accept the fallback | "One record for all three answers", "`skills/boss/SKILL.md` says: when a `Codex down` blocker is open" | 05c (merged), 08 (merged) |
| [09c](09c-waiver.md) | `boss_review.py --waive`, `policy.WAIVE_TEST_TIMEOUT`, the own-turn `CONSENT:` for tests alone, the third option and the `--waive` instruction in SKILL.md | "`boss_review.py --waive ...`", "Tests use 01's stub-directory harness" | 09b |

09a and 09b are independent and can be built side by side; 09b's reader reads the open blocker through `_classify`, which 09a does not change. 09c needs only 09b's `choice(track)` result and record grammar.

**Where other tickets point:** 04's gate and its end-to-end test read the record `--waive` writes, so 04 is blocked by 08 and 09c; 11 stays blocked by 04; `coverage.md` findings 4 and 7 name 09b and 09c.

**Blocked by:** 09a, 09b, 09c (this file is an index; the work is in the three)

**Status:** ready-for-agent (09a, 09b, 09c)
