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

**Claimed by:** Anahita 2026-11-19 18:26

**Status:** done (PR 166, CI and review pending merge)

- [x] Idle unparked worker plus unassigned work: the Stop hook blocks with a reason naming both -- `test_idle_unparked_worker_and_unassigned_ticket_block_the_stop` (skills/boss/test_pulse_block.py, PR 166): output `decision: block`, reason has `IDLE: Ada` and the item; log line `blocked`
- [x] A validly parked worker does not block -- `test_a_checked_park_lets_the_stop_through`: park on busy Bo gives no block; once Bo is idle it blocks again
- [x] The fourth consecutive block for the same idle set is skipped and logged -- `test_the_block_lets_go_after_three_and_logs_it`: block x3, then `block-let-go` x2 in the silence log (the let-go still prints the ordinary pulse text)
- [x] Idle, no work, no park: no block, the text says retire -- `test_idle_with_no_work_and_no_park_is_told_to_retire_without_a_block`: no `decision`, text says retire
- [x] The concierge is never counted as an idle worker -- existing `test_an_idle_concierge_is_not_an_idle_worker` (test_boss_pulse.py) passes on the merged tree: `team()` still excludes the concierge
