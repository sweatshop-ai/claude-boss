# 22: A provisional GO on an older head must not merge or be rechecked as the current one

**What to build:** close the hole found in spec round 2 of 06 (`plan-review-codex-06-1.md`, finding 1). 06a keeps one list entry per PR, naming the newest provisional head; 04's gate lets the first valid posted round on the live head decide; 10 reviews a merged PR at the entry's `head=`. Three cases leave a provisional GO that no entry covers or covers with the wrong head:

- A: provisional GO on head A (round 1), push of head B, Codex GO on B (round 2, rule 2 removes the entry), force-push back to A: round 1 decides again and the PR merges on a non-deploying base with no entry.
- B: provisional GO on A, then on B (the entry now names B), the PR goes back to A and merges: 10 reviews the merged PR at B, not at the merged A (R17).
- C: a CLOSED PR lost its entry (06b's old rule 3, replaced in spec round 3: a CLOSED PR now keeps it), was reopened on the same head and merged on its old provisional round; no new provisional GO wrote an entry.

**Blocked by:** 06b (it changes 06b's rule 3 and brings 06a with it)

**Order:** 22 blocks 04 and 10: it is the gate's own correctness, so it lands before either is built. It writes the two rules that 04 and 10 must implement as boxes in their ticket files (the first two boxes below); 04 and 10 build the code and the tests for cases A and B.

**Status:** done (Piotr built it, PR 105, merge c1a2c6c)

- [x] Add to ticket 04 a box, with a test for case A: in 04's gate, a provisional or waived GO decides only when it is the PR's highest-numbered round file of any status (`posted`, `post-failed`, `head-moved`, `no-verdict`, `list-failed`); any later round, whatever its head or status, means the GO no longer decides and the PR needs a new round. This covers a later `post-failed` provisional GO that replaced the entry (06a replaces the entry before posting and keeps it when posting fails). Test: provisional GO on A posted, provisional GO on B `post-failed`, force-push back to A: the gate refuses.
- [x] Add to ticket 10 a box, with a test for case B: in 10's recheck, a merged PR is reviewed at its merged `headRefOid`, not at the entry's `head=`. A Codex GO on the merged head removes the entry by 06b's rule 4 (done in 22 below); a NO-GO writes 10's post-merge blocker and then removes the entry as 10 already says; a failed or stalled review leaves the entry and the release stop holds. The box also says: 10's recheck does not review a PR that is `CLOSED` without a merge, and 10's release stop (`--list`) does not count its entry while it is closed; a closed PR whose state cannot be read counts.
- [x] 06b's rule 3 is replaced (done in 06b, 2026-11-12, spec round 3 finding 1): a CLOSED unmerged PR keeps its entry, so case C cannot merge on a bare old round; rule 4 is added for case B. The tests of both are in 06b's box (this ticket checks they exist).
- [x] Case C is tested end to end: provisional GO on head A with an entry, the PR closed, `prune_provisional` keeps the entry, the PR reopened on A and merged: the entry is still there and 10's release stop holds.

Done in the PR: the two boxes are in 04 and 10 (`superseded-go` is 04's reason for a GO that a later round supersedes); 06b's rows for rules 3 and 4 and its case-C test exist in `test_boss_review_prune.py` (`RemovalRows`, `test_a_closed_pr_keeps_its_entry_and_the_reopened_one_is_removed_by_rule_one`); `test_boss_review_head_binding.py` runs cases A, B and C from the real writer through `prune_provisional`. The gate half of case A and the recheck half of case B are built in 04 and 10, whose tests the new boxes name. 10's release stop (`--list`) does not exist yet, so the end-to-end test holds the entry itself, which is what `--list` reads.
