# 05: Frontier cache path in the store, and the bash scripts kept in agreement

**What to build:** `frontier_cache(track, source)`, the file where the last
`frontier.py --json` of a GitHub ticket graph is kept, moves from the pulse into
the track store, key included. `boss-goal` and `boss-tracker` keep their own
bash path code (settled: no extra `python3` per call), and a test keeps them
true: it fails when their track-name regex, the tracker, objective or archive
path, or `boss-goal check`'s frontier cache key differ from the store's. The
pattern is `test_policy.py`'s, which keeps the prose's quotes of the policy true.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The pulse asks the store for the cache path; the key is computed in one
      Python place
- [ ] The agreement test fails when the bash regex, a bash path, or the bash
      `sha1sum` key is changed by one character (checked by mutating a copy)
- [ ] The agreement test passes on the branch
