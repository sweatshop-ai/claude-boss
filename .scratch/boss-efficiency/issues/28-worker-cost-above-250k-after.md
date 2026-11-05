# 28: Share of worker cost above 250k, after the rule (from ticket 03 box 3)

**What to build:** the "after" half of ticket 03 box 3. Nothing to build; read the same measure again once tracks have run under the rule written in `skills/boss/SKILL.md`, "Session age" (ticket 03, owner's decision of 2026-11-05).

**How it is read:** `flock ~/.claude/pm/.boss-efficiency-transcripts.lock nice -n 19 ionice -c3 python3 -I routines/ctx_over_measure.py --days 14`, run in a window that starts after the rule merged. It prints overall figures; the per-worker rows go to `~/.claude/pm/ctx-over-measure.jsonl` and stay there. Compare these lines with the "before" in ticket 03: workers past 250k, how many of them were asked for a boundary, and the share of worker cost spent above 250k.

**Before.** Definition: a worker session is one that received a boss dispatch as a message of its own; peak context is input + cache write + cache read of the largest assistant message; cost units as `boss_efficiency_core.cost`. The window matters a lot, so both are kept (read with the same script, window ending 2026-11-05):
- 14 days, 371 worker sessions: 32 past 250k (9%); 5 asked for a boundary after the crossing (16%), all 5 ended within 15 turns; 9% of worker cost above 250k; turns left at the crossing median 30, more than 35 in 14 of 32.
- 35 days, 731 worker sessions: 210 past 250k (29%); 28 asked after the crossing (13%), 17 of them ended within 15 turns; 32% of worker cost above 250k; turns left median 50, more than 35 in 126 of 210.
The audit's 38% is not this population (see ticket 03). Read the "after" over the same length of window and compare with the row of the same length, not across.

**Blocked by:** time, and ticket 03 merged. At least 14 days of tracks after the merge, and 20 or more workers past 250k in that window; with fewer the two shares do not compare.

**Claimed by:** nobody

**Status:** waiting

- [ ] Same measure run on a window after the merge
- [ ] Asked share and cost share above 250k written here beside the before
