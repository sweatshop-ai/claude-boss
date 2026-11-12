#!/usr/bin/env python3
"""Sentences SKILL.md must carry, and wordings it must not.

Run: python3 skills/boss/test_skill_text.py
"""
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE / "SKILL.md"


def flat() -> str:
    return " ".join(SKILL.read_text().split())


class CodexUsageLimit(unittest.TestCase):
    """Ticket 12: a usage limit or an outage means the fallback review now, not a wait."""

    SENTENCE = ("On a usage limit or an outage, the same turn runs the labelled fallback review (Opus, "
                "read-only), with the reset time Codex gave in the review file's header; the review is "
                "never held for that time, and no wakeup or loop is scheduled for it.")

    def test_the_fallback_sentence_appears_exactly_once(self):
        self.assertEqual(flat().count(self.SENTENCE), 1)

    def test_it_sits_in_the_codex_routine(self):
        text = flat()
        start = text.index("Codex is the external reviewer, twice")
        self.assertLess(start, text.index(self.SENTENCE))
        self.assertLess(text.index(self.SENTENCE), text.index("How many rounds"))

    def test_the_fallback_is_posted_under_its_own_heading(self):
        text = flat()
        self.assertEqual(text.count('"Fallback review N (<model id>, Codex unavailable: <reason>; run by <name>)"'), 1)
        self.assertEqual(text.count('"Codex review N (run by <name>)" for a Codex answer'), 1)

    def test_no_line_tells_anyone_to_wait_for_the_reset(self):
        found = re.findall(r"\b(?:wait(?:s|ing)?|hold(?:s|ing)?|sleep(?:s|ing)?)\s+(?:for|until|till)\s+(?:the|its|a)?\s*"
                           r"(?:codex\s+)?(?:limit\s+)?reset", flat(), re.I)
        self.assertEqual(found, [])


class MergeRule(unittest.TestCase):
    """Ticket 08: one rule for every kind of GO, in place of the two absolute sentences."""

    RULE = ("The merge rule: a Codex GO on the head that merges may merge; a GO that is not Codex's (a "
            "provisional fallback review, or the owner's merge on tests alone) may merge only on a branch "
            "the repo marks non-deploying, which `boss_merge.py` decides; anything else does not merge.")

    def test_the_old_absolute_sentences_are_gone(self):
        text = flat()
        self.assertNotIn("No PR merges without a GO on record", text)
        self.assertNotIn("every PR gets a Codex review on the head that merges", text)

    def test_the_new_rule_appears_exactly_once(self):
        self.assertEqual(flat().count(self.RULE), 1)

    def test_the_plan_half_and_the_message_only_line_stay(self):
        text = flat()
        self.assertEqual(text.count("No plan is dispatched from without a Codex GO."), 1)
        self.assertIn("no merge order is given on a GO that exists only in a message", text)

    def test_the_sentence_on_production_merges_follows_the_rule(self):
        self.assertIn("merges on a Codex GO, or on a provisional fallback GO where the repo marks the branch "
                      "non-deploying", flat())


if __name__ == "__main__":
    unittest.main()
