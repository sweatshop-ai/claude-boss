# 32: The Codex down blocker clears only on an answered streak that was observed

**Blocked by:** 05

**Status:** done (Amelie built it, PR 119)

Found by the Codex re-review of PR 90 (class b, real on main). `codex_blocker.py` cleared an open `Codex down`
blocker when `codex_health` said `up`, and `codex_health` starts at `up` for a log that is missing or empty.
With `attempts.jsonl` deleted or truncated while the blocker was open, one failed attempt (`state=up,
failures=1, answers=0`) cleared it. A missing or truncated log is not evidence of recovery.

## What to build

`codex_blocker.sync` clears only when `state == "up"` and `answers >= policy.CODEX_UP_AFTER`: the streak of
answered attempts is read from the log, not assumed.

- [x] A test that fails on main: with a blocker open, a deleted log, an empty log and a log of one failure each
  leave it open and post no `clear`; two answered attempts then clear it once.
- [x] The condition in `codex_blocker.sync`; CHANGELOG.md.
