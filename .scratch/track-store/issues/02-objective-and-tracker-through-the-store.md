# 02: Objective and tracker are read through the store

**What to build:** the track store names and reads a track's two files:
`objective_path(track)`, `tracker_path(track)`, `read_objective(track)` and
`read_tracker(track)`, the reads returning the text or `None` when the file is
missing or unreadable. The store never interprets the text; `objective.py` and
`tracker.py` keep the formats. The pulse reads the tracker once per Stop (today
`open_blockers` and `due_rungs` each read it) and the objective through the
store; `boss-compact` builds its re-injection from the same calls.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Store tests: path names, a missing file, an unreadable file, an invalid
      track name (no path is built for it)
- [ ] The pulse and compact build no `pm/<track>…` path themselves
- [ ] The pulse reads the tracker once per Stop (a test counts the reads, or the
      code shows one read passed to both consumers)
- [ ] Existing pulse and compact tests pass unchanged
