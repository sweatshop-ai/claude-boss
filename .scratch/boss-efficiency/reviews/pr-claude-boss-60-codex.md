# Codex review, claude-boss PR 60, merge 482b0e4

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr
scope: commit 482b0e4
diff:  2 file(s), 296 changed line(s)
files:
  CHANGELOG.md
  skills/boss/SKILL.md
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr.
The secret check covers the diff listed above, not what Codex opens on its own.
The new operational rule uses a turn definition inconsistent with the measurement underlying its 35-turn threshold, which can cause unnecessary worker restarts when tool calls are batched.

Review comment:

- [P2] Count parallel tool calls as one turn — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/skills/boss/SKILL.md:319-320
  When a model message batches multiple tool calls, they share one message ID and the measure counts them as one turn, but this instruction tells workers to count every tool call separately. That inflates remaining-turn estimates and can trigger a restart when no more than 35 chargeable model turns remain; define a turn as one model message regardless of its number of tool calls, and update the duplicate wording in `skills/team/SKILL.md:79`.

codex-review: output kept at /tmp/codex-review-Britt-cr-20261105T045333-1612072-review.txt (Codex's session log: /tmp/codex-review-Britt-cr-20261105T045333-1612072-review.txt.stderr)

## Answers

Verdict: GO, with one class b finding.

| # | Finding | Citation | Class | Answer |
|---|---------|----------|-------|--------|
| 1 | [P2] SKILL.md defines a turn as "each tool call", but `ctx_over_measure.py` counts one turn per assistant message id, so batched tool calls share one turn and workers overcount remaining turns against the 35 threshold | skills/boss/SKILL.md:319-320, skills/team/SKILL.md:79 | b | VERIFIED at 482b0e4: both files say "one turn is one model message, so each tool call is its own turn"; routines/ctx_over_measure.py:82-97 keys turns by `message.id`. Ticket 32. |
