# 50: a daily token-cost report in Slack #claude-ops

**What to build:** decision 1 of `/home/tiroir/.claude/plans/2026-11-19-token-review-decisions.md` (owner's choice 2026-11-19: A). A routine in `~/.claude/routines/` (brain `token-cost.md`, body a script, pulse a systemd user timer at 08:00): from the local transcripts under `~/.claude/projects`, the previous day's tokens by type (input, cache write, cache read, output) and by session class (boss, worker, subagent, other), with the API-price equivalent, posted to Slack #claude-ops (credentials in `~/.config/tiroir/slack.env`). The measuring scripts of the 16–19 November analysis are the starting point, copied to `/home/tiroir/.claude/plans/2026-11-19-token-scripts/` (the plan names the scratchpad, which does not survive a reboot).

Calibration, part of A: for one week the owner notes the `/usage` percentage twice a day; the report keeps those notes beside the day's dollars so the ratio between dollars and the plan limit can be set. Ask the owner once, through the boss, where the notes go (a file the report reads is the default).

**Blocked by:** 49 (decision 5A order)

**Status:** ready-for-agent

- [ ] Test first: the script's counts on a small fixture of transcript lines match a hand count
- [ ] Timer installed and enabled; one run posts to #claude-ops (message permalink in the report)
- [ ] Nothing from transcripts beyond counts and session names leaves the machine
