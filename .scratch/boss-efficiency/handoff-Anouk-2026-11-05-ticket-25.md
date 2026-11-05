# Handoff: Anouk, ticket 25, PR 56 (claude-boss), 2026-11-05

**State:** PR 56 https://github.com/sweatshop-ai/claude-boss/pull/56 is open, not merged, `mergeable=false, dirty` (conflicts with main after PRs 59 and 61). No CI has run on the remote head.

- Worktree: /home/tiroir/Projects/boss-plugin-wt-anouk, branch `anouk/ticket-25`.
- Remote head: 94d4644 (verdict GO from fresh Opus on that head; rounds in reviews/).
- **Local branch is already rebased onto origin/main, NOT pushed** (I started the rebase before Anton's stop message arrived). Only CHANGELOG.md conflicted; I kept both entries. Local head after rebase: see `git rev-parse HEAD` in the worktree (the 6 commits replayed). It is untested after the rebase and has no verdict: after you run the touched tests (test_boss_guard, test_fleet, test_boss_lifecycle, test_version_gap, test_bin, test_policy) and push, the head that merges needs a new second-model verdict (fresh Opus; Codex back from 04:38 may do it, and a Codex follow-up on PRs 56's content is owed anyway). Check `gh run list --status queued` before pushing; runner pool is small (P16).
- Reviews: /home/tiroir/Projects/boss-plugin/.scratch/boss-efficiency/reviews/pr-claude-boss-56-round1-code-review.md, pr-claude-boss-56-opus-round1.md, pr-claude-boss-56-opus-round2.md.
- Ticket: .scratch/boss-efficiency/issues/25-codex-findings-claude-boss.md (boxes ticked, status in-progress).

**To do (Anton's instruction):**
1. Fix `install.sh`: a re-run overwrites an edited unit with no copy (install.sh:48-53). The owner runs it after the history rewrite. Apply the same rule as boss-link (copy a differing existing unit to `<unit>.bak-<YYYY-MM-DD-HHMMSS>` first, print the path), with a test on a temp HOME and a stub systemctl. Never run install.sh against the real ~/.config.
2. Push the rebased branch, wait for CI on the new head, then a new verdict (round 3 at most).

**Class c findings left open (round 2 verdict):**
- `cp -n` prints a "non-portable -n" warning on stderr at every refresh (bin/boss-link:54); `--update=none-fail` is quiet.
- The three `.service.in` headers say `.bak-<date>`; the real name is `.bak-YYYY-MM-DD-HHMMSS` (README is right).
- Copies are never pruned.
- A failing copy makes boss-link exit 1 at each session start and skips the other units.
- One `.bak` per service file on the first upgrade (headers changed the content).
- From round 1: a sed program with a backslash counts as work (tracker tick `s/- \[ \]/- [x]/` is warned); a concierge with no session record yet is skipped by spawn's lookup (fleet.py:176); a `#` before a heredoc marker counts as work.

**Running:** nothing. The wait loops are stopped.
