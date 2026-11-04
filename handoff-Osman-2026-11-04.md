# Handoff: ticket 22, PR 52 (Osman, 2026-11-04 ~23:25)

Spec: `.scratch/boss-efficiency/issues/22-lifecycle-follow-ups.md` (status in-progress, claimed by Osman).
Worktree `/home/tiroir/Projects/boss-plugin-wt-22`, branch `ticket-22-lifecycle`, PR https://github.com/sweatshop-ai/claude-boss/pull/52, head `d771a25`, CI `pytest` green on it. Not merged; merge only when Anton says.
Git identity in the worktree is set (`tiroir <202564+tiroir@users.noreply.github.com>`). Public repo: no client names, no measured client data, no transcript text.

## Accepted by Anton
Items 1, 2, 3, 4, 6 and 7 stand as pushed. Item 3 decision: `--wait-idle` runs without `--expect-last` (SKILL.md and PR say so).

## The change still to build (Anton's call, not a review finding), word for word
Item 5's behaviour has to change. PR 52's `restart --require-idle` goes through on `shell` with the turn over and stops the job, with no opt-out. A finished turn does not mean a finished task: workers sit turn over, one Monitor armed, waiting for CI on a merge they still have to report. A restart would kill the monitor and lose the rest of the task, with only a printed line afterwards; a boss cannot read that line before it fires.

1. Default: `shell` with the turn over is still refused, and `--wait-idle` keeps waiting. The refusal now says what it knows: "turn over, background work still running", with each job listed. That is the signal found (`turn_duration` last), and it is what a boss was missing.
2. Opt-in: a new explicit flag, for example `restart --require-idle --stop-shells`, is what makes it go through and stop them, printing each job, for a boss that has looked. `--force` must not imply it.
3. Tests: refused by default with the job list, through with the flag, and a turn in flight with a shell refused even with the flag.
4. SKILL.md and CHANGELOG say this: a Monitor waiting on CI is the normal case of a worker between turns, so look at the pane or ask the worker before using the flag.

Where it lands in `skills/boss/boss-lifecycle.sh` (head d771a25):
- `still_busy` (~340): `shell` is busy unless the fifth `--state` field is `1`. Keep that; without the flag, `shell` stays busy even with the field `1`, but the refusal message differs (turn over vs in flight) so the wait loop can keep waiting.
- The idle gate (~385) and the message printed before `/exit` ("its turn is over and a background shell is still running; the restart will stop it") become the flag path. The job list is on screen only after `/exit` opens the "Background work is running" dialog (`stop_leftover_background`). To list jobs in the refusal, a boss cannot type `/exit`; read the pane instead (`tmux capture-pane`; the footer shows `N shell(s)` and the dialog is not up). Decide whether the refusal lists only the count plus a pointer to the pane, or parses a job list from somewhere that needs no keystroke: that is the open design point, check what the pane/status file actually shows before promising "each job listed".
- Parse the new flag next to `--force` / `--require-idle` (arg loop at the top), require it with `--require-idle` like the others, and keep `--force` from setting it.
- Tests go in `skills/boss/test_boss_lifecycle.py` (`RequireIdle`): `test_shell_with_the_turn_over_is_restartable_and_the_stop_is_said_first` becomes the flag test; add default-refused-with-message and in-flight-refused-with-flag. `run_waiting` takes `wait=` and `extra_env=`; rows can carry the fifth field.
- Update the PR body ("What happens to the shell"), `CHANGELOG.md` (Unreleased entry for ticket 22) and the SKILL.md restart paragraph. A fix after the last GO means a new second-model verdict on the new head, and a re-run of CI on that head (push once).

## Probe recipe (real pane, throwaway server)
- `tmux -L <name> -f /dev/null new-session -d -s p -c <scratch dir>`, then `claude --model sonnet --effort low --allowedTools 'Bash(sleep:*)'` (the classifier refuses a bypass-permissions launch; do not work around it). Accept the trust dialog (Down, Enter). Text and Enter must be sent as separate `send-keys` calls with a short gap (`C-m` works), or the prompt is not submitted.
- Prompt "Run Bash with run_in_background true: sleep 900. Then reply with the word armed" gives status `shell` once the turn ends; read `boss-panes.py --state %0` with `TMUX="$(tmux -L <name> display -p '#{socket_path}'),0,0"` (fields: session, status, pin, past-exit pin, turn-over 1/0). A turn with a foreground `sleep 40` reads `busy`, over 0.
- Run the script under test as `TMUX_PANE=%1` (a second pane) so it does not refuse the worker pane; `BOSS_WORKER_MODEL=sonnet BOSS_WORKER_EFFORT=low` for the relaunch. Print `realpath` of the script (P17).
- Kill the server, remove `/tmp/tmux-1000/<name>`, check `ps` for nothing left.
- Measured on 2.1.311: with a turn running, status `busy` throughout (a bg shell does not change it); after the turn `shell` and the last turn record is `system`/`turn_duration`; the screen shows "N shell still running".

## Open follow-up (small)
`stamp-self` never removes a stamp: worker panes stamped as their own boss by the old `self_register` keep `@boss_pane` until the pane is reused (clear with `tmux set-option -pu -t <pane> @boss_pane`). Not in the CHANGELOG; add a line or a ticket.

## Opus findings (fresh agent, GO on d771a25), `.scratch/boss-efficiency/reviews/pr-52-round1-opus.md`
Minor: two sessions in one pane make `stamp-self` judge the oldest (fails safe); the old stamps stay; a shell that ends between the status read and `/exit` can lose the turn it wakes (existing gap race); 32 of 60 recent transcripts end on `end_turn` without `turn_duration`, so such a worker in `shell` is refused (NOT FOUND whether that hits live workers). Codex follow-up owed from 23:38 (Codex was out at 23:14). Code-review round 0: `pr-22-round0-code-review.md`.

## Left on the machine by the probe (for Anton to report to the owner)
- `~/.claude.json`, key `projects["/tmp/claude-1000/-home-tiroir-Projects-boss-plugin/e5871745-ed46-4dce-94aa-b0057457b9c5/scratchpad/probe"]` with `hasTrustDialogAccepted: true`. Not edited.
- Probe transcripts: `~/.claude/projects/-tmp-claude-1000--home-tiroir-Projects-boss-plugin-e5871745-ed46-4dce-94aa-b0057457b9c5-scratchpad-probe/`.
- Another probe entry for `.../a30c4845-d74c-448a-910c-3e655ea6d83a/scratchpad/probe` is not mine.

Nothing of mine is running: no tmux server, no process, no loop; the worktree is clean at d771a25.
