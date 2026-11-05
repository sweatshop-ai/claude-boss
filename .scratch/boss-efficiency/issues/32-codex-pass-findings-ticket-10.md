# 32: Findings of the Codex pass on the merged PRs (ticket 10)

**What to build:** Codex, run once on the merged diff of each PR (2026-11-05, Britt), found the items below. Each is a ticket-sized fix, not a revert; none is fixed here. Raw output and the answers are in `.scratch/boss-efficiency/reviews/pr-claude-boss-<n>-codex.md`. Class: a security property broken, data loss, wrong behaviour on a normal path; b wrong behaviour on an unusual realistic path; c far-fetched; d tests, docs, style. All citations were checked against the merge commit and are VERIFIED.

**Blocked by:** None (can start immediately)

**Claimed by:** nobody

**Status:** ready

- [x] a. (moved to ticket 35, not ready work here) PR 49, `routines/boss_efficiency_core.py:391-393`: asks are counted only from boss sessions. The guard refuses the boss's own AskUserQuestion while a concierge lives, so the concierge's questions are attributed as a worker and never counted; questions/day and its alert (lines 497-498) read near zero in the standard workflow.
- [ ] b. PR 49, `install.sh:50-51`: the new timer and service exist only for users who rerun `install.sh`; `bin/boss-link` moves the symlink only. Same cause as the MemoryMax finding of PR 53 (ticket 25) and ticket 33 R4-9; one fix serves all.
- [ ] b. PR 49, `systemd/boss-efficiency.service.in:8`: no `Environment=CLAUDE_CONFIG_DIR=@CFG@`, so a non-default config dir is ignored under systemd (the watchdog unit has the same gap).
- [ ] b. PR 49, `routines/boss_efficiency_core.py:638-640`: a week with anomaly flags is added to the history and the state written before `alert()` runs; if Slack fails, that week is the next baseline and a persistent change is never reported.
- [ ] b. PR 49, `routines/boss-efficiency.sh:34-40`: a lock wait of two hours or a `timeout` kill only logs and exits 1; the core's Slack failure path never runs, so a missed week sends no alert.
- [ ] b. PR 49, `routines/boss_efficiency_core.py:302-305`: persisted socket-to-track ties never expire; socket paths carry the pid, so a reused path keeps its old track until two new votes.
- [ ] b. PR 50, `skills/boss/boss-lifecycle.sh:344-348`: pane ownership is checked once, by `resolve_pane`, before the `--wait-idle` loop; another boss can claim or `--force` the pane during the wait and the stale command then sends `/exit` to it. Re-read `@boss_pane` after the last status poll.
- [ ] b. PR 50, `skills/boss/boss-lifecycle.sh:370-373`: with a missing or unreadable transcript `--state` prints `-` for both pins, `$past2 == $past` holds, and a turn started in the gap is not seen before "Exit and stop tasks" is confirmed. Require a real past pin, as the `--expect-last` check at line 360 does.
- [ ] d. PR 50, `skills/boss/boss-lifecycle.sh:344-346`: the sleep is the full 20 s interval; `--wait-idle N` with N under 20 or not a multiple of 20 overshoots. Sleep the smaller of the interval and the time left.
- [ ] b. PR 48, `routines/boss-workers-watch.sh:111`: a concierge answer option such as `Yes, and always use sonnet` matches `Yes, and (always|don.t ask)` in the last 15 lines and raises the permission alert the change meant to prevent.
- [ ] b. PR 48, `routines/boss-workers-watch.sh:111`: on a narrow pane a real prompt wraps (`Do you want to make` / `this edit`, a split `Tab to amend`); grep matches per line and the `❯ 1. Yes` fallback is off for concierges, so the prompt is never seen.
- [ ] b. PR 48, `routines/boss-workers-watch.sh:100`: `tail -n 15` of the capture takes blank rows when 15 or more empty rows sit below the dialog (reproduced with `tmux capture-pane -p -S -40` on a fresh pane). Take the last non-blank rows.
- [ ] b. PR 60, `skills/boss/SKILL.md:319-320` and `skills/team/SKILL.md:79`: a turn is defined as each tool call, while `routines/ctx_over_measure.py:82-97` counts one turn per assistant message id; batched calls make workers overcount against the 35-turn line.
- [ ] d. PR 59, `skills/boss/SKILL.md:862-872`: the self-contained worker dispatch leaves out the rule that `code-review` runs once per PR (stated at line 616).
