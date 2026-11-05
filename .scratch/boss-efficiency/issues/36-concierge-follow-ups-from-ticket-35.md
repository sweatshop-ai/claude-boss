# 36: follow-ups from ticket 35 (the concierge in the efficiency measure)

**What to build:** four items left over from PR 65, each with the class the reviewers gave it. Source: `.scratch/boss-efficiency/reviews/pr-claude-boss-65-code-review.md`.

1. **(b) A boss serving two tracks places its concierge on one of them.** `Index.__init__` (the socket path, `resolve_sockets` majority vote) gives the concierge's time from each boss message onward to the one voted track, before name attribution runs and claims the time in `taken`. Reproduced by the Opus reviewer: socket voted `alpha-x`, the boss re-registers `beta-y`, the concierge is asked later and asks; alpha gets 1, beta 0. The concierge's time and tokens were misplaced the same way before ticket 35; its asks now follow them. Fix to decide: attribute a concierge by the boss's window at the time of each `ASK`, not by the socket vote.
2. **(b) The first weekly run after deploy may raise the questions alert once.** `judge` compares a week measured with ticket 35 against the stored week measured without it, where a track with a concierge read near zero. Read from the code (`spend`, `ASKS_RISE`, `ASKS_RATIO`, `FLOOR_TOKENS`), not run. On Monday 2026-11-09 the first weekly run may raise "questions ... per 100 M tokens" once for a track that had a concierge. A thing to expect, not to build for: leave the code alone.
3. **(d) Concierge wait time is not in the ask state seconds.** `measure_track` credits `states["ask"]` only from boss sessions (the `_group(c, ...) == "ask"` loop over `index.bosses`), so the report's ask seconds read low on a track with a concierge. Not asked by ticket 35.
4. **(d) The concierge's tokens count as `build`.** On the first track measured (boss-efficiency, 2026-11-04/05): 339,753 of 14.0 M total tokens, 2.4%, counted in the `build` phase with the workers'. Decide whether the concierge is its own phase.
5. **(b) An answered question is dropped when its answer quotes the guard's words.** `scan_session` drops an `AskUserQuestion` whose result contains `GUARD_REFUSAL` ("Send it to your concierge"), without checking `is_error` (found by Opus round 3 on 3e98205; reproduced at string level, not on a real transcript). Fix: require `b.get("is_error")` and the phrase; the dismissed-question test still passes.
6. **(d) Nothing ties `GUARD_REFUSAL` to `skills/boss/boss-guard.py`.** The constant and the test fixture each copy the guard's reason; rewording the guard counts refused asks again with green tests. Fix: a test that imports or runs the guard's reason.
7. **(d) The `find(">", f.end())` slice has no test.** Reverting that hunk alone keeps all 70 tests green. Fix: a test with text containing `>` before the tag.
8. **(c) `ASK_MSG` misses a backticked `ASK q1:`, and the sender is never checked**, so any peer whose message starts `ASK x:` flags its receiver as a concierge (it adds nothing unless the receiver has the tool). Leave unless seen.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Status:** ready

- [ ] Item 1: a test with one boss, two tracks and one concierge, each `ASK` on the track the boss was on at that time
- [ ] Item 3: a test that a concierge question open time is in `states["ask"]`
- [ ] Item 4: a decision, then a test
- [ ] Items 5, 6, 7: the fix and the two tests, one PR
- [ ] Item 2: nothing to build; after the run of 2026-11-09, say whether the alert fired
