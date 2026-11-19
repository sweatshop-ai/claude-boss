# 03: Park with a checked condition (local events)

**What to build:** `boss-park <track> <worker> --until <event>` records a park for a worker,
with three local events: a ticket done (`ticket:<id>`), another worker finished
(`worker:<name>`), and the owner's answer to a question the boss asked through the concierge
(`owner:<question id>`). The park carries its start time and expires after 2 hours. `boss-park
<track> --list` shows the parks; `boss-park <track> <worker> --clear` drops one, and dispatching
work to the worker drops it too. The pulse treats a worker as idle-and-waiting only while its
event has not happened and the park has not expired; when the event happened it says "X's wait
is over (ticket 12 done): dispatch it", when the park expired "X has waited 2 h on <event>:
dispatch, re-park or retire". Prose such as "parked on purpose" no longer counts as a park.
Update the boss SKILL.md with the command and the five allowed events (the two GitHub events
arrive in ticket 04).

**Blocked by:** None (can start immediately)

**Claimed by:** Talia 2026-11-19 17:46

**Status:** done

- [x] An unknown event kind or a missing target is refused with the list of allowed events (test_park.py Parse::test_an_unknown_kind.../test_a_missing_target..., Cli::test_a_bad_event_exits_2 (exit 2, allowed list in stderr); PR 164 CI pytest success)
- [x] A clock time is not an allowed event (test_park.py Parse::test_a_clock_time_is_not_an_event; PR 164 CI pytest success)
- [x] A park on `ticket:<id>` wakes when the frontier reports that ticket done (test_boss_pulse.py test_a_park_on_a_ticket_wakes_when_the_frontier_reports_it_done; PR 164 CI pytest success)
- [x] A park on `worker:<name>` wakes when that worker's session goes idle or ends (test_boss_pulse.py test_a_park_on_a_worker_wakes_when_that_worker_goes_idle; PR 164 CI pytest success)
- [x] A park on `owner:<id>` wakes when the concierge records the answer (test_boss_pulse.py test_a_park_on_the_owner_wakes_when_the_blocker_is_cleared (wakes when the boss clears the blocker on ANSWER); PR 164 CI pytest success)
- [x] A park older than 2 hours is reported as expired (test_boss_pulse.py test_a_park_older_than_two_hours_is_reported_expired; PR 164 CI pytest success)
- [x] Dispatching to a parked worker clears its park (test_boss_guard.py DispatchClearsPark (SendMessage, not ASK); PR 164 CI pytest success)
