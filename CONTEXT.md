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

**Tracker**: `pm/<track>.md`, the boss's live state. Its formats — the Open
blockers section, the marker, the lock — live in `skills/boss/tracker.py`.

**Open blocker**: a bulleted line under the tracker's first `## Open blockers`
heading. Something is blocked on the owner.

**Marker**: the `[ladder id=… t0=… last=… next=… ask="…"]` token on an open
blocker. The ladder escalates that line from it, with no boss turn.

**Objective status**: the first `_Status: …_` line of `pm/<track>.goal.md`,
line 2 as `boss-goal` writes it. A track is open when it starts with OPEN.

**Reviewer chain**: the order in which a second model is asked for a `VERDICT:`
line: Codex first, then an optional fallback model through `claude`, otherwise
nobody answered. One module, `skills/boss/reviewer_chain.py`; `boss-run` calls it
and runs nothing unless it returns a whole answer. Its result says which
reviewer answered (`codex`, the fallback's name, or `none`) and keeps every
attempt.

**Attempt reason**: why one reviewer's turn ended as it did, from a closed set:
`answered` (a usable verdict), `absent` (not on PATH), `timeout`, `error`
(non-zero exit), `noverdict` (it answered with no usable `VERDICT:` line). A
usable verdict always wins, whatever the exit status.

**Fallback**: the spec of the model asked when Codex fails: a name, an exact
model id, a timeout, an optional tool restriction, and which Codex reasons let
it run. Optional; without one the chain is Codex only.

**Review round**: one run of `skills/boss/boss_review.py` on one PR head. The
review runs first (Codex only, in a child process standing in the checkout);
the round is claimed at the end of the run, under the PR's lock, whatever the
outcome, so numbers follow posting order and each comment's number is its
file's. Kept under `$CLAUDE_CONFIG_DIR/pm/reviews/<owner>/<repo>/pr<N>/`, never
in a checkout, private (0700 and 0600). Its status is `posted`, `head-moved`
(the head or the base moved during the review), `no-verdict` or `post-failed`.

**Round record**: `round<NN>.json`, what a gate reads. A round is `posted` only
after `gh pr comment` returned success, so a comment on the PR with no `posted`
record behind it authorizes nothing. A round claimed and never finished is an
empty file; the next round supersedes it and no round file is edited after its
final write. `round<NN>.out` beside it holds the reviewer's full answer.

**Repo key**: `<owner>/<repo>` lowercased by `repo_key`, the one spelling used
for a PR's directory, lock and records, because GitHub does not tell the cases
apart. It refuses anything but two plain names.
