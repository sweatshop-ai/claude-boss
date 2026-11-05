# Codex review, claude-boss PR 71, merge 5afec09 (first parent as base)

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr2
scope: base 5afec09^1
diff:  13 file(s), 454 changed line(s)
files:
  .scratch/boss-efficiency/issues/06-fewer-questions.md
  .scratch/boss-efficiency/reviews/pr-ticket-06-review.md
  CHANGELOG.md
  routines/boss_efficiency_core.py
  skills/boss/SKILL.md
  skills/boss/bin/boss-unask
  skills/boss/boss-guard.py
  skills/boss/references/concierge-brief.md
  skills/boss/references/concierge.md
  skills/boss/test_boss_efficiency.py
  skills/boss/test_boss_guard.py
  skills/boss/test_unask.py
  skills/boss/unask.py
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr2.
The secret check covers the diff listed above, not what Codex opens on its own.

The reporting flow can execute unintended shell text when its fixed heredoc delimiter appears in report content. Its damaged-line recovery also fails for torn Unicode records, potentially disabling listing and the weekly routine.

Full review comments:

- [P1] Replace the fixed `EOF` delimiter — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/skills/boss/SKILL.md:739-739
  When the captured question or owner wording contains a line exactly `EOF`—for example, when quoting a shell heredoc—the shell terminates this heredoc early and interprets the remaining report text as commands. Since the guard permits the whole invocation because it begins with `boss-unask`, benign report text can execute unintended commands; use collision-safe framing or a delimiter guaranteed absent from the content.

- [P2] Decode damaged report lines without aborting — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/skills/boss/unask.py:81-81
  If an interrupted append leaves a malformed UTF-8 sequence, which is possible because reports store Unicode, `read_text()` raises `UnicodeDecodeError` before the per-line damage handling runs. The malformed line remains, so `boss-unask list` keeps failing and `owner_reports()` crashes every weekly routine run; decode per line or tolerate decoding errors so damaged lines are actually skipped.

## Answers

Verdict: GO with two follow-ups. Class a/b/c/d: 0/2/0/0. Both citations VERIFIED against main (5afec09 and later); neither fixed by a later PR. Both in ticket 37.

- [P1] `skills/boss/SKILL.md:739`, fixed `EOF` heredoc delimiter in the `boss-unask record` example: a report line that is exactly `EOF` ends the heredoc and the rest runs as shell. Class b (needs an `EOF` line in a question or the owner's words; no outside attacker, the text is the worker's and the owner's own). Ticket 37.
- [P2] `skills/boss/unask.py:81`, `read_text()` on a torn UTF-8 record raises `UnicodeDecodeError` before the per-line skip; reproduced on main. `list` and the weekly routine fail until the file is fixed. Class b. Ticket 37.
