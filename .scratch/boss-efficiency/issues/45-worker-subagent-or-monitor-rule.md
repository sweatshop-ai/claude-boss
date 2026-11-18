# 45: the boss chooses between a worker, a subagent and a Monitor by rule

**What to build:** a section in `skills/boss/SKILL.md`, under the Cardinal Rule, that states which carrier a job gets, and a change in `skills/boss/boss-guard.py` so the guard stops calling a read-only subagent "implementation work".

- **Subagent** (no pane, the answer comes back to the boss): read-only, under about an hour, one answer. An inventory, a render check, a dependency graph from the trackers. Only `subagent_type` `Explore` or `Plan` (their tool sets have no Edit, Write or NotebookEdit), always `run_in_background: true`, never with a `name` (that is a teammate, still refused).
- **Monitor or background shell:** waiting on an external state (CI green, a cron firing). Already outside the guard's WATCHED set; the skill says so.
- **Worker (its own pane):** it writes to a repo or a box, holds state for hours (a stage, a PR taken to merge), or needs the owner's word in its pane.
- **Not a boss subagent:** a review. The one-round rule (2026-11-15) stands: the worker's `code-review` plus `/codex-review` is the round, the boss runs none of its own.

Guard: an `Agent` call whose `subagent_type` is `Explore` or `Plan` and that carries no `name` is coordination (no warning, still logged with `kind: read-only-subagent`). `general-purpose` or any type with write tools keeps the warning: the guard cannot tell from the prompt whether it will write.

**Measured 2026-11-18 (Rocco, track plans-live, tt-tiroir):** 17 worker panes, six past 150k tokens and one at 266k, several of them doing one-answer read-only jobs (watching main CI until green, checking a sheaf page renders, building a dependency graph from the trackers). The skill named no carrier for those jobs, so each got a pane.

**Blocked by:** None (can start immediately)

**Claimed by:** Rafael (2026-11-18)

**Status:** open

- [ ] Test first: `test_boss_guard` gets an Explore call with no name (no message, logged as read-only-subagent), a general-purpose call (warned as now), an Explore call with a name (teammate message as now)
- [ ] SKILL.md section written, Cardinal Rule's allowed list names read-only subagents and Monitor
