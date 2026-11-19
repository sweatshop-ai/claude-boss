# 07: Below the memory floor, retire the longest park first

**What to build:** when a spawn is refused by the memory floor (ticket 02) and the boss has
parked workers, the pulse tells the boss to retire the parked worker that has waited longest
(it keeps its park target in the tracker so the work is picked up later) and then to retry the
spawn. If the boss has no parked worker or memory is still short after the retire, it starts
nobody, the pulse does not block over it, and it logs the shortfall.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] Refused spawn with two parked workers: the pulse names the one parked longest
- [ ] Refused spawn with no parked worker: no block, one log line with free memory and floor
- [ ] A worker retired this way leaves its park event recorded so its work is not lost
