# PR 67 (sweatshop-ai/claude-boss), Opus review round 2

Diff: `git -C /home/tiroir/Projects/boss-plugin-wt-32a diff 4fbf734 HEAD`, one commit `39f8363`
(`skills/boss/boss-lifecycle.sh` +11/-6, `skills/boss/test_boss_lifecycle.py` +7).
What I ran: `python3 -m pytest skills/boss/test_boss_lifecycle.py -k RequireIdle -q`, which gave 38 passed
(load 2.6). I also ran the new awk clamp on edge values. No real panes were touched.

**Verdict: GO.** B1, B2 and C3 are closed and nothing in class a or b is new. C1 from round 1 is still open,
and one new c and two d remain. None of them blocks the merge.

## Round 1 findings, re-checked

### B1: closed (VERIFIED)
- `skills/boss/boss-lifecycle.sh:388-390` VERIFIED: `owner0=$(pane_owner "$pane") || exit 1` / `owner1=$owner0` / `row=$(python3 "$PANES_PY" --state "$pane" 2>/dev/null) || true`
- `skills/boss/boss-lifecycle.sh:404-405` VERIFIED: `owner1=$(pane_owner "$pane") || exit 1` / `row=$(python3 "$PANES_PY" --state "$pane" 2>/dev/null) || true`
- `skills/boss/boss-lifecycle.sh:432-436` VERIFIED: the two owner checks are `[[ ]]` builtins, then `tmux send-keys -t "$pane" '/exit' Enter`.

On both paths (no wait, and the wait loop) the owner read now comes just before the status read. Between the
last `--state` read and `/exit`, lines 408-435 run only builtins, `printf`, and the refusal paths
(`refuse_busy`/`die`, which never reach `/exit`). The gap is back to what it was before PR 67. The owner read is
now one python process earlier, so a claim that lands between the last owner read and `/exit` goes unseen. That
window is the same size as the status window the function already accepts, so this is the intended trade.
The comment at `:379-380` ("the gap between the read below and the keystroke") is accurate again, which also
closes D1.

### B2: closed (VERIFIED)
- `skills/boss/boss-lifecycle.sh:434-435` VERIFIED: `[[ -z "$owner1" || -z "$BOSS_PANE" || "$owner1" == "$BOSS_PANE" || -n "$FORCE" ]] ||` / `die "$pane belongs to another boss (pane $owner1), not you ($BOSS_PANE): not retiring"`
- `skills/boss/boss-lifecycle.sh:214-215` VERIFIED (resolve_pane): `if [[ -n "$owner" && -n "$BOSS_PANE" && "$owner" != "$BOSS_PANE" ]]; then` / `if [[ -z "$FORCE" ]]; then`

The new condition is the exact negation of resolve_pane's refusal: it passes on an empty owner, an empty
`BOSS_PANE`, the own pane, or `--force`. A claim between `resolve_pane` and `owner0` now leaves `owner0 == owner1 ==`
the foreign pane, and `:434` refuses it. The new test `test_a_claim_between_resolve_pane_and_the_first_owner_read_is_still_refused`
(`test_boss_lifecycle.py:442-447`, owners `%1,%9`, `TMUX_PANE=%1`) exercises exactly this: resolve_pane reads `%1`,
`owner0` reads `%9`, and the run expects "belongs to another boss" with no keys sent. It passes.

### C3: closed (VERIFIED)
- `skills/boss/boss-lifecycle.sh:403` VERIFIED: `'BEGIN { print (l < 0) ? 0 : (l < e) ? l : e }'`

Ran it: `l=-1,e=20 -> 0`, `0,20 -> 0`, `5,20 -> 5`, `30,20 -> 20`, `-3,1.5 -> 0`, `1,1.5 -> 1`. awk's `?:` nests to the
right, so the expression parses as intended. `sleep 0` returns at once, and the loop condition at `:401` then ends the wait.

## Attack list for the round 2 change

| Case | Result | Where |
|---|---|---|
| Unowned pane | `pane_owner` prints nothing for `-` (`:109`), so `owner1` is empty and `:434` passes on `-z "$owner1"`. Default tests (stub owner `-`) pass. | `:105-110`, `:434` |
| Own pane (owner == `BOSS_PANE`) | passes on `"$owner1" == "$BOSS_PANE"`; `test_a_pane_that_keeps_its_owner_through_the_wait_is_retired` (owners `%1`, `TMUX_PANE=%1`) passes. | `:434`, test `:449-453` |
| Foreign pane with `--force` | resolve_pane warns and lets it through; `owner0 == owner1`, and `:434` passes on `-n "$FORCE"`. A third boss claiming during the wait still trips the equality check at `:432`. | `:221`, `:432-434` |
| Empty `BOSS_PANE` (no `TMUX_PANE`) | `:434` passes on `-z "$BOSS_PANE"`, the same rule as `:214`. `BOSS_PANE` is always set (`:36`, `"${TMUX_PANE:-}"`), so `set -u` cannot trip. | `:36`, `:434` |
| Restart path | `cmd_restart` calls `cmd_retire "$pane" >/dev/null` (`:524`): a redirect, not a subshell, so `die` and `exit 1` in `retire_require_idle` end the script before `launch_claude`. The owner is read twice by resolve_pane, then by `owner0`; the rule does not depend on how many reads came before. | `:520`, `:524` |
| `/exit` sent wrongly | Every new line before `:436` can only refuse; none of them adds a path that reaches `/exit`. | `:432-436` |

## Findings

### C1 (c), still open from round 1: an unowned pane claimed by this same boss during the wait is refused
- `skills/boss/boss-lifecycle.sh:432-433` VERIFIED: `[[ "$owner1" == "$owner0" ]] ||` / `die "$pane changed owner during the check (was ${owner0:-nobody}, now ${owner1:-nobody}): not retiring"`

Round 1 said the B2 fix would cover this. It does not: the equality check runs first and does not depend on
the rule, so `owner0=""` with `owner1=$BOSS_PANE` still dies. The refusal fails closed and says why. It only
happens if the same boss runs a parallel `claim` on the pane it is retiring. Fix if wanted: skip the equality
check when `owner1 == $BOSS_PANE`.

### C4 (c), new: one transient `get` failure during a long wait now ends the retire
- `skills/boss/boss-lifecycle.sh:404` VERIFIED: `owner1=$(pane_owner "$pane") || exit 1`

Before this commit the owner was read once after the wait. Now it is read on every retry: a 30-minute
`--wait-idle` at the default 20 s means about 90 reads. `pane_owner` dies on any failure of `boss-panes.py get`
(`:107-108`), so a single failed registry read or `tmux list-panes` call in the middle of the wait refuses a retire
that would have gone through. It fails closed, the ERROR line names the cause, and nothing is typed. The cost is
one retry by the boss. This is acceptable as is; tolerating a failed read inside the loop and requiring a good
read only on the last iteration would bring back the failure mode B1 was about, so I would leave it.

### D3 (d): the test docstring still names `--force` as something the check catches
- `skills/boss/test_boss_lifecycle.py:432-434` VERIFIED: `"""The owner is read once by resolve_pane, before the wait. Another boss` / `may claim the pane (or --force it) while this one waits; /exit would then` / `stop a session that is no longer ours."""`

The script comment was fixed (C2), but the docstring was not. A `restart --force` by another boss does not change
`@boss_pane`, so this check does not catch it; `--expect-session` does. "The owner is read once" is also out of date now.

### D2 (d), still open from round 1: no `restart` variant of the owner tests
All three owner tests use `cmd="retire"`. The code is correct for restart (see the table), but the path the boss
actually uses has no test pinning it. A variant with `cmd="restart"` and owners `%1,%1,%9` (two resolve_pane reads,
then `%9` at `owner0`) would cover both B2 and restart in one test.

## Verdict

**GO.** B1, B2 and C3 are closed, and I verified each by re-reading the code and running the tests (38 passed).
No new a or b. C1, C4, D2 and D3 are tickets or nothing.
