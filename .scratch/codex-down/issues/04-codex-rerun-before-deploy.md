# 04: Codex re-run before deploy

**What to build:** a provisional GO never satisfies the gate on a branch that deploys. The boss keeps a list of PRs that hold only a provisional GO. When Codex answers again, each one gets a Codex review on its current head; a NO-GO on a PR that already merged becomes a follow-up task for its author. A merge order to a deploying branch is refused while the PR's last GO is provisional.

**Blocked by:** 03 (Labelled fallback review)

**Status:** ready-for-agent

- [ ] PRs with only a provisional GO are listed in the boss's tracker
- [ ] The first successful Codex answer triggers a re-review of every listed PR on its current head
- [ ] A Codex NO-GO on an already merged PR produces a dispatched fix, not a silent note
- [ ] The boss never gives a merge order to a deploying branch on a provisional GO; how a repo marks a branch as deploying is configurable, not tied to one machine
- [ ] Tests: provisional PR re-reviewed on recovery; merge to a deploying branch refused on provisional GO
