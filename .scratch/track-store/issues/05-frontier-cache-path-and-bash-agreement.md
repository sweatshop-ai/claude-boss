# 05: Frontier cache path in the store, and the bash scripts kept in agreement

**What to build:** `frontier_cache(track, source)`, the file where the last
`frontier.py --json` of a GitHub ticket graph is kept, moves from the pulse into
the track store, key included. `boss-goal` and `boss-tracker` keep their own
bash path code (settled: no extra `python3` per call), and a test keeps them
true: it fails when their track-name regex, the tracker, objective or archive
path, or `boss-goal check`'s frontier cache key differ from the store's. The
pattern is `test_policy.py`'s, which keeps the prose's quotes of the policy true.

**Blocked by:** 01

**Claimed by:** Farid 2026-10-27 12:28

**Status:** done

- [x] The pulse asks the store for the cache path; the key is computed in one
      Python place
     Evidence: `boss_store.frontier_cache(track, source, cfg=None)`; boss-pulse.py calls it (its own copy deleted); test_boss_store.py FrontierCache + 67 passed locally (fcb6813).
- [x] The agreement test fails when the bash regex, a bash path, or the bash
      `sha1sum` key is changed by one character (checked by mutating a copy)
     Evidence: test_bash_agreement.py MutationCheck, 13 subtests passed: one-character changes on copies to regex length/anchor/class, goal/tracker/archive paths, cache dir/suffix, key length/hash, `echo` for `printf`, truncated source, `:-` to `-` all caught.
- [x] The agreement test passes on the branch
     Evidence: `pytest test_bash_agreement.py` 3 passed locally (key pinned on é, 日本, trailing newlines, locales C/C.UTF-8/en_US.UTF-8); CI on fcb6813: pytest completed success, total_count 1.
