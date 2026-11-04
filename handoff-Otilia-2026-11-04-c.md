# Handoff: Otilia, ticket 18 (refused restart retry), 2026-11-04

Gate-ready, not merged. PR 50 (sweatshop-ai/claude-boss), branch fix/refused-restart-retry, head 40d716f, worktree /home/tiroir/Projects/boss-plugin-wt/Otilia. CI pytest green. Ticket 18: boxes 1 and 3 ticked, box 2 open, Status in-progress until the merge.

Reviews: code-review (round 0) and Opus fallback GO on the head (round 1): .scratch/boss-efficiency/reviews/pr-50-round0-code-review.md, pr-50-round1.md. Codex follow-up owed from 23:38. Verdict posted on the PR.

Fixed: false "a turn started" (status is `waiting` under the exit dialog); `--wait-idle` timer retry. `shell` is read mid-turn, so it is retried, not accepted.

Open: box 2 (why the sampled pane read busy and no notice came is not shown); round-1 minor findings (octal `08`, BOSS_RETRY_EVERY validation and floor); `shell` turn-over vs turn-in-flight; `self_register` (boss-lifecycle.sh:171) stamps the calling pane as a boss on every invocation, which is what put @boss_pane=%64 on a worker pane.
Count script: scratchpad count.py (counts only).
No background task of mine runs; Otilia-test tmux server killed.
