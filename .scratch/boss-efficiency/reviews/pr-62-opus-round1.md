# PR 62 (ticket 30), Opus round 1: bug hunt

**Verdict: GO.** No blocking finding; one wording nit.

## 1. Is `_stop` right? Does anything run with no limit?

- VERIFIED `skills/boss/reviewer_chain.py:246-255`: `killpg(TERM)`, `wait(TERM_GRACE)`, then `killpg(KILL)` with no condition, `wait(None)`, `wait()`. KILL goes to the group whether or not the leader exited during the grace. Only the leader is reaped.
- VERIFIED: there are two callers, both in `_run` (`reviewer_chain.py:307` on timeout, `:310` on any BaseException). `_run` is called only from `_codex` (`:339`) and `_claude` (`:359`). Every reviewer starts with `start_new_session=True` (`:298-299`). Every path that leaves a reviewer running reaches `_stop`.
- VERIFIED, known and accepted: a descendant that leaves the group (`setsid`) escapes the KILL. The `_run` docstring says so (`:288-292`), and the `detached` tests cover it (`test_reviewer_chain.py:261,272`). This is not a regression.
- Not a defect, theoretical only: if the leader exits during the grace and every group member is gone, the second `killpg` targets a pgid the kernel may already have reused. That needs a PID reuse within microseconds. No action.
- An unbounded `proc.wait()` after SIGKILL can block only on a leader stuck in kernel D-state. That is out of the code's control.

**Claim holds.**

## 2. Does the poll still catch a real miss?

- VERIFIED `hermetic.py:136-144`: `trap '' TERM` comes before `sleep 300 &`. The ignored disposition is inherited, so without KILL the child lives about 300 s. 300 s is far beyond the 10 s deadline (`test_reviewer_chain.py:219`), so a missing KILL still fails the test.
- Nothing weaker passes. A missing `child.pid` raises and errors the test; it does not pass it.
- VERIFIED `hermetic.py:43-53`: `alive()` returns False for a zombie (`state != "Z"`) and for a pid that is gone. That matters here: the orphaned `sleep` is reparented to init or a subreaper, and a CI container whose PID 1 never reaps would leave it a zombie forever. The poll treats that as dead.
- The only false result left points the other way: a pid reused within 10 s would fail a correct run. Negligible.
- VERIFIED: a failed run leaves nothing behind. `Base.setUp` registers `sb.cleanup` (`test_reviewer_chain.py:44`), and `reap()` (`hermetic.py:212-231`) SIGKILLs every process that carries the sandbox's environment.
- NOT FOUND: the CI log of the original failure. The cause is consistent with the code but was not observed. `killpg` only queues SIGKILL, and the child turns Z only once it is scheduled. On a loaded runner that gap can exceed the single check the old test made.

## 3. Other findings

- Nit, wording (`test_reviewer_chain.py:215-216`): "leaves the process table a moment later" is not quite what happens. `alive()` already counts a zombie as gone. The real gap is between the signal being queued and the child running its exit path. Suggested text: "SIGKILL is queued at once but the child dies only when next scheduled". This is optional.
- The first test (`:234-237`) cannot tell TERM from KILL, because its child does not ignore TERM. That is unchanged and fine: it tests the group kill, not the escalation.

## Run

`nice -n 19 python3 -m pytest -q -p no:cacheprovider` on the two `Timeouts` ids gave **2 passed in 3.38 s**, run once, at load 6.9. `pgrep -af "sleep 300"` afterwards found no leftover process.
