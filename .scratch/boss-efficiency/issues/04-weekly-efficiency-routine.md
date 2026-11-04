# 04: A weekly routine that measures where the time goes

**What to build:** the audit scripts of 2026-11-04 as a routine under `routines/`: script, prompt, timer. It reports per track the share of duration by state, tokens by phase, questions per day and CI waits, and speaks only on an anomaly. Worker sessions are found through the boss's socket, because dispatch wording varies and matching the text missed about half of the worker messages.

**Why:** every other ticket here needs a before and an after. And nothing reads the weekly usage cap that the skill names as the real limit.

**Blocked by:** None (can start immediately)

**Status:** ready

- [ ] The coverage check is in the report: share of worker messages outside tracked activity (19% on 2026-11-04)
- [ ] It runs weekly, silent when nothing moved
- [ ] It says per track what share of the token budget went where, and flags a track whose share moves
