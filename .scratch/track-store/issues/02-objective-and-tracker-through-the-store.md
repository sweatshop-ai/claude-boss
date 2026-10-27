# 02: Objective and tracker are read through the store

**What to build:** the track store names and reads a track's two files:
`objective_path(track)`, `tracker_path(track)`, `read_objective(track)` and
`read_tracker(track)`, the reads returning the text or `None` when the file is
missing or unreadable. The store never interprets the text; `objective.py` and
`tracker.py` keep the formats. The pulse reads the tracker once per Stop (today
`open_blockers` and `due_rungs` each read it) and the objective through the
store; `boss-compact` builds its re-injection from the same calls.

**Blocked by:** 01

**Claimed by:** Chiara 2026-10-27 12:28

**Status:** done

- [x] Store tests: path names, a missing file, an unreadable file, an invalid
      track name (no path is built for it)
      (evidence: `python3 skills/boss/test_boss_store.py` -> Ran 15 tests, OK; new class TrackFiles, red before the store change: errors=8; commit 86c00cf)
- [x] The pulse and compact build no `pm/<track>…` path themselves
- [x] The pulse reads the tracker once per Stop (a test counts the reads, or the
      code shows one read passed to both consumers)
- [x] Existing pulse and compact tests pass unchanged

Evidence (Chiara, 86c00cf on feat/track-store):
- Box 2: `grep -n 'pm_dir\|\.goal\.md\|%s\.md' skills/boss/boss-pulse.py skills/boss/boss-compact.py` finds only the docstring line 20 and the GOAL_HEAD heading text; no path is built.
- Box 3: `OneTrackerRead.test_the_tracker_is_read_once_per_stop` counts `boss_store.read_tracker` calls in one `main()` Stop: 1 (0 before the change), and the blocker reaches the text.
- Box 4: no existing test edited; `test_boss_pulse.py` Ran 25 OK, `test_config_dir.py` Ran 8 OK (the only test file driving boss-compact, which has none of its own).
- CI: `gh api .../commits/86c00cf.../check-runs`: total_count 1, pytest completed success.
