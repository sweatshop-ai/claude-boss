# 06: Provisional GOs are tracked in a list that survives restarts (index)

Split on 2026-11-12 (Lucia, task #06S) into two tickets, on Chiara's ruling on finding 11 of spec round 1 (`plan-review-codex-06-1.md`). The six boxes of the old 06 now live in exactly one of them (the old Tests box gave its removal rows to 06b's box, so the count stays six); this file holds none, so an old reference to "06" resolves here and a reference to a box resolves to the letter below.

What to build, in one line: every PR that holds only a provisional GO is kept in a durable list in the boss's tracker, written before the comment is posted, and removed once Codex has since said GO; the fallback goes on from the command line where the list exists. Re-reviewing the entries, the post-merge NO-GO and the release stop are 10.

| Ticket | What it holds | Old 06 box (by its first words) | Blocked by |
|---|---|---|---|
| [06a](06a-provisional-list.md) | The list write in `_keep_and_post`, `list-failed`, no track no provisional review, the `main()` switch with `--help` and the "Fallback review N" line, the SKILL.md sentence and its test, `track=` on the fallback tests, the smoke check | "When `boss_review.py` records a provisional GO", "**No track, no provisional review:**", "When `main()` passes `allow_fallback=True`", "Tests use real `git`" (without its removal rows) | 05a, 05c, 08, 14 |
| [06b](06b-prune-provisional.md) | `prune_provisional(track, repo)` and its three removal rules, with the removal rows of the tests | "A function `prune_provisional(track, repo)`" (and the removal rows of "Tests use real `git`") | 06a |

**Where other tickets point:** 10 calls `prune_provisional` (06b) and reads the list (06a's line format): it is blocked by 06b. 04's gate passes over a `list-failed` round (06a). Nothing in 04, 09 or 10 waits for 06a's switch alone: 09 runs beside 06a and 04's fallback fixture calls `review()` directly; any test that calls `review(allow_fallback=True)` passes `track=` (06a's box), and 04 and 10 are blocked by 22.

**Blocked by:** 06a, 06b (this file is an index; the work is in the two)

**Status:** done (06a and 06b are merged: PR 101, 53abb32, and PR 103, b045291).
