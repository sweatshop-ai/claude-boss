# 24: Hand-clear hold, edge cases found in the review of 09a

**Blocked by:** 09a

**Status:** ready-for-agent

Found by Codex round 1 on PR 102 (real Codex, GO, no class a or b finding). Review file: `09a-reviews/round-1.md` beside the 09a worktree.

- [ ] Class c: `codex_blocker.sync` rejects only `now.tzinfo is None`; a `tzinfo` whose `utcoffset()` returns None passes, and the future-clear comparison in `_newest_clear` then raises `TypeError` and aborts the sync. Check `now.utcoffset() is not None` and turn a `TypeError`/`ValueError` from a malformed `tzinfo` into the existing `ValueError`; test it.
- [ ] Class d: `test_two_outages_with_the_same_injected_now_get_two_ids` checks two ids but never the `boss-alert` stub; also assert `len(self.alerts("0")) == 2`.
