# claude-boss — domain terms

**Boss**: a Claude session that coordinates workers and does no implementation
itself. It holds a marker under `pm/.boss-sessions/` and a track.

**Worker**: any session a boss dispatches to. One task per session.

**Track**: the name of a boss's tracker (`pm/<track>.md`) and objective
(`pm/<track>.goal.md`).

**Policy**: the steering numbers a boss and its workers act on — context
bands, cost lines, escalation rungs. One module, `skills/boss/policy.py`; the
prose quotes it and `test_policy.py` keeps the quotes true.

**Transcript**: a session's append-only JSONL log. Context, cost per turn and
the pin are read from its last 4 MB by one module, `skills/boss/transcript.py`.

**Pin**: the uuid of the last user, assistant or queued-command record in a
transcript. A worker that took input after the boss looked has a newer one.

**Flag**: what the policy says about one session right now, by role.
Worker: `CTX-SPLIT` (cut the task at its next boundary), `CTX-OVER` (overdue).
Boss: `CTX-EVAL`, `CTX-RESTART`. Either: `heavy`, `RECYCLE` (cost per turn).

**Handoff**: the file a worker writes before a restart — branch, what was tried
and rejected, live constraints, next step — ending with the boss-jev footer.

**Rung**: a point on the escalation ladder, in minutes since a blocker's T+0,
at which the blocker is raised to the owner again.
