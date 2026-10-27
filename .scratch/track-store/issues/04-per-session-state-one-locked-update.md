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

**Status:** ready-for-agent

- [ ] Store tests: `update_state` on a missing file, on unreadable JSON (starts
      from `{}`), and on an unwritable directory (the hook still exits 0)
- [ ] The guard's powers-of-two speaking and the pulse's 60 s / 12 per hour limit
      behave as before (existing tests pass)
- [ ] Reap's tests pass; a file named without a UUID in either directory is
      never returned by the store's candidate list
- [ ] Neither guard, pulse nor reap builds a `.pulse/` path itself
