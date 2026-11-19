#!/usr/bin/env python3
"""Tests for the Codex usage-limit skip of `boss_review.py` (ticket 49).

Run: python3 -m pytest skills/boss/test_boss_review_limit.py

A Codex attempt that fails on its usage limit writes the reset time to `pm/reviews/codex-limit.json`; every review
that starts before that time, with a fallback allowed, runs the fallback straight away (Codex not started, nothing
in attempts.jsonl) and says so. Reviews go through hermetic.Sandbox as test_boss_review_provisional.py does, and the
clock (`boss_review._aware_now`) and the zone (TZ) are fixed per test.
"""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import codex_health  # noqa: E402
from test_boss_review import AUTHOR  # noqa: E402
from test_boss_review_provisional import MODEL, Base  # noqa: E402

UTC = timezone.utc
LIMIT_TEXT = ("ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
              "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at %s.\n")
DATED = LIMIT_TEXT % "Nov 20th, 2026 2:10 PM"          # 14:10 where the machine runs, +01:00 below: 13:10 UTC
UNTIL = datetime(2026, 11, 20, 13, 10, tzinfo=UTC)
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
GO = "FINDING: none\nVERDICT: GO\nREASON: fine\n"


class Zone(unittest.TestCase):
    """The machine runs in a zone one hour ahead of UTC, so that a local time read as UTC is a visible mistake."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"TZ": "Etc/GMT-1"})
        patcher.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(patcher.stop)


class ResetTime(Zone):
    def test_a_dated_message_is_read_as_local_time_and_kept_with_its_offset(self):
        got = br.limit_reset("noise\n" + DATED, NOW)
        self.assertEqual(got, (UNTIL, True))
        self.assertIsNotNone(got[0].tzinfo)

    def test_a_time_alone_is_the_next_time_it_is_that_hour_on_the_local_clock(self):
        text = LIMIT_TEXT % "7:10 PM"                       # 19:10 local = 18:10 UTC
        self.assertEqual(br.limit_reset(text, datetime(2026, 11, 19, 12, 0, tzinfo=UTC)),
                         (datetime(2026, 11, 19, 18, 10, tzinfo=UTC), True))
        self.assertEqual(br.limit_reset(text, datetime(2026, 11, 19, 18, 11, tzinfo=UTC)),
                         (datetime(2026, 11, 20, 18, 10, tzinfo=UTC), True))

    def test_a_limit_message_without_a_time_skips_for_one_hour(self):
        text = "ERROR: You've hit your usage limit. Upgrade to Pro.\n"
        self.assertEqual(br.limit_reset(text, NOW), (NOW + timedelta(hours=1), False))

    def test_a_time_that_cannot_be_right_is_no_time(self):
        far = LIMIT_TEXT % "Dec 30th, 2026 2:10 PM"
        self.assertEqual(br.limit_reset(far, NOW), (NOW + timedelta(hours=1), False))
        bad = LIMIT_TEXT % "Nov 31st, 2026 2:10 PM"
        self.assertEqual(br.limit_reset(bad, NOW), (NOW + timedelta(hours=1), False))

    def test_only_the_usage_limit_error_counts(self):
        for text in ("codex: not signed in\n", "ERROR: 401 Unauthorized\n", "ERROR: connection reset by peer\n",
                     "ERROR: timeout waiting for child process to exit\n", "",
                     # the brief echoed on stderr can quote the message: it is not an error line
                     "+ ERROR: You've hit your usage limit. try again at Nov 20th, 2026 2:10 PM.\n",
                     "the usage limit text: ERROR: You've hit your usage limit.\n"):
            self.assertIsNone(br.limit_reset(text, NOW), text)


class State(Zone):
    def setUp(self):
        super().setUp()
        import tempfile
        self.dir = Path(tempfile.mkdtemp(prefix="limit-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.path = self.dir / "codex-limit.json"

    def test_it_is_written_with_an_explicit_offset_and_private(self):
        br.write_limit(self.dir, UNTIL, True, NOW)
        record = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(record["until"], "2026-11-20T13:10:00+00:00")
        self.assertEqual(record["parsed"], True)
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")

    def test_active_before_the_reset_time_and_gone_at_it(self):
        br.write_limit(self.dir, UNTIL, True, NOW)
        self.assertEqual(br.read_limit(self.dir, UNTIL - timedelta(seconds=1)), (UNTIL, True))
        self.assertIsNone(br.read_limit(self.dir, UNTIL))
        self.assertFalse(self.path.exists(), "a file past its reset time is cleaned")

    def test_the_comparison_is_between_aware_times(self):
        # 14:10 at +05:00 is 09:10 UTC: at 10:00 UTC the limit is over, though 14:10 > 10:00 on the clock face
        self.path.write_text(json.dumps({"until": "2026-11-20T14:10:00+05:00", "parsed": True}), encoding="utf-8")
        self.assertIsNone(br.read_limit(self.dir, datetime(2026, 11, 20, 10, 0, tzinfo=UTC)))
        self.path.write_text(json.dumps({"until": "2026-11-20T14:10:00+05:00", "parsed": True}), encoding="utf-8")
        self.assertEqual(br.read_limit(self.dir, datetime(2026, 11, 20, 9, 0, tzinfo=UTC)),
                         (datetime(2026, 11, 20, 14, 10, tzinfo=timezone(timedelta(hours=5))), True))

    def test_a_time_with_no_offset_or_no_sense_is_ignored_and_cleaned(self):
        for text in ('{"until": "2026-11-20T14:10:00", "parsed": true}', '{"until": 5}', "[]", "not json",
                     '{"until": "2026-11-20T14:10:00+00:00"}',
                     '{"until": "2027-06-01T00:00:00+00:00", "parsed": true}'):      # months away: no limit lasts so long
            self.path.write_text(text, encoding="utf-8")
            self.assertIsNone(br.read_limit(self.dir, NOW), text)
            self.assertFalse(self.path.exists(), text)

    def test_no_file_is_no_limit(self):
        self.assertIsNone(br.read_limit(self.dir, NOW))


class Skip(Zone, Base):
    def setUp(self):
        super().setUp()
        self.clock = NOW
        patcher = mock.patch.object(br, "_aware_now", side_effect=lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.limit_path = self.reviews / "codex-limit.json"

    def limited_codex(self, text=DATED, rc=1):
        self.codex(rc=rc, err=text.rstrip("\n"))

    def state(self):
        return json.loads(self.limit_path.read_text(encoding="utf-8"))

    def test_a_usage_limit_failure_writes_the_reset_time_and_the_fallback_answers(self):
        self.limited_codex()
        self.claude(GO)
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.kind), (0, "provisional"))
        self.assertEqual(self.state()["until"], "2026-11-20T13:10:00+00:00")
        self.assertEqual(self.state()["parsed"], True)
        self.assertEqual([(a["reviewer"], a["reason"]) for a in self.record(1)["attempts"]],
                         [("codex", "error"), ("opus", "answered")])
        self.assertNotIn("codex_skipped", self.record(1))

    def test_a_review_before_the_reset_time_does_not_start_codex(self):
        self.limited_codex()
        self.claude(GO)
        self.fallback_review()
        self.clock = NOW + timedelta(hours=1)
        self.expect["claude"] = 2
        self.claude(GO)
        self.expect["claude"] = 2
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.round, result.kind), (0, 2, "provisional"))
        self.assertEqual(len(self.sb.calls_of("codex")), 1, "Codex was asked in round 1 only")
        self.expect["codex"] = 1
        self.assertEqual(len(self.sb.calls_of("claude")), 2)

    def test_the_round_record_and_the_comment_say_codex_was_skipped(self):
        self.limited_codex()
        self.claude(GO)
        self.fallback_review()
        self.expect["claude"] = 2
        self.fallback_review()
        self.expect["codex"] = 1
        record = self.record(2)
        self.assertEqual(record["codex_skipped"], {"reason": "usage limit", "until": "2026-11-20T13:10:00+00:00",
                                                   "parsed": True})
        self.assertEqual([(a["reviewer"], a["reason"], a["model"]) for a in record["attempts"]],
                         [("opus", "answered", MODEL)])
        head = self.comments()[1].argv[-1].split("\n")[0]
        self.assertEqual(head, "Fallback review 2 (%s, Codex skipped: usage limit until 2026-11-20T13:10:00Z; "
                               "run by %s)" % (MODEL, AUTHOR))
        self.assertIn("Verdict: provisional GO", self.comments()[1].argv[-1])

    def test_a_skipped_round_is_no_codex_failure(self):
        self.limited_codex()
        self.claude(GO)
        self.fallback_review()
        before = codex_health.health(self.reviews / "attempts.jsonl")
        self.expect["claude"] = 2
        self.fallback_review()
        self.expect["codex"] = 1
        self.assertEqual(codex_health.health(self.reviews / "attempts.jsonl"), before)
        self.assertEqual([line["round"] for line in self.attempts_log()], [1, 1])      # round 1's two attempts only

    def test_a_skipped_go_is_still_a_loan_listed_for_the_codex_recheck(self):
        self.limited_codex()
        self.claude(GO)
        self.fallback_review()
        self.expect["claude"] = 2
        self.fallback_review()
        self.expect["codex"] = 1
        self.assertEqual(self.tracker.read_text(encoding="utf-8").count("[prov "), 1)      # one PR, one line

    def test_after_the_reset_time_codex_is_asked_again_and_the_file_is_gone(self):
        self.limited_codex()
        self.claude(GO)
        self.fallback_review()
        self.clock = UNTIL + timedelta(minutes=1)
        self.codex(answer="VERDICT: GO")
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.kind), (0, "codex"))
        self.assertEqual(len(self.sb.calls_of("codex")), 2, "Codex was asked in round 1 and again in round 2")
        self.expect["codex"] = 2
        self.assertFalse(self.limit_path.exists())

    def test_an_unparseable_limit_message_skips_for_one_hour_and_says_so(self):
        self.limited_codex("ERROR: You've hit your usage limit. Upgrade to Pro.\n")
        self.claude(GO)
        self.fallback_review()
        self.assertEqual(self.state(), dict(self.state(), until="2026-11-19T13:00:00+00:00", parsed=False))
        self.clock = NOW + timedelta(minutes=30)
        self.expect["claude"] = 2
        self.fallback_review()
        self.expect["codex"] = 1
        self.assertEqual(self.record(2)["codex_skipped"]["parsed"], False)
        head = self.comments()[1].argv[-1].split("\n")[0]
        self.assertIn("Codex skipped: usage limit until 2026-11-19T13:00:00Z (no reset time in the message: "
                      "skipped for one hour)", head)
        self.clock = NOW + timedelta(minutes=61)
        self.codex(answer="VERDICT: GO")
        self.expect["codex"] = 2
        self.assertEqual(self.fallback_review().kind, "codex")

    def test_only_a_usage_limit_error_starts_the_skip(self):
        for err, rc in (("codex: not signed in", 3), ("ERROR: 401 Unauthorized", 1), ("ERROR: connection reset", 1),
                        ("+ ERROR: You've hit your usage limit, try again at Nov 20th, 2026 2:10 PM.", 1)):
            with self.subTest(err=err):
                self.setUp_clean()
                self.limited_codex(err, rc=rc)
                self.claude(GO)
                self.fallback_review()
                self.assertFalse(self.limit_path.exists())
                self.expect = {"claude": 1, "codex": 1}
                self.sb.guard()

    def test_a_codex_timeout_starts_no_skip(self):
        self.codex(hang=True)
        self.claude(GO)
        self.fallback_review(codex_timeout=1)
        self.assertFalse(self.limit_path.exists())

    def test_without_a_fallback_codex_is_asked_whatever_the_file_says(self):
        br.write_limit(self.reviews, UNTIL, True, NOW)
        self.codex(answer="VERDICT: GO")
        result = self.review()
        self.assertEqual((result.exit_code, result.kind), (0, "codex"))
        self.assertEqual(len(self.sb.calls_of("codex")), 1)
        self.assertTrue(self.limit_path.exists())

    def test_a_file_past_its_reset_time_is_ignored_and_cleaned_by_the_next_review(self):
        br.write_limit(self.reviews, NOW - timedelta(minutes=1), True, NOW - timedelta(hours=5))
        self.codex(answer="VERDICT: GO")
        result = self.fallback_review()
        self.assertEqual(result.kind, "codex")
        self.assertFalse(self.limit_path.exists())


if __name__ == "__main__":
    unittest.main()
