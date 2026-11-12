# 37: The pulse tells the boss to ask again a blocker the owner has already answered

**What to build:** `render()` in `skills/boss/pulse.py` printed "BLOCKED, and you are ending your turn without asking" for every line under `## Open blockers`, and `decide()` put an `ask` action first, even when the owner had answered. The answer is `- [codex-choice <blocker id>] <choice> - <ts>` under Decisions in force, written by `codex_blocker.py --choose` (ticket 09b). The pulse therefore told the boss to put the same question to the owner again, which breaks "never send a question twice" in `references/concierge.md`. On the codex-down track it fired on every turn from 21:44.

`boss-pulse.py` now asks `codex_blocker._state` (the reader of 09b, no second parser) whether the one open Codex down blocker has a valid recorded choice. An entry whose own marker carries that blocker's id is taken out of `facts.blockers` and goes into the new `facts.decided`; `render()` shows it as `DECIDED by the owner, do not ask again: <entry> (owner chose <choice>)`, so it is not dropped silently, and `decide()` adds no `ask` for it. A choice that is malformed, one recorded for another blocker id, one outside Decisions in force and a tracker with several open Codex down lines decide nothing: the blocker stays BLOCKED. Rungs: a line with a ladder marker is already skipped by `due_rungs` (boss-ladder.timer owns it), so a decided blocker presses none; a test pins it.

**Blocked by:** none

**Status:** done (Runa built it)

- [x] A blocker with a valid recorded choice is not listed as BLOCKED and adds no `ask` action; it is shown as decided with its choice (`skills/boss/test_pulse_choice.py`)
- [x] A malformed choice, one for another blocker id, one outside Decisions in force: the blocker stays BLOCKED
- [x] The last recorded choice is the one shown
- [x] A decided blocker presses no rung of the pulse's own (a marked line never did; boss-ladder.timer owns the cd line's rungs and this ticket does not touch it)
- [x] A cd line closed by hand with a marker that does not parse, a line separator inside a marker, two open cd lines and a CRLF tracker do not crash the hook
- [x] The choice is read with `codex_blocker`'s reader, not a second parser
- [x] Tests use `hermetic.Sandbox`, install the `codex`, `claude`, `gh` and `tmux` stubs and read their call logs (`expect_unused`, and tmux only ever `list-panes`)
- [x] CHANGELOG.md has the entry
