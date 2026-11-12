#!/usr/bin/env python3
"""Tests for ticket 22: a provisional GO is bound to its head, end to end from the real writer to the prune.

Run: python3 -m pytest skills/boss/test_boss_review_head_binding.py

The entry is written by the real fallback review (a `claude` stub that says GO), not by hand, then the PR is
moved through the cases of 22 (force-push back, close and reopen, merge on another head, a head that is gone)
and `prune_provisional` is asked each time. Every test goes through hermetic.Sandbox as test_boss_review_prune.py
does (its PruneBase is used here) and asserts the stub calls it expected: the prune makes `gh pr view` calls
and nothing else, and never calls `codex` or `claude`. The gate (04) and the recheck (10) are not built yet;
their halves of these cases are boxes in their own ticket files.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_boss_review_list import GO  # noqa: E402
from test_boss_review_prune import B, PruneBase  # noqa: E402

C = "c" * 40


class ProvisionalGoIsBoundToItsHead(PruneBase):
    def entry_from_the_real_writer(self):
        self.claude(GO)
        result = self.fallback_review()
        self.assertEqual((result.round, result.status, result.kind), (1, "posted", "provisional"))
        (entry,) = self.entries()
        self.assertEqual((entry.head, entry.round), (self.head, 1))
        return entry

    def prune_and_count(self):
        before = len(self.sb.calls_of("gh"))
        got = self.prune()
        views = self.sb.calls_of("gh")[before:]
        self.assertEqual([c.argv[1] for c in views], ["view"])
        self.assertEqual(self.sb.calls_of("codex"), [])
        return got

    def test_case_c_a_closed_pr_reopened_on_its_head_and_merged_still_has_its_entry(self):
        entry = self.entry_from_the_real_writer()
        self.pr_is("CLOSED", self.head)
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])
        self.pr_is("MERGED", self.head)
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])          # what 10's release stop reads is still there
        self.assertEqual(self.text().count("[prov"), 1)

    def test_case_c_the_entry_goes_only_when_codex_says_go_above_its_round_on_the_head(self):
        entry = self.entry_from_the_real_writer()
        self.pr_is("MERGED", self.head)
        self.rounds((2, self.head, "NO-GO"))
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])
        self.rounds((3, self.head, "GO"))
        self.assertEqual(self.prune_and_count(), [entry.tag])
        self.assertEqual(self.entries(), [])

    def test_case_a_a_force_push_back_to_the_provisional_head_keeps_the_entry(self):
        entry = self.entry_from_the_real_writer()
        self.pr_is("OPEN", self.head)
        self.rounds((2, B, "GO"))                      # Codex cleared another head, round above the entry's
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])

    def test_case_a_the_entry_is_dropped_while_the_pr_sits_on_the_cleared_head_and_not_before(self):
        entry = self.entry_from_the_real_writer()
        self.rounds((2, B, "GO"))
        self.pr_is("OPEN", B)
        self.assertEqual(self.prune_and_count(), [entry.tag])
        self.assertEqual(self.entries(), [])

    def test_case_b_a_codex_go_on_a_later_head_does_not_remove_the_entry_of_a_pr_merged_on_the_old_head(self):
        entry = self.entry_from_the_real_writer()
        self.rounds((2, B, "GO"))
        self.pr_is("MERGED", self.head)
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])

    def test_case_b_the_pr_merged_on_a_head_that_codex_cleared_removes_the_entry(self):
        entry = self.entry_from_the_real_writer()
        self.rounds((2, B, "GO"))
        self.pr_is("MERGED", B)
        self.assertEqual(self.prune_and_count(), [entry.tag])
        self.assertEqual(self.entries(), [])

    def test_an_entry_whose_head_is_gone_from_the_pr_is_kept_until_codex_clears_a_head(self):
        entry = self.entry_from_the_real_writer()
        for state in ("OPEN", "MERGED"):
            with self.subTest(state=state):
                self.pr_is(state, C)                   # the entry's head is nowhere in the PR any more
                self.assertEqual(self.prune_and_count(), [])
                self.assertEqual(self.entries(), [entry])
        self.rounds((2, C, "NO-GO"))
        self.pr_is("OPEN", C)
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])
        self.rounds((3, C, "GO"))
        self.assertEqual(self.prune_and_count(), [entry.tag])
        self.assertEqual(self.entries(), [])

    def test_an_entry_of_a_pr_that_cannot_be_read_is_kept(self):
        entry = self.entry_from_the_real_writer()
        self.rounds((2, self.head, "GO"))
        self.gh.configure(view=[{"rc": 1}])
        before = len(self.sb.calls_of("gh"))
        self.assertEqual(self.prune(), [])
        self.assertEqual(self.entries(), [entry])
        self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh")[before:]], ["view"])


if __name__ == "__main__":
    unittest.main()
