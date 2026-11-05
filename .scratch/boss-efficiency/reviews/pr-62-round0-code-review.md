# PR 62 round 0: mattpocock-skills:code-review (head a733d0e)

## Standards
No documented repo standards (no CODING_STANDARDS.md, CONTRIBUTING.md, AGENTS.md, CLAUDE.md, docs/). Baseline smells, judgement calls only:
- Duplicated Code (minor): `child_is_gone` repeats the poll-for-exit loop at `skills/boss/test_boss_run.py:~224-228` (3 s / 0.1 s there, 10 s / 0.05 s here). Leave until a third copy appears.
- Mysterious Name (borderline): `child_is_gone()` blocks up to 10 s; the comment says why; sibling `child_pid()` has the same plain style.
- Primitive Obsession (trivial): inline `10`, `0.05`; the file uses inline literals elsewhere.
- None of the other nine smells.

## Spec (ticket 30)
- Partial: the 14-day list had no home beyond the PR body (no run ids, no denominator). Resolved: written into the ticket file (2 failed runs of the main-branch runs listed by `gh run list --status failure --created >=2026-10-22`; ids 41942504002, 41930248784).
- Extra, said in the PR body: `test_a_timeout_kills_the_reviewer_and_everything_it_started` has the same race and got the same change.
- "Some path" of the chain: `_stop` is one function with one path (TERM group, wait, KILL group, no branch skips KILL); the Opus round reads every caller.
- Repro script and mutant are throwaway and not in the diff; their numbers are in the PR body and the ticket.
