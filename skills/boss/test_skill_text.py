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

    def test_no_line_tells_anyone_to_wait_for_the_reset(self):
        found = re.findall(r"\b(?:wait(?:s|ing)?|hold(?:s|ing)?|sleep(?:s|ing)?)\s+(?:for|until|till)\s+(?:the|its|a)?\s*"
                           r"(?:codex\s+)?(?:limit\s+)?reset", flat(), re.I)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
