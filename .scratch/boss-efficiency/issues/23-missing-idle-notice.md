# 23: A restart read busy after a finished turn, and an idle notice never came: cause not shown

**What to build:** nothing yet. Ticket 18 read one case and could not reproduce it: a status read `busy` 5 s after a worker's finished turn, and two `notify_when_idle` subscriptions made seconds before a worker's turn end gave the boss no notice for 92 minutes. Two probes on Claude Code 2.1.311 (17 subscriptions, 17 notices) did not show it. Evidence and what the probes did not copy are in ticket 18. A boss no longer depends on the notice: `restart --require-idle --wait-idle` reads the status itself.

When it recurs, keep before anything is restarted: the worker's `~/.claude/sessions/<pid>.json`, the last records of its transcript, the time of each subscription, and the Claude Code version. Then find the cause, or file it with Anthropic if the fault is in Claude Code.

**Blocked by:**
- External: a boss or worker sees it again; nobody to ask

**Status:** waits on a recurrence

- [ ] The cause of the busy reading and of the missing notice, shown from a reproduction or from the code
