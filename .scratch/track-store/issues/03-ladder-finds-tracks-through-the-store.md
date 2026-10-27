# 03: The ladder finds open tracks through the store

**What to build:** `open_tracks()` moves from the ladder core into the track
store. It yields `(track, tracker_path, objective_text_or_None, reason)` for
every tracker under `pm/`, skipping dot files, objectives and archives, with only
two reasons: "no goal file" and "goal unreadable". The store does not import
`objective.py`: the ladder keeps its own `is_open()` check and its "goal not
OPEN" line, so what the ladder prints and posts does not change.

**Blocked by:** 02

**Claimed by:** Chiara 2026-10-27 12:33

**Status:** done

- [x] Store tests for `open_tracks()`: a tracker with no objective, an unreadable
      objective, an archive and a `.goal.md` not listed as tracks
- [x] The ladder's `--selftest` passes, and a dry run on a fixture `pm/` prints
      the same lines as before
- [x] The ladder core builds no `pm/` path itself, beyond honouring
      `BOSS_LADDER_PM`
