# 06: The boss cannot end its turn while work lies around

**What to build:** when the pulse finds a worker idle without a valid park (ticket 03) while
unassigned work exists (graph or ticket 05), it returns a blocking decision from the Stop hook
instead of extra context: the boss's turn continues with a reason that names each idle worker
and the unassigned items, and the only ways out are dispatching or a checked park. After 3
blocks in a row for the same set of idle workers the pulse lets go and logs it (ticket 01); a
dispatch or park resets the count. A worker idle with no unassigned work and no park gets a
"retire X" instruction without a block. Nothing reaches the owner. Respect the existing
`stop_hook_active` guard so the hook cannot loop on its own block. Update the boss SKILL.md.

**Blocked by:** 01, 03, 05

**Status:** ready-for-agent

- [ ] Idle unparked worker plus unassigned work: the Stop hook blocks with a reason naming both
- [ ] A validly parked worker does not block
- [ ] The fourth consecutive block for the same idle set is skipped and logged
- [ ] Idle, no work, no park: no block, the text says retire
- [ ] The concierge is never counted as an idle worker
