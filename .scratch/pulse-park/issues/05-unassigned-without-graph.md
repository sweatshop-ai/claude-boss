# 05: Unassigned work on tracks without a ticket graph

**What to build:** on a track without a ticket graph the pulse cannot see who works on which
NEXT item. The boss marks each NEXT item a worker is on with `(→ Name)`; the pulse counts items
without a mark as unassigned and gives the same advice as with a graph: idle worker plus
unassigned item means dispatch, more unassigned items than idle workers means spawn (within
ticket 02's rules). A mark naming a worker that no longer exists counts as unassigned and the
pulse names it. This replaces the bare "dispatch NEXT" line that left plans-live at 3 workers on
2026-11-16 and cuts the "NEXT empty or stale" noise when NEXT holds marked items. Update the
boss SKILL.md where it describes NEXT.

**Blocked by:** None (can start immediately)

**Claimed by:** Anahita 2026-11-19 17:46

**Status:** done

- [x] NEXT with 5 items, 2 marked, gives 3 unassigned
- [x] A mark naming a retired worker counts as unassigned and is named
- [x] With 0 idle workers and 3 unassigned items the pulse asks for 3 spawns
- [x] Tracks with a graph keep using the graph; marks are ignored there

Evidence: PR https://github.com/sweatshop-ai/claude-boss/pull/162, head c811508; `python3 -m pytest skills/boss/test_pulse.py test_boss_pulse.py test_pulse_choice.py test_policy.py test_config_dir.py` 94+ passed (test_next_with_five_items_two_marked_has_three_unassigned passed; test_a_mark_naming_a_retired_worker_is_unassigned_and_named passed; test_no_idle_worker_and_three_unassigned_items_ask_for_three_spawns (and end-to-end test_marks_in_next_tell_the_busy_workers...) passed; test_with_a_graph_the_marks_are_ignored passed); CI pytest success.
