# 25: Prune of the provisional list, edge cases found in review of 06b (class c and d)

**What to build:** the findings of Opus fallback review 3 on PR 103 (Codex was out of tokens) that were graded class c or d and filed instead of fixed.

**Blocked by:** 06b (Provisional entries are removed when Codex has since said GO)

**Status:** done (Tarek built it, PR 115)

- [x] **Round files that break the parser are kept, not raised (class c).** `_codex_rounds` (`boss_review.py`) lets a `ValueError` from `int()` on a round file named with over 4300 digits and a `RecursionError` from deeply nested JSON escape, which stops the prune of every entry of that repo for the pass. Catch both and keep that PR's entries. Test each. **Done for the `RecursionError`, with a test; declined for the 4300-digit name:** a file name is at most 255 bytes (`OSError: File name too long` at 4301 digits, tested), so `int()` never sees one.
- [x] **A round left empty after an OSError keeps its PR's entry for good (class c).** `_keep_and_post` says "round %d is left empty"; the prune keeps the entry (as the spec asks) but nothing ever clears it. Decide who clears it (10's recheck reviewing the PR, which writes a later round) and say so in 10's text. **Done:** the answer is that the next review of that PR clears it, since an empty round with a later round above it is skipped as a dead claim (tested; the newest round empty still keeps the entry). Ticket 10's text is not edited here (PR 106 owns it): its recheck needs no change, it writes a later round.
- [x] **Two tests prove less than they say (class d).** `test_a_held_tracker_lock_leaves_the_entry_and_says_so` and `test_a_gh_that_outlasts_the_io_timeout_keeps_the_entry` use `io_timeout=1` for the `gh` read too, so a slow stub can pass them without reaching the path; neither checks the stderr line. Give the lock test a long `gh` timeout and capture stderr in both. **Done for the lock test** (gh gets 30 s, only the tracker wait is cut to 1 s, stderr line asserted). **gh test:** the timeout is now seen to fire on `gh pr view`; its stderr check asserts silence, because `_live_state` says nothing and the ticket does not ask it to.
- [x] **A leaked descriptor in a test (class d).** `test_the_prune_takes_the_tracker_lock_and_never_the_prs` unlocks `fd` but never closes it. **Done** (the descriptor is closed).
- [x] **Two tracker shapes are untested (class d).** A CRLF tracker, and two identical lines of one entry. **Done**, both tested.
- [x] **Rule 2's boundary has no row (class d, Opus fallback review 4).** Add the row OPEN, live head B, entry `round=02`, rounds [(2, B, GO)]: a GO at the entry's own round does not remove. **Done**, row added.
