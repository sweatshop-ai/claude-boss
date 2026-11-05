# PR 67 (sweatshop-ai/claude-boss), Opus review round 1

Diff: `git -C /home/tiroir/Projects/boss-plugin-wt-32a diff origin/main...HEAD`, one commit `4fbf734`.
What I ran: `python3 -m pytest skills/boss/test_boss_lifecycle.py -k RequireIdle -q`, which gave 37 passed
(load 3). I also ran the awk expression and `sleep` on edge values, and timed `boss-panes.py get` against a fake
`tmux` that fails. No real panes were touched.

**Verdict: GO.** I found nothing in class a. The owner re-read closes the hole Codex reported, the
no-pin refusal fails closed, and the last sleep ends the wait on time. The two b findings are tickets, not blockers.

## Findings

### B1 (b): the owner re-read widens the race the function exists to keep small
- `skills/boss/boss-lifecycle.sh:379-380` VERIFIED: `# Escapes abort ANY busy turn, so this path sends none before /exit. What is` / `# left is the gap between the read below and the keystroke.`
- `skills/boss/boss-lifecycle.sh:428` VERIFIED: `local owner1; owner1=$(pane_owner "$pane") || exit 1`
- `skills/boss/boss-lifecycle.sh:431` VERIFIED: `tmux send-keys -t "$pane" '/exit' Enter`

`owner1` is read after the last `--state` read (`:387` or `:401`) and before `/exit`. That puts one more full
`boss-panes.py` process into the gap between the idle reading and the keystroke. The process loads the
registry and calls `tmux list-panes`. Measured: 0.06 s with tmux failing at once, so the real cost is at
least that, and more under load. Before this PR the gap was the tail of one python process; now it is
roughly doubled. A turn that starts in that gap with the model generating and no tool yet is ended by `/exit`.
This is the exact loss the function is designed around, and no later check catches it, because
no dialog opens. The race existed before; this PR makes it wider. It does not make it new.
Fix: read the owner in the same process as the state. Add an `owner` column to `--state`, or read the owner
just *before* the final `--state` read, so that the state stays the last thing read before the keystroke.

### B2 (b): an owner change between `cmd_retire`'s `resolve_pane` and `owner0` passes as "unchanged"
- `skills/boss/boss-lifecycle.sh:386` VERIFIED: `owner0=$(pane_owner "$pane") || exit 1`
- `skills/boss/boss-lifecycle.sh:429` VERIFIED: `[[ "$owner1" == "$owner0" ]] ||`

The comparison is against `owner0`, not against the rule `resolve_pane` applied (empty, `$BOSS_PANE`, or
foreign plus `--force`). A `claim --force` by another boss that lands between `resolve_pane` and `:386` is
the only path. In that window one `pane_prop` and one python start run, in `cmd_retire` after `resolve_pane`.
Then `owner0` is already the foreign boss, `owner1` equals it, and `/exit` goes to a pane another boss
just claimed, with no `--force` given. The window is tiny, so in practice this sits between b and c.
Fix: at `:429`, also apply `resolve_pane`'s rule to `owner1`. Refuse when `owner1` is non-empty, differs
from `$BOSS_PANE`, and `--force` was not given. Keep the equality check for the `--force` case.

### C1 (c): an owner change to *this* boss refuses a legitimate retire
`:429` refuses when an unowned pane is `claim`ed by the same boss during the wait (`owner0=""`,
`owner1=$BOSS_PANE`). The refusal fails closed and its message is clear. It needs a parallel `claim` from the
same boss on the same pane. The fix from B2 (accept `owner1 == $BOSS_PANE`) covers this too.

### C2 (c): another boss's `restart --force` during the wait is not an owner change
The comment at `:384` VERIFIED reads `another boss may have claimed (or --forced) the`. Only `claim`/`spawn` stamp
`@boss_pane` (`claim_pane` at `:199`, called only from `cmd_spawn` and `cmd_claim`; verified with grep). Suppose
boss B runs a `--force` restart on A's pane while A waits. The owner stays A, and A's next read shows a new,
idle session. Without `--expect-session`, A then sends `/exit` to B's fresh worker. This was already so before
the PR; `--expect-session` is the guard. The comment overstates what the check covers: it catches `claim --force`,
not `restart --force`.

### C3 (c): a negative last sleep stops the script with no ERROR line
- `skills/boss/boss-lifecycle.sh:400` VERIFIED: `sleep "$(awk -v e="$RETRY_EVERY" -v l=$((WAIT_IDLE - (SECONDS - t0))) 'BEGIN { print (l < e) ? l : e }')"`

The loop condition at `:398` guarantees `SECONDS - t0 < WAIT_IDLE` one builtin earlier. So `l` is ≥ 1, or 0 if
`SECONDS` ticks in between, and `sleep 0` works (checked). `l` goes negative only if bash stalls for more than
1 s between two adjacent builtins. Then awk prints `-1`, `sleep -1` exits 1 (checked: "unexpected argument
'-1'"), and `set -e` ends the script with no ERROR line and nothing typed. That fails safe. If you want it
closed anyway, use `l<1?1:...` or a `max(l,0)`.
The rest of the arithmetic is correct. `RETRY_EVERY` is floored to ≥ 1 at `:87`, so the loop is never tight.
Fractional `e` prints as given (`1.5,5 -> 1.5`), `l < e` picks the remaining time (`20,5 -> 5`), and integer `l`
from `$(( ))` is always a valid `-v` value. `WAIT_IDLE=0` never enters the loop.

### D1 (d): the comment at `:379-380` no longer describes the gap
The comment names the gap between "the read below" and the keystroke. That gap now also holds the owner read. Update it with B1.

### D2 (d): the tests do not cover the restart path or the no-wait path for the owner check
The owner tests (`test_a_pane_claimed_by_another_boss_during_the_wait_gets_no_exit`, `..._keeps_its_owner_...`)
run `retire` only. The owner sequence `%1,%1,%9` depends on how many times the owner is read before `owner0`.
`retire` reads it once (in `resolve_pane`), so read 3 is `owner1`, and the test does prove the property. Under
`restart` there is one more `resolve_pane` read, so the same sequence would put `%9` into `owner0`, and the test
would fail if reused. A restart variant (`cmd="restart"`, sequence `%1,%1,%1,%9`) would pin the path the boss
actually uses. The tests also do not cover B2.

## Checked and found correct (attack list)

- **Unowned pane:** `pane_owner` prints nothing for `-` and returns 0 (`:105-110`), so `owner0` and `owner1`
  are both empty and compare equal. The existing tests run with the stub's default owner `-` and pass.
- **`--force` on a foreign pane:** `owner0` and `owner1` are both the foreign pane and compare equal, so the
  retire goes through. A third boss's claim during the wait refuses, which is the intended result.
- **No `BOSS_PANE`:** the check still compares the two reads. The case where `resolve_pane` lets a foreign pane
  through without `--force` when `BOSS_PANE` is empty (`:214`) was already so before the PR; this PR does not touch it.
- **`pane_owner` failing:** `die` inside `$(...)` exits the subshell with 1. Its stderr is not captured, so the
  ERROR line shows. `|| exit 1` then ends the script in the main shell. `retire_require_idle` runs in the main
  shell (`cmd_retire` from `case`; `cmd_restart` calls `cmd_retire "$pane" >/dev/null`, which is a redirect,
  not a subshell). Because `local owner1;` is declared on its own, the assignment keeps the exit status. The
  new reads add two more chances of a fail-closed refusal, the same kind `resolve_pane` already has.
- **No transcript, or a fresh session:** `--state` prints `-` for both pins when there is no transcript
  (`boss-panes.py:240-246`). `:448` refuses only inside the "Background work is running" branch. A fresh, never-prompted
  session has no background work, so a dialog there does mean a turn in the gap, and refusing is correct. An idle worker
  with a leftover task and an unreadable transcript is now refused where it used to be confirmed. That fails closed and
  says why. The only producer of `--state` rows always prints five fields, so an empty `past` cannot reach `:448`
  outside the stub. The tests that were moved from 3 to 4 fields reflect that.
- **One Escape on the no-pin path:** the same keystroke the existing "turn in the gap" path sends, which was measured
  to close the dialog and nothing else.
- **Turn wording:** `routines/ctx_over_measure.py:93-97` keys turns by `message.id`, so "calls batched in one message
  are one turn" matches what the code measures.

## Verdict

GO. B1 and B2 should become a ticket, and the fix is one change: return the owner from `--state` and apply
`resolve_pane`'s rule plus the equality check to it. C1-C3 and D1-D2 are tickets or nothing.
