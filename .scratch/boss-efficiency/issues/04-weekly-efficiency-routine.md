# 04: A weekly routine that measures where the time goes

**What to build:** the audit scripts of 2026-11-04 as a routine under `routines/`: script, prompt, timer. It reports per track the share of duration by state, tokens by phase, questions per day and CI waits, and speaks only on an anomaly. Worker sessions are found through the boss's socket, because dispatch wording varies and matching the text missed about half of the worker messages.

**Why:** every other ticket here needs a before and an after. And nothing reads the weekly usage cap that the skill names as the real limit.

**Blocked by:** None (can start immediately)

**Claimed by:** Amara 2026-11-04 20:49

**Status:** done

- [x] The coverage check is in the report: share of worker messages outside tracked activity (19% on 2026-11-04). Evidence: `test_busy_week_coverage_is_in_the_report_not_a_trigger` asserts `35/100` in `render`, and `test_per_track_coverage_is_callable` / `test_a_worker_message_with_no_tracked_worker_is_counted_outside` cover the count; 33 tests pass and CI `pytest` is green on the merged head 021b0f2 (PR 49, merge bf3e896). The 19% figure is from Bilal's 5-week scan (his handoff); I did not re-run it.
  - Waits for the owner to update the plugin and run install.sh; the first run is the Monday after that. (Silence rests on four comparable weeks of replay and on `test_the_fleet_share_doubling_alone_never_speaks`.)
- [x] It says per track what share of the token budget went where, and flags a track whose share moves. Evidence: `test_a_track_that_changes_how_it_spends_is_flagged` and `test_ci_wait_share_and_questions_are_phases_too` (flags), `render`'s per-track table; same green CI.

The box "It runs weekly, silent when nothing moved" moved to ticket 21: only the owner's plugin update can make it true.
