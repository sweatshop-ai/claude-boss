# 29: A worker's report to the boss's name fails, and ends as plain output

**What to build:** a worker finished at 00:33 and its report sat in its own pane for 32 minutes. Its one SendMessage, to the boss's name as shown in an incoming message, failed with "No agent named ... is reachable"; `ListAgents` in the boss's session names that same address as its own, and workers replying to the `from` socket address arrive. The worker ended the turn with the report as plain output. The boss read its `shell` state as still working, because a leftover wait loop kept it there.

Find out why the name did not resolve for that worker, and make a failed report loud: the dispatch text says to retry on the `from` address and never to end on plain output. Say what the boss looks at when a worker is quiet: the pane's last turn line, not only the status. Also here: one more leftover `pgrep` wait loop, the second tonight.

**Blocked by:** None (can start immediately)

**Claimed by:** Habib 2026-11-05 01:07

**Status:** in-progress

- [ ] The cause of the failed send, shown from a reproduction or the code, or written down as not found
- [ ] The dispatch text carries the retry rule
- [ ] The skill says how a boss tells a quiet worker from a finished one
