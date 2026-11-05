# PR 60 (aurelio/ticket-03), Opus review round 2: bug hunt, fresh eyes

Worktree `/home/tiroir/Projects/boss-plugin-wt-aurelio`, branch `aurelio/ticket-03`.
Read: `git diff e683298 7937f3c` (the fixes), then `git diff origin/main...HEAD` (8 files, +292/-4);
`routines/ctx_over_measure.py` whole, `skills/boss/test_ctx_over_measure.py` whole, `skills/boss/SKILL.md:300-325`
and `:985-991`, `skills/team/SKILL.md:60-85`, `skills/boss/transcript.py:56-70`, `routines/boss_efficiency_core.py:186-196,240`,
tickets 03 and 28. Round 1 read only after forming the view below. No transcript read or scanned.

Tests: `python3 -m pytest -q skills/boss/test_ctx_over_measure.py skills/boss/test_policy.py -p no:cacheprovider` → **14 passed**.
Regex probes run in-process on literal strings only (results quoted below).

Classes: **a** wrong result/crash, **b** broken contract, **c** tests/docs/style, **d** far-fetched.

## Round 1 findings: are they fixed?

**F1 (ask at the crossing turn): fixed.** `routines/ctx_over_measure.py:103` (VERIFIED) records an ask as `len(order)`,
the count of assistant turns already seen, so `a == k` means "after turn k-1, before turn k". `over` is the 0-based
index of the first turn with ctx >= 250k (`:109-112`, VERIFIED). The boss could only have seen >= 250k once turn
`over` was written, i.e. `a >= over+1`, which is `a > over` (`:117`, VERIFIED). Same reasoning at 150k gives
`split < a <= over` (`:118`, VERIFIED). `turns_after_ask = len(order) - late[0]` (`:123`) counts exactly the turns
after the ask. New test `skills/boss/test_ctx_over_measure.py:52-60` (VERIFIED) puts the ask at `a == over == 8` and
asserts not-after / between; arithmetic checked: turns 0-7 = 100k..240k, split at 3 (160k), turn 8 = 260k.
Lower edge `a == split` is untested (see N5).

**F2 (regex too loose): fixed for the cases named.** `:44` (VERIFIED). `stat` without word end is gone;
`stop at the` now needs `(?:next|current) (?:boundary|state)\b`; `CTX-SPLIT` is gone. Test `:62-66` (VERIFIED)
pins "current status", "stop at the first failure", "CTX-SPLIT" as non-asks. The `\b` covers only the
`stop at the ...` alternative; the bare `(?:next|current) boundary` and `CTX-OVER` have no word end (N4, d).
The `boundary` branch of `stop at the ... (?:boundary|state)` is redundant with `(?:next|current) boundary`; harmless.

**F3 (team text vs boss rule): fixed enough.** `skills/team/SKILL.md:77-79` (VERIFIED) now says stop at the very next
boundary unless the PR waits on CI/merge, "or your boss, having asked how much is left, tells you to carry on".
That no longer contradicts `skills/boss/SKILL.md:309-315` (VERIFIED): the worker proposes, the boss decides. Residual
ordering note in N3 (c).

**F4 (unit of a turn): partly fixed.** Both texts now define it: boss `skills/boss/SKILL.md:318-319` "one model reply,
tool calls included" (VERIFIED), team `skills/team/SKILL.md:79` "one of your replies, a tool call included" (VERIFIED).
The measure counts one per assistant message id (`ctx_over_measure.py:93-97`, VERIFIED), as does the source of the
19k/39k figures (`boss_efficiency_core.py:240`, VERIFIED). The wording still reads both ways (N2, c).

## New findings

### N1 (b): the measure does not see the ask the new rule prescribes
The rule tells the boss to ask "how much is left" (`skills/boss/SKILL.md:312-313`, VERIFIED; ticket 03 line 10).
`ASK` (`routines/ctx_over_measure.py:44`, VERIFIED) has no alternative for that. Probe:
`'how many turns are left?' -> False`, `'how much is left' -> False`. Ticket 28 reads "how many of them were asked
for a boundary" on this same measure as the "after" (issue 28, "How it is read", VERIFIED). A boss that follows the
rule exactly ("you are past 250k, how many turns are left?") is counted only if it happens to add "you are at Nk" or
"next boundary"; a plain "how much is left?" counts as never asked, and the after/before comparison of the asked
share is biased low. Fix: add `how (?:much|many turns) (?:is|are)? ?left` (or similar) to `ASK`, one positive case in
`test_ordinary_messages_are_not_asks`, and rerun the "before" so both halves use the same regex.

Related, not verifiable from here: ticket 03 line 18 and ticket 28 "Before" (5 of 32 after, 3 between, 24 never) must
come from a run of the fixed code (7937f3c). Round 1 reported "4 between" from the old run; the ticket now says 3.
If the figures were not rerun after F1/F2, the "same measure" contract of ticket 28 is already broken. NOT FOUND:
no record of the rerun in the diff or the tickets.

### N2 (c): "tool calls included" still reads two ways
`skills/team/SKILL.md:79` (VERIFIED) "one turn is one of your replies, a tool call included" and
`skills/boss/SKILL.md:318-319` (VERIFIED). A model can read "a reply, with its tool calls, is one turn" (the
user-facing answer, many API calls) as easily as "each tool call is a turn". The measure's unit is the second. Plain
form: "count every tool call and every message you write as one turn".

### N3 (c): the worker may stop before the boss asks
`skills/team/SKILL.md:77-79` (VERIFIED): the worker stops at the very next boundary unless the boss "having asked"
says carry on. Nothing makes the boss ask first (`skills/boss/SKILL.md:317-318`, VERIFIED: "nothing else acts on
it"), so in practice the worker's stop is the trigger and the boss's question comes after a handoff is already
written. Not a contradiction, but adding "and give your estimate of turns left when you stop" would hand the boss
the number the rule needs in the same message.

### N4 (d): word ends
`routines/ctx_over_measure.py:44` (VERIFIED). Bare `CTX-OVER` still matches a peer reporting its own flag (probe:
`'I am CTX-OVER myself, FYI' -> True`), and `ctx-overview` case-insensitively. Round 1 asked to drop bare `CTX-...`;
only SPLIT was dropped. Rare in boss traffic.

### N5 (c): edge and doc gaps carried from round 1
- `a == split` (ask just before the 150k crossing) has no test; logic at `:118` is right (VERIFIED).
- Docstring `:17-18` (VERIFIED) still promises matches on "handoff", "boundary", "restart", "split"; the regex
  matches none alone. The boss SKILL's own CTX-SPLIT wording "at its next natural boundary" (`skills/boss/SKILL.md:303`,
  VERIFIED) is not matched (probe: `'at your next natural boundary' -> False`).
- `left_at_cross = len(order) - over` (`:119`, VERIFIED) includes the crossing turn itself; turns left after the
  boss could first see the flag is one less. Off by one against the 35 line; immaterial at a median of 30.

### N6 (c): grammar locked in by a pinned quote
`skills/boss/SKILL.md:312-313` (VERIFIED) "the boss asks the worker how much is left, and restart at the next
boundary" mixes subjects; the ticket has "restarts". `skills/boss/test_policy.py:73` (VERIFIED) pins
"and restart at the next boundary if that is more than about 35", so the fix needs both lines.

### N7 (c): CHANGELOG line width
`CHANGELOG.md:17` (VERIFIED) is 121 characters after the fix rewrapped only half the paragraph; neighbours are about 100.

### Checked and correct
- `test_policy.py:94` (VERIFIED) new pin "unless your PR is open and\nwaiting on CI or a merge" matches
  `skills/team/SKILL.md:77-78` (VERIFIED) line break exactly; the suite passes.
- SKILL.md 2-test paragraph matches ticket 03 lines 7-10 apart from N6.
- `CONTEXT.md:56` and `policy.py:28` (VERIFIED) name the "Session age" rule; it exists at `skills/boss/SKILL.md:251` (VERIFIED).
- `--days` default 14 (`:130`) and docstring (`:12`) agree with ticket 28's command (VERIFIED).
- Removal of the measured figures from SKILL.md and CHANGELOG (VERIFIED in the fix diff) leaves them only in the
  tickets, so a rerun does not leave the shipped docs stale.
- `list`'s COST/TURN (`skills/boss/transcript.py:56-70`, VERIFIED) counts usage records, not message ids, a
  different unit from the 19k/39k figures; pre-existing, outside this diff, but worth knowing when the boss reads
  `list` against the 35.

## Verdict

**NO-GO**, on N1 only: the measure cannot detect the ask the rule prescribes, so ticket 28's asked-share comparison
will read low by construction. One regex alternative plus one test case, and confirm (or redo) the "before" run on
the fixed code. F1-F4 are fixed; N2-N7 are optional.
