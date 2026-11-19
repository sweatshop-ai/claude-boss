# Pulse park: idle workers need a checked reason

Design settled with Thierry on 2026-11-19 (grilling session c81a6c2b). Evidence: about 1,100
pulses named idle workers across 24 boss sessions, and in 86% the boss dispatched nobody; 457
times it answered "parked on purpose" in prose, which nothing checked. The action-list boss had
285 Stops and zero pulses, and the gates leave no trace of why.

## Decisions

1. A worker may be idle only with a **park** whose wake event the pulse can check: a PR merged
   that its next step depends on; the CI of its own PR finished (automatic park); a ticket done;
   another worker finished; the owner's answer to a question the boss asked through the
   concierge. No clock-time condition. Every park lasts at most **2 hours**, then the pulse asks
   the boss again.
2. An idle worker without a valid park while **unassigned work** exists **blocks the end of the
   boss's turn** (Stop hook decision) until the boss dispatches or parks. After 3 blocks in a row
   the pulse lets go and logs it. Nothing is escalated to the owner: the boss fixes it.
3. Unassigned work = a ready, unclaimed ticket in the graph, or a NEXT item without `(→ Name)`.
   Unassigned work beyond the idle workers means spawn.
4. Idle, no unassigned work, no park: the pulse tells the boss to **retire** the worker, no block.
5. **No worker-count limit** (Thierry: a cap does not spend less, it spends slower). The only
   limit is memory: 8 GB `MemAvailable` must remain after a start; below it the boss retires its
   longest-parked worker, then rechecks; else starts nobody. A track may set `Workers: N` in its
   goal file **only with a written reason**, which the pulse shows.
6. Every silent or let-go pulse writes one log line. The background-tasks gate changes only once
   the log shows it is the cause.

Workers never ask the owner directly: they ask the boss, which asks through the concierge.
