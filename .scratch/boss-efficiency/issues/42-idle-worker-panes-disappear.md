# 42: Idle worker panes disappear without a trace

**What to build:** find out first, then fix. On 2026-11-05 the panes of Britt, Kaveh and Rune were gone by 18:16, the old Otilia's between 18:38 and 18:41, and Signe's between 19:05 and 19:25. Checked: no `retire` or `kill-pane` naming any of them in the two other bosses' sessions that evening; `remain-on-exit` is off; those sessions wrote nothing at the end; nothing unpushed was lost. The cause is not known. Nothing from the owner yet on whether they closed the panes themselves.

First step: when a pane goes, record who or what ended it (the pane's exit status, the tmux server log, a `pane-died` / `pane-exited` hook writing one line to a file). Then decide the fix from what the record says. No fix is designed here, because the cause is not known.

**Why:** a worker that vanishes while idle may be one the boss still counts on, and nobody learns why.

**Blocked by:**
- External: it recurs, or the owner says whether they closed the panes

**Claimed by:**

**Status:** waits on a recurrence

- [ ] The cause of one more disappearance, or the owner's answer, written here
- [ ] The fix, or "owner closed them" and the ticket done
