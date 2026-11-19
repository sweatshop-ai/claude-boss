# 50: a daily token-cost report in Slack #claude-ops

**What to build:** decision 1 of `/home/tiroir/.claude/plans/2026-11-19-token-review-decisions.md` (owner's choice 2026-11-19: A). A routine in `~/.claude/routines/` (brain `token-cost.md`, body a script, pulse a systemd user timer at 08:00): from the local transcripts under `~/.claude/projects`, the previous day's tokens by type (input, cache write, cache read, output) and by session class (boss, worker, subagent, other), with the API-price equivalent, posted to Slack #claude-ops (credentials in `~/.config/tiroir/slack.env`). The measuring scripts of the 16–19 November analysis are the starting point, copied to `/home/tiroir/.claude/plans/2026-11-19-token-scripts/` (the plan names the scratchpad, which does not survive a reboot).

Calibration, part of A: for one week the owner notes the `/usage` percentage twice a day; the report keeps those notes beside the day's dollars so the ratio between dollars and the plan limit can be set. Ask the owner once, through the boss, where the notes go (a file the report reads is the default).

**Blocked by:** 49 (decision 5A order)

**Claimed by:** Saskia 2026-11-19 16:19

**Status:** done

- [x] Test first: the script's counts on a small fixture of transcript lines match a hand count
  Evidence: `python3 -m pytest /home/tiroir/.claude/routines/test_token_cost.py -q` → `12 passed`; red first (collection error, script absent). Real run for 2026-11-18 totals $484, equal to the analysis figure for that day.
- [x] Timer installed and enabled; one run posts to #claude-ops (message permalink in the report)
  Evidence: `systemctl --user start token-cost.service` → exit 0, journal `posted: https://thinkingtoo.slack.com/archives/C0B9T1CE6CT/p1795102013673999`, `Finished token-cost.service`; `list-timers`: NEXT Fri 2026-11-20 08:00:00 CET. Units committed in ~/.claude/routines (commits 8e6bf61, 2160fa0, 4b1a421; `git log origin/main..HEAD` empty).
- [x] Nothing from transcripts beyond counts and session names leaves the machine
  Evidence: tests `test_post_carries_only_counts_names_and_models` and `test_odd_model_string_never_reaches_the_post`; names only from the agent-names pool, model ids only if `[A-Za-z0-9.-]{1,40}`; format checked by Aisha before the post.
