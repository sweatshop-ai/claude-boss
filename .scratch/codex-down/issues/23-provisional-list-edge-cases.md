# 23: Provisional list edge cases found in review of 06a (class c and d)

**What to build:** the two findings of Codex round 1 on PR 101 (`06a-reviews/round-1.md`, 2026-11-12) that were graded class d and filed instead of fixed. Neither breaks a security property, loses data or misbehaves on a normal path.

**Blocked by:** 06a (Provisional GOs are written to a list that survives restarts, and the fallback goes on)

**Status:** ready-for-agent

- [ ] **The unusable-track line is said once (class d, [P1] of round 1).** With `--track T` naming a missing file, a symlink or a directory and Codex absent, `review()` calls `usable_tracker` once (`boss_review.py` :1187) and `_sync_health(track)` (:1230, :1214, :1227) reaches `codex_blocker.sync`, which calls it again (`codex_blocker.py` :114): "no blocker can be raised" reaches stderr twice. Resolve the track once in `review()` and hand `_sync_health` the result (or `None`), then make `test_a_track_that_is_missing_a_symlink_or_a_directory_does_the_same` count the line, not only look for it (`test_boss_review_list.py` :305).
- [ ] **`PROV_LINE` is as strict as the contract (class c, [P2] of round 1).** The pattern (`boss_review.py` :967) accepts a repo without an `owner/repo` shape, a head of any hexadecimal length, a round of any length and any non-space `at=`, so a hand-edited `- [prov owner/repo#5] head=a round=1 base=main at=x` counts as an entry and is replaced as a same-tag line. Tighten it to what `_with_entry` writes (`owner/repo`, a 7 to 40 character head, a two-digit round, an ISO `at=`) and add a test that a malformed line is left alone. 06b's parser reads the same form: change both together.
