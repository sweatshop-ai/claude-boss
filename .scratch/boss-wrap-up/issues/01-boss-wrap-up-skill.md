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

## Settled (owner, 2026-11-11)

- It is `/boss wrap-up` (Phase E), not a separate skill.
- "Save the state" = one line under "Open blockers" in the live tracker, written before anything is closed, naming
  every open item: an owner question still unanswered (with its options, and that it must be asked again by the next
  boss), each open PR and what it waits on, CI runs nobody is watching any more, the brief file to resume each piece
  from. Plus the objective set to `paused` with a reason that points to that line (or `met` after
  `boss-goal verify --tick` proves it).
- Closing covers every pane the boss owns, the concierge included even with a question open. Also, on the owner's
  word, the unowned leftover panes in the boss's tmux window. Not the boss's own pane: it stays for the owner to
  close ("close itself last" stays an open box).
- A worker waiting on CI or holding a merge shows busy/shell and `retire --require-idle` refuses it. Closing it
  anyway is allowed only when its git state shows nothing at risk (`tmux kill-pane` or `retire --kill --force`). A
  worker with uncommitted code or commits on no remote is not closed: the wrap-up names it and stops for it.

**Blocked by:** None (can start immediately)

**Status:** in review

- [x] Grilling round settled: separate skill or `/boss wrap-up`; what "save the state" writes
- [x] A worker with uncommitted or unpushed work is never retired; the wrap-up says which and stops
- [x] Every pane the boss owns is closed, the boss pane stays (written check: `test_wrap_up_saves_the_state_before_it_closes_a_pane`); the boss's own pane closing itself is left open
- [x] Outside a boss session it refuses with one line
