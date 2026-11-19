# 07: Below the memory floor, retire the longest park first

**What to build:** when a spawn is refused by the memory floor (ticket 02) and the boss has
parked workers, the pulse tells the boss to retire the parked worker that has waited longest
(it keeps its park target in the tracker so the work is picked up later) and then to retry the
spawn. If the boss has no parked worker or memory is still short after the retire, it starts
nobody, the pulse does not block over it, and it logs the shortfall.

**Blocked by:** 02, 03

**Claimed by:** Nilufar 2026-11-19 18:16

**Status:** in-progress

- [x] Refused spawn with two parked workers: the pulse names the one parked longest (test_boss_pulse.py::test_a_refused_spawn_with_two_parked_workers_names_the_one_parked_longest, passed)
- [x] Refused spawn with no parked worker: no block, one log line with free memory and floor (test_a_refused_spawn_with_nobody_parked_is_silent_and_logs_free_memory_and_floor, passed)
- [x] A worker retired this way leaves its park event recorded so its work is not lost (test_the_retired_workers_park_stays_recorded, passed; text tells the boss to keep the park and note it on its Tracker line)
