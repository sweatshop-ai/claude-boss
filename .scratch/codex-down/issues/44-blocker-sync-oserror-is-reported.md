# 44: `codex_blocker.py TRACK` reports an unreadable attempts log in one line and exits 2

**What to build:** One bug found by the Codex re-review of PR 109 (ticket 10b), real on main (class b).

`sync` calls `codex_health.health()` inside the tracker's update callback. When `pm/reviews/attempts.jsonl` is unreadable but present (a directory, mode 000), `health()` raises `OSError`, `tracker.update` re-raises it, and `main()` caught only `ValueError`: the command died with a traceback and exit 1, and the tracker stayed unsynced. `codex_health.py` itself prints one line and exits 2, and the module docstring promises that failures go to stderr.

`main()` now catches `OSError` and prints `codex_blocker: cannot read <path>: <reason>` on stderr, one line, exit 2 (the module's code for a refusal, the same as `codex_health.py`). The tracker is left as it was and no alert is posted. `sync()` still raises for a library caller. The one caller, `boss_review._sync_health`, already catches every exception and says it once, so a review is not crashed; a test pins that.

**Blocked by:** none

**Status:** done (Zainab built it)

- [x] `codex_blocker.py TRACK` with a directory at `attempts.jsonl`: exit 2, one stderr line naming the path, no traceback, tracker unchanged, no alert; the test fails on the old code (exit 1, traceback)
- [x] An `OSError` with no filename gives one line and exit 2; fails on the old code
- [x] `boss_review._sync_health` does not raise on the same log and says it once (passes on the old code too: it pins the existing guard)
- [x] The new tests read their stubs (ticket 36)
- [x] CHANGELOG.md has the entry
