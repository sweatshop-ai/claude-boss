# Codex review, claude-boss PR 50, merge fa2062c

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr
scope: commit fa2062c
diff:  5 file(s), 160 changed line(s)
files:
  .claude-plugin/plugin.json
  CHANGELOG.md
  skills/boss/SKILL.md
  skills/boss/boss-lifecycle.sh
  skills/boss/test_boss_lifecycle.py
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr.
The secret check covers the diff listed above, not what Codex opens on its own.
The new retry window introduces stale-ownership and timeout issues, while the relaxed dialog status check can defeat the command's core protection against aborting an active turn when transcript pins are unavailable.

Full review comments:

- [P1] Revalidate pane ownership after waiting — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/skills/boss/boss-lifecycle.sh:344-348
  When this background retry is waiting, another boss can claim an initially unowned pane or deliberately take it over with `--force`. Ownership was checked only by `resolve_pane` before entering this loop, so the stale command will eventually send `/exit` to the now-foreign pane. Re-read and validate `@boss_pane` after the final status poll and before sending any keys.

- [P1] Reject unknown pins before confirming the exit dialog — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/skills/boss/boss-lifecycle.sh:370-373
  When the transcript is missing or unreadable, `--state` emits `-` for both `past` values. If a turn starts in the idle-check gap and the exit dialog changes its status to `waiting` or `shell`, this predicate treats `- == -` as proof that no turn started and confirms “Exit and stop tasks,” aborting the active turn. Require a non-placeholder past pin before accepting these non-idle dialog statuses, as the existing `--expect-last` validation does.

- [P2] Cap each sleep at the remaining timeout — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/skills/boss/boss-lifecycle.sh:344-346
  With the default 20-second interval, a timeout shorter than 20 seconds—or not divisible by 20—overshoots the advertised upper bound. For example, `--wait-idle 1` sleeps for 20 seconds and may restart a worker that became idle long after the requested deadline. Sleep for the smaller of the polling interval and the remaining time.

codex-review: output kept at /tmp/codex-review-Britt-cr-20261105T050131-1680252-review.txt (Codex's session log: /tmp/codex-review-Britt-cr-20261105T050131-1680252-review.txt.stderr)

## Answers

Verdict: GO. Three findings, none class a; two class b, one class d. Citations checked against fa2062c.

| # | Finding | Citation | Class | Answer |
|---|---------|----------|-------|--------|
| 1 | [P1] Pane ownership is checked once, by `resolve_pane`, before the `--wait-idle` retry loop; another boss can claim or `--force` the pane during the wait and the stale command then sends `/exit` to it | skills/boss/boss-lifecycle.sh:344-348 | b | VERIFIED: the loop (lines 342-349) never re-reads `@boss_pane`; `resolve_pane` is at 187-205. Needs a second boss taking the pane mid-wait. Ticket 32. |
| 2 | [P1] The exit-dialog branch accepts `waiting`/`shell` when `past2 == past`, but `--state` prints `-` for both when the transcript is missing, so a turn started in the gap goes unseen and "Exit and stop tasks" aborts it | skills/boss/boss-lifecycle.sh:370-373 | b | VERIFIED: boss-panes.py:234 prints `past or "-"`; the check at line 371 compares `$past2 == $past` with no placeholder test (the `--expect-last` check at 360 has one). Needs a missing or unreadable transcript plus a turn in the gap. Ticket 32. |
| 3 | [P2] Each sleep is the full 20 s interval, so `--wait-idle N` with N under 20 or not a multiple of 20 overshoots | skills/boss/boss-lifecycle.sh:344-346 | d | VERIFIED: `sleep "$every"` is not capped by `WAIT_IDLE - (SECONDS - t0)`. The overshoot only delays a restart of a worker that is idle, never types at a busy one. Ticket 32. |
