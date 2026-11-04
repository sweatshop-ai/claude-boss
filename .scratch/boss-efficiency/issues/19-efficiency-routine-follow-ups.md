# 19: Nine small follow-ups from the reviews of the weekly efficiency routine

**What to build:** the nine P3 findings left open after three review rounds of PR 49 (verdict: `.scratch/boss-efficiency/reviews/pr-49-round2.md`). None touches security or lost data; each is small, do them in one change with a test where one is named.
1. `DRY_RUN=1` still runs `mkdir` and the log rotation in `routines/boss-efficiency.sh`; either skip them when dry or reword the header to "writes no reports or state".
2. Reruns of one week stack in `history` because the dedupe is on the exact float `end`; dedupe on the date label, or when the ends are within a day.
3. `scan_session` returns `None` for a file with no user or assistant records and drops its `skipped` count; return the record or say "in sessions with records" in the stderr line.
4. `FAIL_UNCOVERED` has no minimum sample: one to three worker messages, all outside, give 100% and fail the week. Add a floor on the message count. Test at the 90% boundary, healthy side included.
5. `usage()` lets NaN, inf and negative numbers through; accept only finite values of zero or more.
6. The subagent cost test repeats the code under test; assert the literal value.
7. Memory per week of data is not measured; measure peak RSS on one real week and decide on `MemoryMax=` in the service.
8. Trace how `Index` fills `worker_msgs` when the socket lookup finds nothing: a total failure may give 0 messages (the older check) rather than a high share. Make the comment on `FAIL_UNCOVERED` say which it is.
9. `ionice -c3` can starve the scan on a busy disk and hit the 3600 s cap, which loses the week; decide between `-c2 -n7` and a longer cap (the unit's 4h timeout would have to grow with it).

**Why:** the reviews found them and the PR had used its three rounds; left unrecorded they are lost. The Codex review owed on PR 49's merged head may add to this list.

**Blocked by:** None (can start immediately)

**Claimed by:** Rune 2026-11-04 23:30

**Status:** in-progress
