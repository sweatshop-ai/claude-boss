# Handoff: Otilia, ticket 17 (2026-11-04)

**State.** Code, tests, rerun and ticket figures are done. The branch is NOT pushed (Anton: wait for Rune's PR 19 on the same routine to merge; he gives the go).

- Worktree: `/home/tiroir/Projects/boss-plugin-wt/Otilia`, branch `otilia/ticket-17`, based on `a945a12` (origin/main then).
- 3 local commits: names and track end in `routines/boss_efficiency_core.py` plus tests; the doc `routines/boss-efficiency.md`; the shared `Index.clip_end` and tighter tests. 45 tests pass; imports come from the worktree copy (P17 proof: `/home/tiroir/Projects/boss-plugin-wt/Otilia/routines/boss_efficiency_core.py`).
- Git identity in the worktree: `tiroir <202564+tiroir@users.noreply.github.com>`.
- Round 0 review (mattpocock code-review, code only): `.scratch/boss-efficiency/reviews/pr-ticket17-round0-code-review.md`.
- Ticket: `.scratch/boss-efficiency/issues/17-count-workers-by-name.md`, boxes ticked, Result section written, status in-progress until merge. Private per-track rerun: `~/.claude/pm/boss-efficiency.rerun-2026-11-04/report.md` (cache in the same folder; no transcript text in the repo).

**Next session**
1. After Anton's go: `git fetch`, rebase once on origin/main (Rune's PR 19 touches the same core: expect conflicts in `boss_efficiency_core.py` and `test_boss_efficiency.py`; rerun the touched test file at load under 8 and re-prove the import path).
2. Push the branch once (head to gate), open the PR with the `mattpocock-skills:pr` body style, ending with the Claude Code line; check `gh run list --status queued` first (P16), cancel only your own superseded runs.
3. CI: check `.total_count` then conclusions for the head sha.
4. Second-model verdict on the head: Codex (back 23:38) on code and synthetic fixtures only, never transcripts; if it fails, a fresh Opus agent and record that a Codex follow-up is owed. Save output in `.scratch/boss-efficiency/reviews/`, post the verdict on the PR with citations marked VERIFIED or NOT FOUND. At most 3 rounds; a fix after the last GO needs a new verdict on the new head.
5. Report gate-ready to Anton: PR number, head sha, CI result, review paths, proof line. Do not merge until told.

**Known limits (in the ticket and doc):** only 2,654 of 10,030 sessions record a start name; a track is cut only if its last `boss-goal status` is met; the "done" commit is read from the transcript command.
