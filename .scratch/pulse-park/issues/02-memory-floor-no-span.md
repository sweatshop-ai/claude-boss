# 02: No worker limit, an 8 GB memory floor instead

**What to build:** the pulse stops capping spawn at `BOSS_SPAN`: it proposes as many new
workers as there is unassigned work beyond the idle workers (Thierry 2026-11-19: a cap only
spends slower). The spawn path refuses to start a worker when less than 8 GB of `MemAvailable`
would remain after it (estimate the new worker's cost from the boss's current workers, at least
0.5 GB), and says so plainly with the numbers. A track may set `Workers: N — <reason>` in its
goal file; the pulse honours N only when a reason is written and shows the reason in its spawn
line ("team 3 of 3: one change at a time on the plans-live box"). Without a reason the field is
ignored with a one-line note. Update the boss SKILL.md where it speaks of the span.

**Blocked by:** None (can start immediately)

**Claimed by:** Zainab 2026-11-19 17:46

**Status:** in-progress

- [ ] With 20 ready tickets and 2 idle workers the pulse asks for 18 spawns, not a capped number
- [ ] A spawn that would leave under 8 GB free is refused with free memory and the floor named
- [ ] `Workers: 3 — reason` caps the spawn count and the reason appears in the pulse text
- [ ] `Workers: 3` without a reason does not cap and the pulse says why
- [ ] The merge-desk case (track capped at 3, 51 spawn pulses) no longer produces "spawn 6"
