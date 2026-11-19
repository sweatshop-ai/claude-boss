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

**Status:** done

- [x] With 20 ready tickets and 2 idle workers the pulse asks for 18 spawns, not a capped number — test_pulse.py::test_twenty_ready_and_two_idle_ask_for_eighteen_spawns passes (Action spawn 18) (PR 163, CI green on c4854d9)
- [x] A spawn that would leave under 8 GB free is refused with free memory and the floor named — test_memfloor.py::Refusal and test_boss_lifecycle.py::test_a_spawn_under_the_memory_floor_is_refused_before_a_pane_is_made pass: '8.0 GB free' and '8 GB floor' in stderr, no split-window (PR 163, CI green on c4854d9)
- [x] `Workers: 3 — reason` caps the spawn count and the reason appears in the pulse text — test_pulse.py::test_a_capped_spawn_line_gives_the_reason and test_boss_pulse.py::test_a_workers_line_with_a_reason_caps_the_spawn_in_the_pulse_text pass (PR 163, CI green on c4854d9)
- [x] `Workers: 3` without a reason does not cap and the pulse says why — test_pulse.py::test_a_cap_without_a_reason_is_ignored_with_a_note and test_boss_pulse.py (no-reason case) pass (PR 163, CI green on c4854d9)
- [x] The merge-desk case (track capped at 3, 51 spawn pulses) no longer produces "spawn 6" — test_pulse.py::test_a_track_at_its_cap_gets_no_spawn_pulse passes (cap 3, size 3, 9 ready: no pulse) (PR 163, CI green on c4854d9)
