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

**Status:** ready-for-agent

- [ ] An unknown event kind or a missing target is refused with the list of allowed events
- [ ] A clock time is not an allowed event
- [ ] A park on `ticket:<id>` wakes when the frontier reports that ticket done
- [ ] A park on `worker:<name>` wakes when that worker's session goes idle or ends
- [ ] A park on `owner:<id>` wakes when the concierge records the answer
- [ ] A park older than 2 hours is reported as expired
- [ ] Dispatching to a parked worker clears its park
