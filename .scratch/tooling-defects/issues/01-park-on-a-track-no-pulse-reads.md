# 01: A park on a track no pulse reads never wakes

**What happened (2026-11-26):** a boss parked three workers with `boss-park <track> <worker> --until
pr:<owner/repo#N>-merged`. The three PRs merged; the parks stayed in `pm/.pulse/<track>.parks.json` and one worker sat
idle for hours. No `<track>.gh.json` was ever written, so no lookup ran.

**Diagnosis:** the boss's marker (`pm/.boss-sessions/<sid>`) still named its previous track, whose objective was met.
The pulse takes the track from the marker, so every Stop of that boss ended at `objective-closed` for the old track
(`boss-pulse.py why` showed no Stop for the new one) and the new track's parks were never read. `boss-park` wrote the
park on whatever track it was given and said `parked`.

**What to build:** `boss-park --until` refuses (exit 2, nothing written) a park no pulse will read, and says what to run:
- the caller is a boss whose marker names another track: `boss-marker register <track>`, then park again;
- the caller is not a boss and no marker names the track: the track's boss registers it (a worker asks its boss).
`--list` and `--clear` still work, and `--list` warns on stderr when no marker names the track.

**Status:** done (this PR)

- [x] Tests: `test_park.py`, `ParkOnATrackNoPulseReads`
- [x] SKILL.md, "Park a worker": the refusal and what to run
