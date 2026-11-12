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

    SENTENCE = ("On a usage limit or an outage, a plan's review is the labelled fallback review (Opus, "
                "read-only), run the same turn, with the reset time Codex gave in the review file's header; "
                "the review is never held for that time, and no wakeup or loop is scheduled for it.")

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

    def test_a_pr_heads_fallback_is_never_run_by_hand_and_the_command_runs_it_with_a_track(self):
        """Ticket 06a: `boss_review.py --track T` runs the fallback itself, so the by-hand sentence is gone."""
        text = flat()
        self.assertNotIn("does not run that fallback from its command line yet", text)
        self.assertNotIn("so you run the Opus review by hand beside it", text)
        self.assertNotIn("ticket 06 makes it automatic and removes this sentence", text)
        self.assertEqual(text.count(self.NO_HAND), 1)
        self.assertLess(text.index(self.SENTENCE), text.index(self.NO_HAND))
        self.assertLess(text.index(self.NO_HAND), text.index("How many rounds"))

    def test_the_command_shown_for_a_pr_head_carries_the_track(self):
        self.assertEqual(flat().count("--author NAME --track T`."), 1)

    NO_HAND = ("A PR head's fallback review is never run by hand: with `--track T` the command runs it itself "
               "when Codex does not answer, lists the provisional GO in `pm/T.md` before it posts, and prints "
               "\"Fallback review N\"; without a usable track the PR waits for Codex, or for the owner's choice, "
               "when Codex does not answer (exit 4 or 7).")

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
        self.assertIn("merges where nothing deploys, on a Codex GO or on a provisional fallback GO (the repo "
                      "marks the branch non-deploying)", flat())


class CodexDownChoice(unittest.TestCase):
    """Ticket 09b: the boss asks the owner once, records the answer, and does not ask twice."""

    def section(self):
        text = flat()
        start = text.index("**When a `Codex down` blocker is open, ask the owner once what to do**")
        return text[start:text.index("A plan is reviewed by hand", start)]

    def test_the_three_options_and_the_recommendation_first(self):
        sec = self.section()
        self.assertIn("recommendation first, three options: wait for Codex; accept the fallback review", sec)
        self.assertIn("or merge on tests alone (only where nothing deploys, only through `--waive`)", sec)

    def test_tests_alone_has_a_consent_of_its_own_asked_in_the_boss_own_turn(self):
        """Ticket 09c: the CONSENT: question, its exact button, the token, and `--waive` named once."""
        text = flat()
        self.assertEqual(text.count("**Merging on tests alone needs a consent of its own**"), 1)
        self.assertEqual(text.count("`CONSENT: merge PRs of <track> on tests alone while Codex is down (no review of any kind), "
                                    "only where nothing deploys? Command: <cmd>`"), 1)
        for part in ("not a choice", "ask once more in your own turn with `AskUserQuestion`, exactly one question",
                     "the first labelled exactly `Yes, merge on tests alone`", "a button, not free text",
                     "consent token", "any later `AskUserQuestion` withdraws it",
                     "codex_blocker.py --choose T tests-alone --test-cmd '<cmd>'", "On a no, record nothing",
                     "Both commands refuse without the token"):
            self.assertIn(part, text)
        self.assertEqual(text.count("boss_review.py --waive "), 1)
        import consent
        self.assertIn("`%s`" % consent.AFFIRMATIVE, text)

    def test_it_asks_through_the_concierge_and_in_its_own_turn_only_without_one(self):
        sec = self.section()
        self.assertIn("`SendMessage` with `ASK q<n>:`", sec)
        self.assertIn("`AskUserQuestion` in your own turn only when you have no concierge, never in prose", sec)

    def test_the_hand_clear_sentence_carries_its_example_and_never_a_bare_cleared(self):
        sec = self.section()
        self.assertIn("`cleared=<ISO-8601 time with UTC offset>` on its line (for example "
                      "`cleared=2026-11-12T10:30+01:00`), do not delete it", sec)
        self.assertNotRegex(sec, r"cleared=(?![<2])")

    def test_the_commands_and_the_line_format_are_named(self):
        sec = self.section()
        for part in ("codex_blocker.py --choice T", "codex_blocker.py --choose T wait", "--choose T accept-fallback",
                     "- [codex-choice <blocker id>] <choice> - <ts>", "under `## Decisions in force`"):
            self.assertIn(part, sec)

    def test_a_no_answer_writes_nothing_and_the_question_is_never_a_boss_unask_kind(self):
        sec = self.section()
        self.assertIn("A `NO ANSWER` writes nothing and the blocker stays open", sec)
        self.assertIn("never recorded as a `boss-unask` kind", sec)

    def test_it_appears_once_and_the_merge_rule_still_names_the_tests_alone_case(self):
        text = flat()
        self.assertEqual(text.count("ask the owner once what to do"), 1)
        self.assertEqual(text.count(MergeRule.RULE), 1)
        self.assertIn("the owner's merge on tests alone", MergeRule.RULE)


if __name__ == "__main__":
    unittest.main()
