# 01: boss-wrap-up — decide, save if needed, close every worker, then the boss

**What to build:** a wrap-up the owner can call on a running boss that ends the whole
team in one go. Asked by the owner on 2026-10-21. Today Phase E (`skills/boss/SKILL.md`)
collects the closing state and writes the recap, but stops there: the workers stay open
and so does the boss.

The wrap-up:

1. **Can everything close?** Per worker: uncommitted or unpushed work, open branches, a
   task in flight, an open blocker on the owner (the P8 checklist and the tracker).
2. **Verdict, one of two:** *all finished* (objective met, nothing open), or *save the
   state for next time* (what is open, where it is, what the next boss reads first: a
   handoff next to the tracker, the objective set to `paused` with the reason).
3. **Close the workers:** `boss-lifecycle.sh retire --require-idle` for each worker the
   boss owns, only once its work is committed and pushed.
4. **Close itself last.**

**Only when a boss is running.** A skill cannot hide itself, so either it checks
`boss-marker` first and refuses outside a registered boss session, or it is not a separate
skill at all but `/boss wrap-up` (the boss skill's `argument-hint` already lists
`wrap-up`). To settle in a grilling round.

**Open fact to check first:** whether a session can end itself. `retire` sends
`Escape Escape /exit` to a pane and refuses a session in mid-turn, and the boss *is* in
mid-turn while it runs this. Candidates: a detached `sleep 2; boss-lifecycle.sh retire
<own pane>` after the last message, or `tmux kill-pane` on its own pane.

**Blocked by:** None (can start immediately)

**Status:** needs-grilling

- [ ] Grilling round settled: separate skill or `/boss wrap-up`; what "save the state" writes
- [ ] A worker with uncommitted or unpushed work is never retired; the wrap-up says which and stops
- [ ] Every worker the boss owns is retired, then the boss pane ends; `boss-lifecycle.sh list --mine` is empty afterwards
- [ ] Outside a boss session it refuses with one line
