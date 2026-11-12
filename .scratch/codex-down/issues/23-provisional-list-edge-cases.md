# 23: Provisional list edge cases found in review of 06a (class c and d)

**What to build:** the two findings of Codex round 1 on PR 101 (`06a-reviews/round-1.md`, 2026-11-12) that were graded class d and filed instead of fixed. Neither breaks a security property, loses data or misbehaves on a normal path.

**Blocked by:** 06a (Provisional GOs are written to a list that survives restarts, and the fallback goes on)

**Status:** done (Aisha built it, PR 113)

- [x] **The unusable-track line is said once (class d, [P1] of round 1).** With `--track T` naming a missing file, a symlink or a directory and Codex absent, `review()` calls `usable_tracker` once (`boss_review.py` :1187) and `_sync_health(track)` (:1230, :1214, :1227) reaches `codex_blocker.sync`, which calls it again (`codex_blocker.py` :114): "no blocker can be raised" reaches stderr twice. Resolve the track once in `review()` and hand `_sync_health` the result (or `None`), then make `test_a_track_that_is_missing_a_symlink_or_a_directory_does_the_same` count the line, not only look for it (`test_boss_review_list.py` :305).
- [x] **`PROV_LINE` is as strict as the contract (class c, [P2] of round 1).** The pattern (`boss_review.py` :967) accepts a repo without an `owner/repo` shape, a head of any hexadecimal length, a round of any length and any non-space `at=`, so a hand-edited `- [prov owner/repo#5] head=a round=1 base=main at=x` counts as an entry and is replaced as a same-tag line. Tighten it to what `_with_entry` writes (`owner/repo`, a 7 to 40 character head, a two-digit round, an ISO `at=`) and add a test that a malformed line is left alone. 06b's parser reads the same form: change both together.
- [x] **The kept entry of an unreadable PR is tested (class d, Codex's note on Ronja's judgement call).** 06a ends a round whose PR cannot be read after the list write as `post-failed`, exit 7, with the entry kept (the spec was silent; Codex and Joaquin agree: a kept entry is rechecked by 10, a dropped one is a provisional GO nobody revisits). Only the failing-comment path is tested (`test_boss_review_list.py` :235). Add a test where the stub `gh pr view` fails on its second call: status `post-failed`, exit 7, the entry still in the tracker, nothing posted. Say in 06b's and 10's text that an entry means "must recheck", not "a comment exists".

**Built (Aisha, 2026-11-12):**

- Box 1: `review()` calls `usable_tracker` once whenever `track` is given and hands `_sync_health(track, tracker_path)` the result; a `None` skips the sync. `codex_blocker.sync` keeps its signature (05c's tests record it by name), and its own call is silent for a usable track. `test_a_track_that_is_missing_a_symlink_or_a_directory_does_the_same` counts both lines (one each).
- Box 2: `PROV_LINE` is `owner/repo` (`[A-Za-z0-9._-]+/[A-Za-z0-9._-]+`), head `{7,40}`, round `{2}`, `at=` an ISO 8601 time with `Z` or an offset. 06b's parser is the same `_entry_of`, so one change covers both. Tests: eight malformed lines are no entry and are not replaced; the 7-character head and the offset are entries.
- Box 3: `test_a_pr_that_cannot_be_read_after_the_write_keeps_the_entry_and_posts_nothing`.

**Declined, with evidence:** the sentence "an entry means must recheck, not a comment exists" is not written into `06b-prune-provisional.md` and `10-recheck-and-release-stop.md`: open PR 106 edits both files (and 04, 06, 06b, 09c, 10, 11, 22, 27) and the instruction for this build was not to touch them. It is in `CONTEXT.md` under "Provisional entry" instead; whoever lands after 106 can point those two tickets there.
