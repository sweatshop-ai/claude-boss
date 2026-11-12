# 27: Head binding, edge cases found in review of 22 (class c and d)

**What to build:** the findings of Opus fallback review 1 on PR 105 (Codex was out of tokens) that were graded class c or d and filed instead of fixed.

**Blocked by:** 22 (A provisional GO on an older head must not merge or be rechecked as the current one)

**Status:** ready-for-agent

- [ ] **An abandoned PR's entry lives forever (class c).** Rule 3 keeps a CLOSED PR's entry, 10 neither reviews nor counts it, so entries of PRs closed for good pile up and every recheck pass makes one `gh pr view` each. Decide who clears one (the owner by hand through 09a's hand-clear, or an age limit) and say so in 06b and 10.
- [ ] **Case A's test is misnamed (class d).** `test_case_a_a_force_push_back_to_the_provisional_head_keeps_the_entry` (`test_boss_review_head_binding.py`) never puts the PR on B; in the real sequence rule 2 removes the entry while the PR sits on B, and 04's `superseded-go` closes the case. Rename it and add the sequence as one test of the data 04 reads (rounds 1 provisional on A, 2 Codex GO on B, the entry gone).
- [ ] **Case B has no real shape (class d).** Both `test_case_b_*` use a first provisional GO only. Build the real one: a second real provisional GO on B so the entry names B, the PR merged at A, a Codex GO on A removes it by rule 4 with no round above the entry's.
- [ ] **`prune_and_count` checks less than its docstring (class d).** Assert the `claude` log is unchanged after the writer's call, and `codex` in `test_an_entry_of_a_pr_that_cannot_be_read_is_kept`.
- [ ] **Case C skips the reopened state (class d).** Go CLOSED, OPEN, MERGED and prune at each step.
- [ ] **04's override list is shorter than its rule (class d).** The box names three overridden rows; add a test row for a later round on another base and for a later `post-failed` GO.
- [ ] **A Codex GO under a later provisional round (class d).** Codex GO on A in round 1, provisional GO on A in round 2, any round 3: the gate refuses `superseded-go` without reaching round 1. Say in 04 whether that is intended (it fails closed).
- [ ] **A recheck whose `gh pr view` fails (class c, Opus fallback review 2).** 10 branches merged, CLOSED and open and never says what it does when the state cannot be read. Say: skip, leave the entry (06b keeps it), go on to the next, and add the test row.
- [ ] **04's exit-3 line does not name `superseded-go` (class d).** 04's exit-code list says "none, a NO-GO, or a record that cannot be read"; add the superseded GO to it.
