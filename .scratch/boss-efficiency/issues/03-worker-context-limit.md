# 03: A limit on worker context that holds

**What to build:** find out why `CTX-OVER` at 250k does not stop workers, and make it hold where a restart pays: more than about 35 turns left.

**Why:** 77% of workers pass 150k and 38% pass 250k. A turn costs 19k units at 100-150k of context, 39k at 250-400k, 53k above 400k. A restart costs about 425k units of orientation, so it pays after about 35 turns. Upper bound on the saving: 14% of tokens.

**Blocked by:**
- External: Thierry settles a grilling round on when not to restart; not yet asked

**Status:** needs-grilling

- [ ] Measured: of the workers past 250k, how many the boss asked for a boundary, and what happened
- [ ] The rule states when not to restart a worker near the end of its task
- [ ] Share of worker cost above 250k, before and after, on the same measure
