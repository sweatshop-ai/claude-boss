# 03: A limit on worker context that holds

**What to build:** find out why `CTX-OVER` at 250k does not stop workers, and make it hold where a restart pays: more than about 35 turns left.

**Why:** 77% of workers pass 150k and 38% pass 250k. A turn costs 19k units at 100-150k of context, 39k at 250-400k, 53k above 400k. A restart costs about 425k units of orientation, so it pays after about 35 turns. Upper bound on the saving: 14% of tokens.

**Decided by Thierry, 2026-11-05:** both tests together ("1 & 2"), for a worker past 250k:

- Waiting on CI or merging, with the PR open: never restart.
- Anything else, fixing findings from a review round included: the boss asks the worker how much is left, and restarts at the next boundary if that is more than about 35 turns. On review fixes the estimate wins over the list; the new session picks up the findings from the handoff.

Not a decision, already true of `restart` (`skills/boss/SKILL.md`, "Session age"): a worker whose turn is over and who waits on CI with a Monitor is not finished. It reads `shell` and the restart is refused.

**Blocked by:** None (can start immediately)

**Claimed by:** Aurelio 2026-11-05 00:53

**Status:** in-progress

- [ ] Measured: of the workers past 250k, how many the boss asked for a boundary, and what happened
- [ ] The rule states when not to restart a worker near the end of its task
- [ ] Share of worker cost above 250k, before and after, on the same measure
