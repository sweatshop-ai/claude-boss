#!/usr/bin/env python3
"""Tests for ticket 22: a provisional GO is bound to its head, end to end from the real writer to the prune.

Run: python3 -m pytest skills/boss/test_boss_review_head_binding.py

The entry is written by the real fallback review (a `claude` stub that says GO), not by hand, then the PR is
moved through the cases of 22 (force-push back, close and reopen, merge on another head, a head that is gone)
and `prune_provisional` is asked each time. Every test goes through hermetic.Sandbox as test_boss_review_prune.py
does (its PruneBase is used here) and asserts the stub calls it expected: the prune makes `gh pr view` calls
and nothing else, and never calls `codex` or `claude`. The gate (04) and the recheck (10) are not built yet;
their halves of these cases are boxes in their own ticket files. Ticket 27 adds the sequences 22 left untested
(case A as it really runs, case B with two real provisional GOs, case C through reopening) and reads the round
files with 04's own `decide`.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_merge as bm  # noqa: E402
from test_boss_review_list import GO  # noqa: E402
from test_boss_review import PR  # noqa: E402
from test_boss_review_prune import B, PruneBase  # noqa: E402

C = "c" * 40


class ProvisionalGoIsBoundToItsHead(PruneBase):
    def entry_from_the_real_writer(self):
        self.claude(GO)
        result = self.fallback_review()
        self.claude_calls = len(self.sb.calls_of("claude"))
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
        self.assertEqual(len(self.sb.calls_of("claude")), self.claude_calls)      # the writer's call, none since
        return got

    def decides(self, head, base="main"):
        """What 04's gate says about the round files on disk, for a PR on `head` (the data 04 reads)."""
        rounds = bm.read_rounds(self.reviews / "owner" / "repo" / ("pr%d" % PR))
        return bm.decide(rounds, head, base, frozenset({"main"}), ("owner/repo", PR))

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

    def test_case_a_a_codex_go_on_another_head_above_the_entry_keeps_it_while_the_pr_sits_on_the_provisional_head(self):
        entry = self.entry_from_the_real_writer()
        self.pr_is("OPEN", self.head)
        self.rounds((2, B, "GO"))                      # Codex cleared another head, round above the entry's
        self.assertEqual(self.prune_and_count(), [])
        self.assertEqual(self.entries(), [entry])

    def test_case_a_as_it_runs_the_entry_goes_on_b_and_04_refuses_the_force_push_back_to_a(self):
        entry = self.entry_from_the_real_writer()      # round 1: provisional GO on A
        self.assertEqual(self.decides(self.head).reason, "provisional-go-non-deploying")
        self.rounds((2, B, "GO"))                      # round 2: Codex GO on B
        self.pr_is("OPEN", B)
        self.assertEqual(self.prune_and_count(), [entry.tag])     # rule 2 removes it while the PR sits on B
        self.assertEqual(self.entries(), [])
        got = self.decides(B)
        self.assertEqual((got.exit, got.reason, got.round), (0, "codex-go", 2))
        got = self.decides(self.head)                  # force-push back to A: round 1 must not decide again
        self.assertEqual((got.exit, got.reason, got.round), (3, "superseded-go", 1))

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

    def test_case_b_with_two_real_provisional_gos_the_entry_names_b_and_a_codex_go_on_the_merged_a_removes_it(self):
        self.entry_from_the_real_writer()              # round 1: provisional GO on A
        head_b = self.new_head()
        self.claude(GO)
        self.expect["claude"] = 2                      # one call per real review
        result = self.fallback_review()                # round 2: a second real provisional GO, on B
        self.claude_calls = len(self.sb.calls_of("claude"))
        self.assertEqual((result.round, result.status), (2, "posted"))
        (entry,) = self.entries()
        self.assertEqual((entry.head, entry.round), (head_b, 2))     # the entry now names B
        self.pr_is("MERGED", self.head)                # the PR went back to A and merged there
        self.assertEqual(self.prune_and_count(), [])   # no Codex round yet: the entry stays
        self.assertEqual(self.entries(), [entry])
        self.rounds((3, self.head, "GO"))              # Codex GO on the merged head
        self.assertEqual(self.prune_and_count(), [entry.tag])      # rule 4
        self.assertEqual(self.entries(), [])

    def test_case_c_goes_closed_open_merged_and_the_prune_keeps_the_entry_at_each_step(self):
        entry = self.entry_from_the_real_writer()
        for state in ("CLOSED", "OPEN", "MERGED"):
            with self.subTest(state=state):
                self.pr_is(state, self.head)
                self.assertEqual(self.prune_and_count(), [])
                self.assertEqual(self.entries(), [entry])
        self.rounds((2, self.head, "GO"))
        self.assertEqual(self.prune_and_count(), [entry.tag])     # only a Codex GO on the head removes it
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
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertEqual(len(self.sb.calls_of("claude")), self.claude_calls)
        self.assertEqual(self.entries(), [entry])
        self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh")[before:]], ["view"])


if __name__ == "__main__":
    unittest.main()
