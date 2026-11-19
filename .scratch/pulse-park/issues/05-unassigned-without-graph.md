# 05: Unassigned work on tracks without a ticket graph

**What to build:** on a track without a ticket graph the pulse cannot see who works on which
NEXT item. The boss marks each NEXT item a worker is on with `(→ Name)`; the pulse counts items
without a mark as unassigned and gives the same advice as with a graph: idle worker plus
unassigned item means dispatch, more unassigned items than idle workers means spawn (within
ticket 02's rules). A mark naming a worker that no longer exists counts as unassigned and the
pulse names it. This replaces the bare "dispatch NEXT" line that left a production box at 3 workers on
2026-11-16 and cuts the "NEXT empty or stale" noise when NEXT holds marked items. Update the
boss SKILL.md where it describes NEXT.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] NEXT with 5 items, 2 marked, gives 3 unassigned
- [ ] A mark naming a retired worker counts as unassigned and is named
- [ ] With 0 idle workers and 3 unassigned items the pulse asks for 3 spawns
- [ ] Tracks with a graph keep using the graph; marks are ignored there
