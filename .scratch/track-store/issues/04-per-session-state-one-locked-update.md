# 04: Per-session state goes through one locked update

**What to build:** the track store names per-session state files and updates
them safely: `state_path(sid, kind)` and `update_state(sid, kind, fn)`, a
read-modify-write under `flock` (what the guard's counter already does). The
guard's firing counter and the pulse's rate limit (`gate`/`commit`) both use it,
so the pulse's state file gains the lock it lacks. Reap takes its candidates,
`(path, sid)` pairs from the boss-file directory and `pm/.pulse/`, from the
store, keeping the rule that a file whose name holds no UUID is never a
candidate; its live-session set, 30-minute grace and dry run stay in reap.

**Blocked by:** 01

**Claimed by:** Elske 2026-10-27 12:28

**Status:** done

**Evidence:**
- `python3 -m pytest skills/boss/test_boss_store.py -q` in track-store-04 at 14702ff: StateFiles covers missing file, unreadable JSON, non-object JSON, unwritable dir (returns new state, no exception), raising fn leaves bytes identical; 4-process x 25 updates lose none
- `pytest test_boss_store.py test_boss_guard.py test_boss_pulse.py test_boss_reap.py test_config_dir.py`: 91 passed; CI pytest success on 14702ff (draft PR #32)
- test_boss_reap.py passes; ReapCandidates compares `boss_store.reap_candidates` with 0.16.0's rule on a fixture of boss files, legacy and no-UUID names, a dir and a symlink: equal
- `grep -n '".pulse"' boss-guard.py boss-pulse.py boss-reap.py` empty; test NoHookBuildsAStatePath. boss-pulse still calls `boss_store.state_dir()` for the frontier cache (ticket 05)

- [x] Store tests: `update_state` on a missing file, on unreadable JSON (starts
      from `{}`), and on an unwritable directory (the hook still exits 0)
- [x] The guard's powers-of-two speaking and the pulse's 60 s / 12 per hour limit
      behave as before (existing tests pass)
- [x] Reap's tests pass; a file named without a UUID in either directory is
      never returned by the store's candidate list
- [x] Neither guard, pulse nor reap builds a `.pulse/` path itself
