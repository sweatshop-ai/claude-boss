# claude-boss — domain terms

**Boss**: a Claude session that coordinates workers and does no implementation
itself. It holds a marker under `pm/.boss-sessions/` and a track.

**Worker**: any session a boss dispatches to. One task per session.

**Agent-teams teammate**: a session that a Claude Code agent-teams lead
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) spawned inside its own process. Not a
worker: it has no pane and no stamp, dies with its lead, and the boss neither
dispatches to it nor sees it. A worker may lead them; a boss never does.
_Avoid_: teammate (alone), sub-worker

**Burst**: one worker running parallel helpers for the length of one ticket —
background subagents by default, agent-teams teammates when the parts must talk.
Its cost lands in that worker's context.
_Avoid_: team (means `/team`, the peer mesh between workers)

**Ticket graph**: the tickets of a track and their Blocked-by edges — a folder
of ticket files, or the sub-issues of one GitHub issue with GitHub's own
dependencies. Named in the objective's `## Tickets`.
_Avoid_: backlog, task list (no edges)

**Frontier**: the tickets of a ticket graph that can be dispatched now: not
done, not claimed, every blocker done, nothing external open.
_Avoid_: ready list, queue

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

**Stamp**: the `@boss_pane` option on a tmux pane, naming the pane of the boss
that owns it. Only the stamp makes a pane a boss's; `fleet.py` reads and writes it.

**Seat**: one tmux pane and the live session running in it, if any (`fleet.py`).
A pane with no session is an empty seat; a crashed worker leaves one.

**Shared pane**: a pane that more than one live session names in its registry
record. The oldest is the pane's own session; the flag `shared-pane` and the line
under the row in `list` name the others.

**Handoff**: the file a worker writes before a restart — branch, what was tried
and rejected, live constraints, next step.

**Rung**: a point on the escalation ladder, in minutes since a blocker's T+0,
at which the blocker is raised to the owner again.

**Tracker**: `pm/<track>.md`, the boss's live state. Its formats — the Open
blockers section, the marker, the lock — live in `skills/boss/tracker.py`.

**Open blocker**: a bulleted line under the tracker's first `## Open blockers`
heading. Something is blocked on the owner.

**Marker**: the `[ladder id=… t0=… last=… next=… ask="…"]` token on an open
blocker. The ladder escalates that line from it, with no boss turn.

**Pulse decision**: what the pulse tells a boss at a Stop, as data before it
is worded: the ordered actions (`ask`, `fix-graph`, `dispatch-ready`,
`spawn n`, `dispatch-next`, `refill-next`, `run-rung n`), the due rungs it
names (`overdue`, three at most) and the fired marks (`fired`: each rung
already said) saved once the text is out; or nothing, and the boss is left
alone. `skills/boss/pulse.py` decides and words it; `boss-pulse.py`
gathers the facts and owns the gate and the state file.

**Objective status**: the first `_Status: …_` line of `pm/<track>.goal.md`,
wherever it sits; `boss-goal status` rewrites that same line. A track is open
when it starts with OPEN. The objective's format — status, sections, ticket
source — lives in `skills/boss/objective.py`; `boss-goal` reads and writes it
through that module's command line.

**Reviewer chain**: the order in which a second model is asked for an answer:
Codex first, then an optional fallback model through `claude`, otherwise
nobody answered. One module, `skills/boss/reviewer_chain.py`, three callers:
`boss-run` (a `VERDICT:` of APPROVE/REJECT, fallback `opus`), `boss-goal review`
(COMPLETE/INCOMPLETE, fallback `opus`) and `boss-goal premortem` (eight or more
`RISK:` lines, fallback `fable`). `boss-run` runs nothing unless it returns a
whole answer. Its result says which reviewer answered (`codex`, the fallback's
name, or `none`) and keeps every attempt.

**Acceptance rule**: what the chain counts as a usable answer. Either a
`VERDICT:` line carrying one of the caller's words, or at least N lines under
one label (`RISK:`), returned with the label stripped. A fallback runs only when
Codex's answer fails the rule.

**Attempt reason**: why one reviewer's turn ended as it did, from a closed set:
`answered` (a usable verdict), `absent` (not on PATH), `timeout`, `error`
(non-zero exit), `noverdict` (it answered with no usable `VERDICT:` line). A
usable verdict always wins, whatever the exit status.

**Fallback**: the spec of the model asked when Codex fails: a name, an exact
model id, a timeout (twice Codex's unless set), an optional tool restriction,
and which Codex reasons let it run. Optional; without one the chain is Codex
only. Callers name one by **preset** (`opus` = `claude-opus-5-5`, `fable` =
`claude-fable-5-1`), so the model ids are written in `reviewer_chain.py` alone.
