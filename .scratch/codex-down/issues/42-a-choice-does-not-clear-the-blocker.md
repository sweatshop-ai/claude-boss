# 42: a recorded choice does not clear the `Codex down` blocker

**What to build:** Found by the Codex re-review of PR 104 (ticket 09b), real on main (class b). `references/concierge.md` said of `ANSWER q7: …`: "Act on it, clear the blocker." For the `Codex down` blocker the owner's answer is recorded with `codex_blocker.py --choose` and the blocker must stay open; it clears only when `codex_health` says up, through the sync. A boss following the concierge text cleared it by hand, a later failure raised a new id, the recorded choice no longer applied, and the owner was asked again. The concierge text now names the exception, SKILL.md's 09b paragraph states that a recorded choice does not clear the blocker, and `test_policy.py` pins both texts.

**Blocked by:** none

**Status:** done (Mira built it)

- [x] concierge.md says to record a Codex-down answer with `--choose`, not clear it, and that the sync clears it
- [x] SKILL.md 09b says a recorded choice does not clear the blocker
- [x] `test_policy.py` fails if either sentence goes (checked against the old text)
- [x] CHANGELOG.md has the entry
