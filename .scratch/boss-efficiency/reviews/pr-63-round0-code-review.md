# PR 63, round 0: Standards and Spec (head 152dea5)

No coding-standards file exists in the repo (CODING_STANDARDS.md, CONTRIBUTING.md, AGENTS.md, CLAUDE.md: NOT FOUND). skills/boss/SKILL.md holds no coding conventions (VERIFIED).

## Standards
- Breaches of a documented standard: 0.
- Judgement calls (baseline smells), all mild:
  - Duplicated Code: the env-stripping comprehension in `tmux()` and `watch()` (VERIFIED). Fixed: `bare_env()`.
  - Mysterious Name: `self.boss` (VERIFIED). Fixed: `boss_pane`.
  - Module constant `LIFECYCLE` sat mid-file, away from `SCRIPT` and `FIXTURES` (VERIFIED). Fixed: moved up.
  - Data Clumps (`env=, capture_output=True, text=True`): the file's own style, left.
  - Primitive Obsession (TMUX value assembled from a format string; `r.stdout.split()[0]` ties the test to the output of `spawn`): left; `spawn` prints `<pane>\t<name>` and the test needs that pane.
- Ticket cites line numbers that will drift: accepted, tickets are point-in-time.

## Spec
- Citations: lifecycle line 292 VERIFIED; watchdog line 59 VERIFIED; `grep -n -i registry routines/boss-workers-watch.sh` prints nothing, VERIFIED; header lines 7-9 VERIFIED; `--concierge` sets ROLE at lifecycle line 62 VERIFIED; the three named existing tests VERIFIED (lines 77, 94, 98).
- Wrong in the ticket: test line 52 is `def run_watch`, the TSV write is line 55 and the role is a parameter. Fixed in the ticket.
- Missing: no mutant evidence and no ticked boxes in the diff. Fixed: both mutants and the unmutated run are recorded in the ticket.
- Scope: the control (mark removed, same screen alerts) is not in the ticket; kept, it shows the silence comes from the mark.
- Unverified by the reviewer, verified by the author: that `pane_current_command` reports `claude` for `exec -a claude sleep` (the test passes only if it does).

Summary: Standards 0 breaches, 5 mild smells (3 fixed); Spec 2 findings, both fixed.
