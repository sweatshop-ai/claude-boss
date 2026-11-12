# 22: A provisional GO on an older head must not merge or be rechecked as the current one

**What to build:** close the hole found in spec round 2 of 06 (`plan-review-codex-06-1.md`, finding 1). 06a keeps one list entry per PR, naming the newest provisional head; 04's gate lets the first valid posted round on the live head decide; 10 reviews a merged PR at the entry's `head=`. Three cases leave a provisional GO that no entry covers or covers with the wrong head:

- A: provisional GO on head A (round 1), push of head B, Codex GO on B (round 2, rule 2 removes the entry), force-push back to A: round 1 decides again and the PR merges on a non-deploying base with no entry.
- B: provisional GO on A, then on B (the entry now names B), the PR goes back to A and merges: 10 reviews the merged PR at B, not at the merged A (R17).
- C: a CLOSED PR loses its entry (06b rule 3), is reopened on the same head and merges on its old provisional round; no new provisional GO writes an entry.

**Blocked by:** 06a, 06b, 04, 10 (it edits their text and code)

**Status:** ready-for-agent

- [ ] In 04's gate, a provisional or waived GO decides only when it is the PR's highest-numbered posted round; an older one on the same head, followed by any later posted round, does not.
- [ ] In 10's recheck, a merged PR is reviewed at its merged `headRefOid`, not at the entry's `head=`; an entry whose head differs from it is reviewed at both, or says why not.
- [ ] 06b's rule 3 (a CLOSED unmerged PR loses its entry) is kept, or replaced by "kept, and skipped by 10's release stop while CLOSED"; whichever is chosen, case C has a test.
- [ ] A test per case A, B and C.
