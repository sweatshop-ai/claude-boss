# 22: Lifecycle follow-ups from PR 50: wait-idle edges, `shell` status, self-stamping

**What to build:** four small fixes and one measurement in `boss-lifecycle.sh`, left open by ticket 18's review (PR 50, round 1).
1. `--wait-idle 08` is read as octal in the arithmetic: the loop is skipped and the restart dies "still busy" without waiting. Nothing is typed. Read the value as base 10.
2. `BOSS_RETRY_EVERY`: validate it (a number; a non-number stops the script on sleep's own error with no `ERROR:` line) and floor it at 1 s (0 busy-loops a python status read for up to the whole wait).
3. `--wait-idle` with `--expect-last` always ends in a refusal when a wait happened, because the busy turn writes new records; without a pin it restarts after whatever turn ran meanwhile, including a task a peer gave it that the boss never saw. Decide which the skill says, and say it in SKILL.md.
4. Tests for a non-numeric `--wait-idle` value and for `--wait-idle --force`.
5. `shell` (a background shell running) is read mid-turn and after the turn, so it is refused as not idle. Find a signal that tells "turn over, background shell left running" from "turn in flight" (the transcript's last record, the screen), so a worker that finished is restartable; 41 of 237 refusals in five weeks of boss transcripts read `shell`.
6. `self_register` (`boss-lifecycle.sh:171-172`) stamps the calling pane with itself on every invocation, so a worker that runs the script becomes a boss pane (`@boss_pane` set to its own pane id; the guard and pulse then treat it as a boss). Stamp only a pane that is a boss.
7. SKILL.md (restart paragraph, near `--wait-idle`): say that a background subagent a worker started keeps the pane `busy` after its last words and holds its idle notice back until the agent reports (measured 2.1.311, 2m24s for a 2m10s agent), so a refusal as busy right after a report can be a subagent still running, not a lost notice; a background shell or Monitor reads `shell`. The skill already tells the boss to use `--wait-idle` instead of waiting on a notice.

**Why:** found while building ticket 18. Items 1 to 4 are minor and nothing is typed in any of them; item 5 is the larger share of refusals the retry cannot clear; item 6 changed a worker pane's ownership on a real machine.

**Blocked by:** None (can start immediately)

**Claimed by:** Renzo 2026-11-04 23:30 (Osman before, who handed off)

**Status:** done (PR 52 merged as 063b2d8, 2026-11-04; CI on the PR head d60b853 green)

- [x] Items 1 to 4, each with a test that is red before and green after (PR 52, `test_boss_lifecycle.py`)
- [x] Item 5: reproduced on 2.1.311 in a throwaway tmux server; the signal is `turn_duration` as the last transcript record (fifth `--state` field). Met by the flag: by Anton's decision a finished turn is not a finished task, so `shell` stays refused by default and the restart goes through on it only with `--stop-shells`; a turn in flight with a shell stays refused even with the flag. Without typing, the pane shows only kinds and counts (footer `2 shells`), so the refusal says that and jobs are listed only under the flag
- [x] Item 6: a test that a worker pane running the script is not stamped, and a boss pane still is

**Accepted residuals** (round 2 Opus GO, `.scratch/boss-efficiency/reviews/pr-52-round2-opus.md`; not built):
- The `retire` usage line (`boss-lifecycle.sh` l.12) nests `--stop-shells` inside `--wait-idle`; the code does not need it.
- After `/exit`, the exit dialog is confirmed without checking `--stop-shells` (older than this PR): the default refusal relies on Claude Code reporting `shell` whenever background work runs, and no fixture pins that.
- Codex verdict on d60b853 owed (ticket 10's list).
