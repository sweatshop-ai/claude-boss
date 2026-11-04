# 18: A refused restart is retried on a timer, not waited on

**What to build:** diagnose, then change the boss's restart step. In one sampled gap the boss asked a worker to end its turn so it could restart it fresh with `--require-idle`, subscribed to the worker's idle notice, and waited. The worker's turn ended within seconds. No idle notice arrived for 92 minutes, the boss did nothing until an unrelated notice woke it, and the pane still read busy when it tried again. A ready job, the full suite in a fresh session, sat the whole time. In another gap the boss looped the same refusal and the restart went through in 16 seconds. Find out why the pane read busy and why the notice did not come, and make the restart step retry after the worker's last turn at a fixed interval (and say so on the tracker) instead of waiting on a notice that can be lost.

**Why:** ticket 07's sample: 1 gap of 50, 92 minutes, an estimated 4.5 h of the 214 h of short gaps (plus or minus 8.7), and the only gap where a ticket was ready and a worker was free. One case: the first box is to find out how often it happens.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] How often a restart was refused as busy and not retried within 10 minutes, counted over the boss transcripts of the last five weeks under the transcript lock, with the count of cases where no idle notice followed
- [ ] The cause of the busy reading and of the missing notice, shown from a reproduction or from the code
- [ ] The restart step retries on a timer, with a test that a refused restart is retried once the worker's last turn has ended
