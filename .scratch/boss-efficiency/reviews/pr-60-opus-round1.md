# PR 60 (aurelio/ticket-03), Opus review round 1: bug hunt

Diff: `git diff origin/main...HEAD` in `/home/tiroir/Projects/boss-plugin-wt-aurelio` (6 files, +273/-2).
Read: `routines/ctx_over_measure.py`, `skills/boss/test_ctx_over_measure.py`, `skills/boss/test_policy.py` (diff),
`skills/boss/SKILL.md` (diff and context), `skills/team/SKILL.md` (diff and context), `skills/boss/policy.py:29`,
`routines/boss_efficiency_core.py:186-204`, the ticket `.scratch/boss-efficiency/issues/03-worker-context-limit.md`.
No transcript was read or scanned.

Tests run: `python3 -m pytest -q skills/boss/test_ctx_over_measure.py skills/boss/test_policy.py -p no:cacheprovider` → **12 passed**.

Classes as briefed: **a** wrong result or crash, **b** broken contract, **c** tests/docs/style, **d** far-fetched.

## Findings

### F1 (a): an ask sent before the 250k crossing is counted as "asked after the crossing"
`routines/ctx_over_measure.py:103` (VERIFIED) records an ask as `len(order)`, the index of the *next* assistant turn.
`routines/ctx_over_measure.py:117` (VERIFIED) takes `late = [a for a in asks if a >= over]`. When the ask arrives
after turn `over-1` (last seen context < 250k) and before turn `over`, `a == over`, so it is labelled late even
though the boss sent it while the worker was still under 250k (the turn that crosses is the reply to the ask).
Same off-by-one at the lower edge, `routines/ctx_over_measure.py:118` (VERIFIED): `split <= a` counts an ask sent
before the 150k crossing as "between". Fix: `late = a > over`, `early = split < a <= over`. Effect on the measured
figures (5 of 32 asked after, 4 between) is bounded by asks landing exactly on the crossing turn, but it moves
rows between the two buckets the ticket reports. No test covers `a == over`.

### F2 (a): the ASK regex matches ordinary boss traffic
`routines/ctx_over_measure.py:44` (VERIFIED). `(?:next|current) (?:boundary|stat)` has no word end after `stat`,
so it matches "current state", "current status", "next status" and "next state", all
common in boss check-ins ("what is your current status?"). `stop at the` matches "stop at the first failure".
`CTX-(?:OVER|SPLIT)` matches any peer message that merely mentions a flag (a peer worker reporting its own
`CTX-SPLIT`). Any such message after the crossing sets `asked_after` (`:117`, `:120`, VERIFIED) and starts the
`turns_after_ask` clock (`:123`, VERIFIED). Fix: `\bstat(?:e|us)?\b` → drop the `stat` alternative, anchor
`stop at the (?:next|very next)`, and drop bare `CTX-…` or require it with an imperative.

### F3 (b): the worker rule in team/SKILL.md contradicts the boss rule and the ticket decision
`skills/team/SKILL.md:77-78` (VERIFIED): "past ~250k the split is overdue — stop at the very next boundary, unless
your PR is open and waiting on CI or a merge". The ticket decision (issue 03, line 10, VERIFIED) and
`skills/boss/SKILL.md:312-315` (VERIFIED) say a worker past 250k is restarted only if more than about 35 turns are
left. A worker at 260k with 10 turns left is told by team/SKILL.md to stop at the next boundary, and by the boss
rule not to be restarted. The worker text needs the same "more than about 35 turns left" condition, or should
defer to the boss's ask when it works for a boss.

### F4 (b): "turns" is not the same unit on both sides
The 35-turn threshold and the 19k/39k per-turn costs count assistant API messages (one per message id:
`routines/ctx_over_measure.py:93-97`, VERIFIED; `routines/boss_efficiency_core.py:240`, VERIFIED). The worker is
told "When your boss asks how much is left, answer in turns" (`skills/team/SKILL.md:78`, VERIFIED) with no
definition; a worker reads "turn" as an exchange with its user, each of which is many API calls. Its estimate will
be low by a large factor, so the ">35 turns" test will almost never fire. Define the unit (tool calls / model
calls) in both SKILL texts, or ask for the estimate in another form.

### F5 (c): "Two tests, both" introduces two mutually exclusive branches
`skills/boss/SKILL.md:309` (VERIFIED) "Two tests, both:" then `:311` "never restart" and `:312` "Anything else"
(VERIFIED). They are cases of one rule, not two tests that must both hold. Taken from the ticket's "1 & 2", but it
reads as a conjunction. Suggest "Two cases:".

### F6 (c): the 150k rule has no PR-open exception, the 250k rule does
`skills/boss/SKILL.md:302-305` (VERIFIED) and `:989-990` (VERIFIED): a worker crossing 150k is asked for a
boundary and restarted, unconditionally. At 250k a worker waiting on CI with its PR open is never restarted
(`:311`). So a worker at 200k waiting on CI is restarted and the same worker at 260k is not. Outside the ticket's
scope (it decided only past 250k), but the text is now less strict at the higher threshold.

### F7 (c): docstring promises a match the regex does not make
`routines/ctx_over_measure.py:17-18` (VERIFIED) says a boundary ask is a message wording "handoff", "boundary",
"restart", "split". The regex (`:44`, VERIFIED) matches none of those words alone: "please hand off and restart"
or "at your next natural boundary" (the SKILL's own wording, `skills/boss/SKILL.md:303`, VERIFIED) is missed
unless "write the handoff" also appears. Under-counts asks; docstring should describe the regex.

### F8 (c): median printed with `%d`
`routines/ctx_over_measure.py:174` and `:177-178` (VERIFIED): `statistics.median` returns `x.5` on even counts and
`%d` floors it. Cosmetic. Empty-list cases are guarded (`:170`, `:175`, VERIFIED); `pct` guards zero
denominators (`:153-154`, VERIFIED); `statistics.median` accepts the generator at `:174` (it sorts its input).
`report([] , 0)` prints `n/a` throughout, no crash.

### F9 (c): "private file" is written with the default umask, not atomically
`routines/ctx_over_measure.py:5-7` (VERIFIED) calls the output private; `:148` (VERIFIED) uses `write_text`, so the
mode is whatever the umask gives (usually 0644) and an `--out` whose parent does not exist raises
`FileNotFoundError` after the whole scan. Rows hold only basenames and numbers (`:113-115`, VERIFIED), so the
leak is small. Use `os.open(..., 0o600)` or chmod, and `mkdir(parents=True)`.

### F10 (c): tests do not cover the paths the brief asks about
`skills/boss/test_ctx_over_measure.py:33-57` (VERIFIED) covers is_worker, one ask after the crossing, and never
asked. Missing: `isSidechain` lines skipped (`ctx_over_measure.py:90`), a message id repeated over several lines
(`:95-97`), a `tool_result` user line carrying the ask words (`:99-100`), an ask landing exactly on the crossing
turn (F1), an ask between 150k and 250k (`asked_between`, `:118`/`:121`), and `report()` at all, including empty
input. The asserted numbers that exist are right: crossing at index 8 (100k+8·20k = 260k), split at 3 (160k),
`left_at_cross` 15-8 = 7, `turns_after_ask` 15-10 = 5 (VERIFIED by reading `:41-50` against `:106-123`).

### F11 (d): non-object JSON lines crash both readers
`routines/ctx_over_measure.py:60-63` (VERIFIED): a line that parses to a list or string (e.g. a JSON string
literal containing "Boss dispatch from ") makes `d.get` raise `AttributeError`, which `is_worker` does not catch
(it catches only `OSError`, `:67`). Same in `scan` at `:87-92` (VERIFIED), and a non-dict `message` or a list
`message.id` (unhashable, `:95`) also crashes. Claude Code writes objects only, so far-fetched; a `isinstance(d,
dict)` guard costs one line.

### F12 (d): is_worker stops at the first matching user line
`routines/ctx_over_measure.py:64-66` (VERIFIED) returns on the first non-sidechain, non-tool_result user line that
contains "Boss dispatch from ", whether or not it carries `<cross-session-message`. A session whose owner first
types or pastes those words and is dispatched later reads as not a worker; a boss whose first incoming worker reply
quotes the header in its first 400 characters reads as a worker. The PEEK counter (`:54-56`, VERIFIED) counts
characters, not bytes as the docstring says (`:4`). All edge cases.

### F13 (d): races in main()
`routines/ctx_over_measure.py:136` (VERIFIED): `p.stat()` inside the glob comprehension raises if a transcript is
removed between glob and stat; `scan` (`:84`) has no `OSError` guard either. `:139-140` (VERIFIED) calls
`getloadavg()` twice, so the printed load can differ from the tested one. Far-fetched.

## Checked and correct

- Message-id dedup: `order` gets each id once, `turns` keeps the last line's usage (`:95-97`, VERIFIED), which is the
  final usage of a streamed message. Turn count and cost are per API message, consistent with
  `boss_efficiency_core.py:240` (VERIFIED).
- Sidechain lines are skipped before any counting (`:90`, VERIFIED); tool_result user lines never count as asks
  (`:99-100`, VERIFIED).
- `first()` (`:109-110`, VERIFIED) returns the first crossing even after a compaction lowers context; `cost_over`
  (`:115`, VERIFIED) sums only turns whose own context is ≥250k, which is what "spent above 250k" means.
- `usage()` sanitises non-numeric and out-of-range fields (`boss_efficiency_core.py:186-192`, VERIFIED), so odd
  usage blocks cannot crash the sums.
- `test_policy.py` quotes (diff lines added at `skills/boss/test_policy.py:72-74`, `:94`, VERIFIED) match the SKILL
  texts; the run passes.
- The SKILL.md paragraph matches the ticket decision word for word (`skills/boss/SKILL.md:309-315` against issue 03
  lines 7-10, VERIFIED); the measured figures in SKILL.md `:317-320` and CHANGELOG match the ticket's line 18.

## Verdict

**NO-GO.** Two class a findings in the measure (F1 off-by-one on the crossing, F2 regex false positives on
"current status" and similar) and two class b findings in the wording (F3 team/SKILL.md tells a worker to stop
regardless of turns left; F4 "turns" undefined for the worker). All four are small fixes; F1 and F2 should come
with a test each and a rerun of the measure, since the ticket's 5/4/23 split rests on them.
