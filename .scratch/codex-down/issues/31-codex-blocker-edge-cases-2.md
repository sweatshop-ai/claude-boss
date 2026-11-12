# 31: Codex down blocker, edge cases found in the review of 20 (class c and d)

**Blocked by:** 20

**Status:** ready-for-agent

Found by the fallback review of PR 110 (`20-reviews/round-1.md`, GO). No round blocked on them.

- [ ] Class c: `_is_cd` (`codex_blocker.py:97-103`) strips quoted values with `"[^"]*"`, which pairs quotes left to right. A hand-edited broken marker with `id=` after a stray quote (`[ladder t0=bad ask="say "hi" id=cd261112090000 next="x"]`) loses its `id=`, is not counted as broken, and the next down sync raises a second blocker beside it. `render_marker` writes `id=` first, so this needs a hand reorder and an unbalanced quote. Decide: leave, or look for `id=cd` before the first quote as well as after the strip. A hand typo such as `id=cd261112090000x` is no longer seen as a cd line either (it was by the old regex).
- [ ] Class d: `Edges.test_a_symlink_swapped_in_after_the_check_is_not_written_through` and the `tracker.update` docstring say "not a write through it"; the old code never wrote through the link, it read the target and turned the link into a regular file (`os.replace`). Reword the test name and docstring to say that; the test still fails on a revert, through the stderr and alert asserts.
- [ ] Class d: `Edges.test_a_hand_written_empty_cleared_is_open_and_the_next_up_sync_clears_it` and `test_a_cd_id_in_the_markers_own_field_is_still_a_broken_cd_line` pass on main too; they pin behaviour that exists. Say so in their docstrings.
