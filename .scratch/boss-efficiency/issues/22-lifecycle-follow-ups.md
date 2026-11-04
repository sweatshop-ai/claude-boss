# 22: Lifecycle follow-ups from PR 50: wait-idle edges, `shell` status, self-stamping

**What to build:** four small fixes and one measurement in `boss-lifecycle.sh`, left open by ticket 18's review (PR 50, round 1).
1. `--wait-idle 08` is read as octal in the arithmetic: the loop is skipped and the restart dies "still busy" without waiting. Nothing is typed. Read the value as base 10.
2. `BOSS_RETRY_EVERY`: validate it (a number; a non-number stops the script on sleep's own error with no `ERROR:` line) and floor it at 1 s (0 busy-loops a python status read for up to the whole wait).
3. `--wait-idle` with `--expect-last` always ends in a refusal when a wait happened, because the busy turn writes new records; without a pin it restarts after whatever turn ran meanwhile, including a task a peer gave it that the boss never saw. Decide which the skill says, and say it in SKILL.md.
4. Tests for a non-numeric `--wait-idle` value and for `--wait-idle --force`.
5. `shell` (a background shell running) is read mid-turn and after the turn, so it is refused as not idle. Find a signal that tells "turn over, background shell left running" from "turn in flight" (the transcript's last record, the screen), so a worker that finished is restartable; 41 of 237 refusals in five weeks of boss transcripts read `shell`.
6. `self_register` (`boss-lifecycle.sh:171-172`) stamps the calling pane with itself on every invocation, so a worker that runs the script becomes a boss pane (`@boss_pane` set to its own pane id; the guard and pulse then treat it as a boss). Stamp only a pane that is a boss.

**Why:** found while building ticket 18. Items 1 to 4 are minor and nothing is typed in any of them; item 5 is the larger share of refusals the retry cannot clear; item 6 changed a worker pane's ownership on a real machine.

**Blocked by:** None (can start immediately)

**Status:** ready

- [ ] Items 1 to 4, each with a test that is red before and green after
- [ ] Item 5: a reproduction of a worker with a finished turn and a background shell, the signal chosen, and a restart that goes through on it; a turn in flight with a shell stays refused
- [ ] Item 6: a test that a worker pane running the script is not stamped, and a boss pane still is
