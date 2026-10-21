# 01: Cross-repository sub-issues are read and claimed in the parent's repo

**What to build:** `frontier.py` treats every sub-issue of `gh:owner/repo#N` as living in
`owner/repo`. GitHub allows a sub-issue from another repository. For such a ticket the
dependency read (`issues/<n>/dependencies/blocked_by`) and the claim label go to the
same-numbered issue in the parent's repository: the wrong graph, and a `worker:<name>`
label on an unrelated issue. Carry each sub-issue's own repository (its
`repository_url`) and number through `gh_ticket`, `load_github` and `claim_github`, or
reject a cross-repository sub-issue as broken input (exit 2) before anything is
dispatched.

Found by Codex review 3 of PR 20 (head 7f082c9), [P1], `skills/hand-to-boss/frontier.py:196-198`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A test with a sub-issue whose `repository_url` is another repo: its blockers are
      read from that repo, or the graph is refused with a message naming it
- [ ] `claim` never labels an issue in a repository other than the sub-issue's own
