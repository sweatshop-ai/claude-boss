# 18: A refused restart is retried on a timer, not waited on

**What to build:** diagnose, then change the boss's restart step. In one sampled gap the boss asked a worker to end its turn so it could restart it fresh with `--require-idle`, subscribed to the worker's idle notice, and waited. The worker's turn ended within seconds. No idle notice arrived for 92 minutes, the boss did nothing until an unrelated notice woke it, and the pane still read busy when it tried again. A ready job, the full suite in a fresh session, sat the whole time. In another gap the boss looped the same refusal and the restart went through in 16 seconds. Find out why the pane read busy and why the notice did not come, and make the restart step retry after the worker's last turn at a fixed interval (and say so on the tracker) instead of waiting on a notice that can be lost.

**Why:** ticket 07's sample: 1 gap of 50, 92 minutes, an estimated 4.5 h of the 214 h of short gaps (plus or minus 8.7), and the only gap where a ticket was ready and a worker was free. One case: the first box is to find out how often it happens.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Claimed by:** Otilia 2026-11-04 22:23

**Status:** in-progress

- [x] How often a restart was refused as busy and not retried within 10 minutes, counted over the boss transcripts of the last five weeks under the transcript lock, with the count of cases where no idle notice followed
- [ ] The cause of the busy reading and of the missing notice, shown from a reproduction or from the code
- [x] The restart step retries on a timer, with a test that a refused restart is retried once the worker's last turn has ended

## Result (Otilia, 2026-11-04; PR 50)

- Count, boss transcripts since 2026-09-30 (60 files, under the lock): 237 refusals as not idle in 14 sessions (193 busy, 41 shell, 3 waiting). 49 not retried within 10 minutes (a later restart/retire command naming the pane); 32 of those with no restart or retire command at all; 17 of the 32 with no idle-notice text within 90 minutes (text heuristic).
- Cause of the false "a turn started": with the exit dialog up the status is `waiting`, the check wanted `idle`. Reproduced in the stub harness and read live in an isolated tmux server. Separate finding: `shell` is read mid-turn too.
- Box 2 stays open: why the sampled gap's pane read busy and why no notice came is not shown. 41 of the 237 refusals read `shell`; the link to the missing notice is not shown.
- Retry: `--wait-idle <seconds>` (PR 50).
- Follow-ups: tell "turn over, background shell left" from "turn in flight" for `shell`; `self_register` stamps the calling pane as a boss on every invocation (a worker that runs the script becomes a boss pane).

PR 50 merged fa2062c; box 2 goes to the next worker: reproduce a worker that ends its turn with a background shell, with an idle subscription, and read whether the notice fires.
