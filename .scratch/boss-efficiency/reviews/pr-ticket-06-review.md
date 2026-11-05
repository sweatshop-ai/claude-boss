# Ticket 06: review of the owner's "not this kind of question" report

Head reviewed: see the PR comment. Diff: 12 files, about 360 added lines (tests and docs included). Name grep: no hit.
Codex: owed (out of tokens until 09:41 on 2026-11-05); Opus ran in its place, two rounds.

## Standards and Spec (mattpocock-skills:code-review), round 0

Fixed:
- Guard allow-list had no test for the heredoc form the skill teaches: test added.
- Owner's words were cut at 1000 characters like the question: words now get 4000.
- `proposal()` text had its bold stripped after the fact: plain text now, bold added by `render`.
- `fromisoformat` on a `Z` date relied on Python 3.11: `Z` is replaced explicitly.
- Concierge path did not say which track the boss records under, nor that a mid-session report must be re-read: both said in SKILL.md P12.
- A short write could leave a torn line: the file object now finishes the write.

Not changed, by design: the irreversible/own-hand carve-out (the owner's "you can take the decision yourself" does not reach a deletion that cannot be undone; the ticket's own measurement was about that case); a proposal raising a Slack alert (the routine's only channel).

## Opus bug hunt, round 1 (Codex substitute)

- [P2] Double close of the fd on a failed write, and a torn last line swallowing the next report. FIXED: one file object owns the fd; a missing final newline is repaired before the next append. Tests added.
- [P2] A plain `---` line inside the question split it in the wrong place. FIXED: the separator is `--- owner ---`. Test added.
- [P2] `read()` did not re-check track and kind. FIXED, test added.
- [P2] Windows are `[now-7d, now)`, not tied to the timer, so a late run leaves a gap and the next overlaps. NOT FIXED here: every weekly measure shares it, and the proposal total is cumulative, so a report in a gap still counts toward a later proposal. Ticket line.

## Opus round 2 (delta only)

GO. One P2: `KIND_RE` ended in `$`, which accepts a trailing newline. FIXED with `fullmatch`, test added. `TRACK_RE` in `boss_store.py` has the same `$`: outside this ticket, ticket line.

Three rounds are used. Nothing else is open at class a or b.

## Left as ticket lines

- Window drift of the weekly routine (above).
- `TRACK_RE` in `boss_store.py` accepts a trailing newline.
- Kind slugs are chosen freely by each session, so two names for one kind under-count; revisit when real reports exist.
- The live test in a real session: owed, see the ticket.
