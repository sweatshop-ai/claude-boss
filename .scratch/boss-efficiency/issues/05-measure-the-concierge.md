# 05: Measure whether the concierge shortened projects

**What to build:** nothing; a measurement. On tracks run with a concierge, compare against the 30 tracks of the audit: share of duration with no worker active and a question open (21%), worker messages queued while a question was open, questions per active day (18), and what the concierge costs in tokens.

**First evidence:** `.scratch/boss-efficiency/concierge-0.21.0.md` is the first evidence for this measure.

**Why:** PR 45 rests on an upper bound. Nobody knows how many waiting workers had a ticket ready.

**Blocked by:**
- 04
- External: three finished tracks run with a concierge

**Status:** waits for three finished tracks with a concierge

- [ ] The same measures, on at least three tracks
- [ ] A verdict: keep, change or remove the concierge
