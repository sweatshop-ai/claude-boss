# 43: `--list` honours only a valid `cleared=`, and a hand-written `Owner/Repo` entry is one entry on every path

**What to build:** Two bugs found by the Codex re-review of PR 125 (ticket 10b), both real on main (class b).

1. **Fail-open on the release stop.** `boss_recheck.list_entries` counted any `cleared=<non-space>` text as cleared (`cleared=bogus` included), where `tracker.validate` requires ISO 8601 with an offset. `--list` exited 0 while a merged-NO-GO blocker was still open. The cleared test now uses the tracker's own marker parse (`tracker.scan_marker`, `tracker.validate`), no second parser: a blocker is cleared only when its whole marker validates and carries a `cleared=`. A value tracker cannot read, an empty value, or a marker that fails validation (bad `t0`/`id`, missing `ask`, unknown field; found by Codex round 1) is not cleared, and the release stays stopped.
2. **Repo case.** `PROV_LINE` accepts upper case, while `recheck`, `list_entries` and `prune_provisional` compared `e.repo == key` with `key` lowercased. A hand-written `Owner/Repo` entry was listed (that path lower-cased) but never rechecked or pruned, and its round records were looked up under the wrong directory. This one failed closed. `_entry_of` now reads the repo as `repo_key` spells it (lower case), so the entry is the same on every path.

**Blocked by:** none

**Status:** done (Tove built it)

- [x] `cleared=bogus`, a naive time (`2026-11-12T11:00`) and an impossible date keep the release stopped (`--list` exits 1 and prints the BLOCKER); the tests fail on the old code
- [x] A valid `cleared=` on a marker `tracker.validate` rejects does not clear
- [x] A valid `cleared=` (with `+00:00` or `Z`) still clears; an empty one still does not
- [x] A `Owner/Repo` entry is rechecked and removed by a pass, and removed by the prune; both tests fail on the old code
- [x] The new tests read their stubs (ticket 36)
- [x] CHANGELOG.md has the entry
