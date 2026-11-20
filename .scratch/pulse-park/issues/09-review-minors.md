# 09: Minor findings left open by the fix PRs 177, 178 and 179

**What to build:** the minor findings the review rounds on the fix PRs left open. None blocks a
boss today; each makes the pulse or the spawn lock behave worse than it says. Fix them test-first,
one failing test per item, in one PR.

NEXT parsing (`skills/boss/objective.py`, `entries()`, the one NEXT reader since PR 177):

- [ ] Short prose lines without final punctuation ("Ticket 12" / "Ticket 13") read as two items, not one, so the pulse does not undercount unassigned work. Decide the rule (a line that starts with a capital or a ticket number starts a new item) and test both orders.
- [ ] A placeholder followed by a reason ("Nothing queued; waiting on the owner.") is no work: it does not block an idle Stop and asks for no spawn.

Spawn lock and memory settle (`skills/boss/boss-lifecycle.sh`, `skills/boss/memfloor.py`, PR 179):

- [ ] `settle` ends as soon as the new worker's process tree is up and growing, and does not regularly run the full 30 s timeout; measure on a real spawn and record the times in the PR.
- [ ] The `flock` has a timeout, so a spawn queued behind another boss exits with a clear message before the caller's tool timeout.
- [ ] Without `XDG_RUNTIME_DIR` the lock goes in a per-user directory with mode 0700, not in a predictable name in `/tmp`.
- [ ] A test checks that `spawn` passes `--boss` to `settle`.

Tests (`skills/boss/test_park.py`, PR 178):

- [ ] `test_a_clear_that_cannot_be_written_fails_loudly` also passes when run as root (chmod 0o500 does not stop root); make the write fail another way, or skip only under root with the reason.

CHANGELOG: one line under `## Unreleased`. No version bump.

**Blocked by:** none

**Claimed by:**

**Status:** ready
