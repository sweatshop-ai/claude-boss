# PR 60 (aurelio/ticket-03), Opus review round 3: N1 fix, fresh eyes

Worktree `/home/tiroir/Projects/boss-plugin-wt-aurelio`, branch `aurelio/ticket-03`.
Read: `git diff 7937f3c 717b402` (5 files, +7/-7); `routines/ctx_over_measure.py:10-22,40-126`;
`routines/boss_efficiency_core.py:236-245`; `skills/boss/SKILL.md:310-321`; `skills/team/SKILL.md:76-80`;
ticket 03. Round 2 read after forming the view below. No transcript read.

Tests: `python3 -m pytest -q skills/boss/test_ctx_over_measure.py skills/boss/test_policy.py -p no:cacheprovider`
gives **14 passed**. Regex probes ran in-process on literal strings only.

Classes: **a** wrong result or crash, **b** broken contract, **c** tests/docs/style, **d** far-fetched.

## N1 (round 2): fixed

`routines/ctx_over_measure.py:44` (VERIFIED) adds `how (?:much|many turns)[^.?\n]* left`. Probes:
`'how much is left?'`, `'how many turns are left'`, `'how many turns have you left'` and
`'roughly how many turns do you have left'` all give True. Test `skills/boss/test_ctx_over_measure.py:65`
(VERIFIED) pins the two phrasings the rule uses. The boss's prescribed question is now detected.

## Can it mislabel a worker's own report?

No, by construction. `scan` tests `ASK` only on `type == "user"` records with no `tool_result` whose first 400
characters hold `<cross-session-message` (`ctx_over_measure.py:98-103`, VERIFIED). A worker's own report is an
assistant record in its own transcript and is never scanned. `'nothing left'` gives False anyway.

What the new alternative can catch is an **incoming** message from another session that uses "how much ... left"
for something else. Probes, all True: `'how much was left'`, `'how much time is left on CI?'`,
`'how much leftover budget'` (no word end after `left`), `"I don't know how much context is left in the boss"`,
`'see how much fun is left'`. Such a message counts only if it arrives after the worker crossed 150k
(`:117-118`, VERIFIED), and boss-to-worker traffic past 250k is mostly about the boundary. Class **d**. A `\b`
after `left` would close the `leftover` case for free.

## New findings

### R1 (c): "each tool call is its own turn" is not the measure's unit
`skills/boss/SKILL.md:319` and `skills/team/SKILL.md:79` (both VERIFIED) now say "one model message, so each tool
call is its own turn". The measure counts one turn per distinct assistant `message.id`
(`ctx_over_measure.py:93-97`, VERIFIED), and so does the source of the 19k/39k figures
(`boss_efficiency_core.py:240`, VERIFIED). Parallel tool calls issued in one model message share one id, so they are
one turn, not several. The first half of the sentence is right; the "so" clause overcounts when calls are batched.
Plain form: "one model message, so a message with tool calls counts once, however many it makes, and each next
message is another turn". The error is in the worker's favour (its estimate reads high, the restart is more likely),
so not class b.

### R2 (c): `skills/boss/SKILL.md:319` is 134 characters
The rewrap moved text onto one line; neighbours are 79-90 (VERIFIED by `awk length`). Rewrap lines 319-321.

### R3 (c): docstring still names words the regex does not match
`routines/ctx_over_measure.py:17-18` (VERIFIED) says the ask is a message wording a boundary ("handoff",
"boundary", "restart", "split"). Carried from round 2 N5; it now also omits the "how much is left" form, the one the
rule prescribes. One line.

### R4 (c): the "before" figures were not shown to be rerun on this regex
Ticket 03 line 18 (VERIFIED) still gives 5 of 32 asked after, 3 between, 24 never. Adding an alternative can only
raise the asked count. NOT FOUND: any record in the diff or the ticket that the 14-day and 35-day runs were redone
on 717b402. Ticket 28 compares an "after" to this "before" on the same measure, so the "before" should be rerun
once on the final regex; if the counts do not move, say so in the ticket.

## Pinned quotes and coherence with ticket 03

- `skills/boss/test_policy.py:73` (VERIFIED) pins "and restarts at the next boundary if that is more than about 35";
  `skills/boss/SKILL.md:313` (VERIFIED) holds it; ticket 03 line 10 (VERIFIED) has the same "restarts". Round 2 N6
  fixed.
- `skills/boss/SKILL.md:312-315` matches ticket 03 line 10 word for word apart from the line breaks (VERIFIED).
- `skills/team/SKILL.md:77-79` (VERIFIED) still agrees with the boss rule: the worker stops unless the PR waits on
  CI or a merge, or the boss, having asked how much is left, says carry on.
- The turn unit is not defined in ticket 03; SKILL and team text agree with each other (R1 aside).

## Verdict

**GO.** N1 is fixed and tested; the new alternative cannot mislabel a worker's own report, and the incoming-message
false positives are class d. R1-R4 are class c: R1 (turn wording vs parallel tool calls) and R4 (rerun the "before")
are worth doing before ticket 28 reads its "after".
