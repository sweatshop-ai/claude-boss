# 17: The weekly measure counts a worker by name and ends a track at its last done ticket

**What to build:** ticket 04's routine, and the audit it comes from, count a worker's time only from a recognised dispatch message or a socket match, and count a track until the boss session's last event. Two changes. First, attribute a session to a track when the boss sent to it or heard from it by name, and count its records in the track's window; a message's `from-name` is the name the session started with, not the one the boss claims it under. Second, stop a track's duration at the commit that sets its last ticket to done, or at the goal being marked met, whichever is later; the boss session after that is not the track.

**Why:** ticket 07 sampled 50 of the 2,416 gaps under two hours where the audit saw nobody active. In 16 of them (an estimated 74 h of the 214 h, plus or minus 29) a worker of the track was working: in 8 its session was never scanned, in 8 it was scanned and filed under another track or outside its dispatch windows. In 5 more (23 h, plus or minus 19) the track was finished or closed and only the boss session was left. None of these is lost time; they inflate "nobody active" (44% of duration on 2026-11-04).

**Blocked by:**
- 04

**Claimed by:** Otilia 2026-11-04 22:58

**Status:** in-progress

- [ ] The same 50 gaps, rerun with the new attribution: the hidden-work class falls to 0 or each remaining case is named with its reason
- [ ] The share of worker messages to the boss that fall outside tracked activity is reported before and after (19% on 2026-11-04)
- [ ] A track's duration ends at its last done ticket, shown on three finished tracks with the old and new end
- [ ] "Nobody active" is recomputed for the 30 tracks of the audit and the new figure is stated beside 44.1%
