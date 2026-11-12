#!/usr/bin/env python3
"""Tests for `review(..., track=)` and `--track` (ticket 05c): when the Codex health is synced into the
track's tracker, and that three failed reviews in a row raise the "Codex down" blocker end to end.

Run: python3 -m pytest skills/boss/test_boss_review_track.py

Every test goes through hermetic.Sandbox as test_boss_review.py does. BOSS_ALERT is the sandbox's stub (a
test fails if it is unset), BOSS_LADDER_PM and BOSS_LADDER_STATE point into the temp dir, and the tracker is
a file in the temp config dir: no test posts a real alert or writes a real tracker.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import codex_blocker  # noqa: E402
import codex_health  # noqa: E402
from test_boss_review import AUTHOR, OTHER_SHA, PR, REPO, Base as ReviewBase  # noqa: E402

TRACKER = "# t\n\n## Open blockers\n"


class Base(ReviewBase):
    def setUp(self):
        super().setUp()
        self.alert = self.sb.stub("boss-alert")
        pm = self.sb.cfg / "pm"
        for key, value in (("BOSS_ALERT", str(self.alert)), ("BOSS_LADDER_PM", str(pm)),
                           ("BOSS_LADDER_STATE", str(self.sb.side / "ladder.json"))):
            patcher = mock.patch.dict(os.environ, {key: value})
            patcher.start()
            self.addCleanup(patcher.stop)
        pm.mkdir(parents=True, exist_ok=True)
        self.tracker = pm / "t.md"
        self.tracker.write_text(TRACKER, encoding="utf-8")

    def tearDown(self):
        self.assertEqual(os.environ["BOSS_ALERT"], str(self.alert), "BOSS_ALERT must be the stub")
        super().tearDown()

    def alerts(self):
        return [c.argv for c in self.sb.calls_of("boss-alert")]

    def synced(self, **kw):
        """Run review(track='t') with the sync replaced by a recorder of the attempts log it saw."""
        seen = []
        with mock.patch.object(codex_blocker, "sync",
                               side_effect=lambda track: seen.append((track, self.attempts_log()))):
            result = self.review(track="t", **kw)
        return result, seen


class TrackArgument(Base):
    def test_a_track_that_is_not_a_plain_name_is_a_value_error_before_the_pr_is_read(self):
        for bad in ("a..b", "../x", "Upper", "", "a/b", "x" * 65, 7):
            with self.subTest(track=bad):
                with self.assertRaises(ValueError):
                    self.review(track=bad)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.assertEqual(self.sb.calls_of("codex"), [])

    def test_the_command_line_turns_a_bad_track_into_exit_two_with_nothing_claimed(self):
        args = ["--repo", REPO, "--pr", str(PR), "--checkout", str(self.checkout), "--author", AUTHOR]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(br.main(args + ["--track", "../x"]), 2)
        self.assertIn("track", err.getvalue())
        self.assertEqual((self.sb.calls_of("gh"), self.sb.calls_of("codex"), self.reviews.exists()),
                         ([], [], False))

    def test_the_command_line_passes_the_track_on(self):
        args = ["--repo", REPO, "--pr", str(PR), "--checkout", str(self.checkout), "--author", AUTHOR]
        for extra, want in (([], None), (["--track", "t"], "t")):
            with mock.patch.object(br, "review", return_value=br._nothing(0)) as rv:
                br.main(args + extra)
            self.assertEqual(rv.call_args.kwargs["track"], want)

    def test_check_fallback_takes_no_track(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            br.main(["--check-fallback", "--checkout", str(self.checkout), "--track", "t"])

    def assertNoSyncButTheResultStands(self, real):
        self.codex(answer="VERDICT: GO")
        err = io.StringIO()
        with mock.patch.object(codex_health, "health", side_effect=AssertionError("health ran")), \
                contextlib.redirect_stderr(err):
            result = self.review(track="t")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("no blocker can be raised", err.getvalue())
        self.assertEqual((real.read_text(encoding="utf-8"), self.alerts()), (TRACKER, []))

    def test_a_missing_tracker_says_so_runs_no_health_sync_and_keeps_the_result(self):
        self.tracker.unlink()
        other = self.tracker.with_name("other.md")
        other.write_text(TRACKER, encoding="utf-8")
        self.assertNoSyncButTheResultStands(other)

    def test_a_symlinked_tracker_says_so_runs_no_health_sync_and_keeps_the_result(self):
        real = self.tracker.with_name("real.md")
        real.write_text(TRACKER, encoding="utf-8")
        self.tracker.unlink()
        self.tracker.symlink_to(real)
        self.assertNoSyncButTheResultStands(real)


class WhenTheSyncRuns(Base):
    def test_after_a_posted_verdict_once_with_the_attempts_already_logged(self):
        self.codex(answer="VERDICT: GO")
        result, seen = self.synced()
        self.assertEqual(result.exit_code, 0)
        (track, log), = seen
        self.assertEqual((track, [l["reason"] for l in log]), ("t", ["answered"]))

    def test_never_with_track_none(self):
        self.codex(answer="VERDICT: GO")
        with mock.patch.object(codex_blocker, "sync", side_effect=AssertionError("synced")):
            self.assertEqual(self.review().exit_code, 0)

    def test_after_a_refused_answer_whose_attempts_are_logged_with_round_null(self):
        attempt = {"reviewer": "codex", "reason": "answered", "exit_code": 0}
        with mock.patch.object(br, "_ask_codex", side_effect=br._Refused("a NUL", [attempt])):
            result, seen = self.synced()
        self.assertEqual(result.exit_code, 7)
        (track, log), = seen
        self.assertEqual([l["round"] for l in log], [None])

    def test_after_a_head_moved_round(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(view=[{}, {}, {"patch": {"headRefOid": OTHER_SHA}}])
        result, seen = self.synced()
        self.assertEqual((result.exit_code, result.status), (6, "head-moved"))
        self.assertEqual(len(seen), 1)

    def test_after_a_round_left_empty(self):
        self.codex(answer="VERDICT: NO-GO")
        with mock.patch.object(br, "write_out", side_effect=OSError("disk full")):
            result, seen = self.synced()
        self.assertEqual((result.exit_code, result.status), (7, None))
        self.assertEqual(len(seen), 1)

    def test_after_a_no_verdict(self):
        self.codex(answer="no idea")
        result, seen = self.synced()
        self.assertEqual((result.exit_code, result.status), (4, "no-verdict"))
        self.assertEqual(len(seen), 1)

    def test_after_a_failed_post(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(comment=[{"rc": 1}])
        result, seen = self.synced()
        self.assertEqual((result.exit_code, result.status), (7, "post-failed"))
        self.assertEqual(len(seen), 1)

    def test_after_a_findings_failure_the_attempts_are_logged_with_round_null_and_the_exit_is_seven(self):
        self.codex(answer="VERDICT: GO")
        with mock.patch.object(br, "findings_block", side_effect=OSError("rules unreadable")):
            result, seen = self.synced()
        self.assertEqual(result, br.ReviewResult(7, None, None, None, None, None))
        (track, log), = seen
        self.assertEqual([(l["round"], l["reviewer"], l["reason"]) for l in log], [(None, "codex", "answered")])
        self.assertEqual(self.comments(), [])
        self.assertEqual(list(self.reviews.glob("*/*/pr*/round*")), [])

    def test_never_when_the_run_ended_before_the_chain_answered(self):
        self.gh.configure(view=[{"rc": 1}])
        with mock.patch.object(codex_blocker, "sync", side_effect=AssertionError("synced")):
            self.assertEqual(self.review(track="t").exit_code, 7)

    def test_a_failing_sync_is_said_and_the_exit_code_is_the_reviews(self):
        self.codex(answer="VERDICT: NO-GO")
        err = io.StringIO()
        with mock.patch.object(codex_blocker, "sync", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(err):
            self.assertEqual(self.review(track="t").exit_code, 3)
        self.assertIn("boom", err.getvalue())


class EndToEnd(Base):
    def test_three_failed_reviews_raise_one_blocker_and_two_answers_clear_it(self):
        for n in range(3):
            self.assertEqual(self.review(track="t").exit_code, 4)      # no codex stub: absent
            self.assertEqual(len(self.alerts()), 1 if n == 2 else 0)
        text = self.tracker.read_text(encoding="utf-8")
        self.assertEqual(text.count("[ladder id=cd"), 1)
        self.assertEqual(self.alerts()[0][0], "0")
        self.review(track="t")                     # a fourth failure: still one blocker, no second alert
        self.assertEqual(len(self.alerts()), 1)
        self.codex(answer="VERDICT: GO")
        self.assertEqual(self.review(track="t").exit_code, 0)
        self.assertNotIn(" cleared=", self.tracker.read_text(encoding="utf-8"))
        self.assertEqual(self.review(track="t").exit_code, 0)
        self.assertEqual([c[0] for c in self.alerts()], ["0", "clear"])
        self.assertIn(" cleared=", self.tracker.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(json.dumps(codex_health.health()["state"])), "up")


if __name__ == "__main__":
    unittest.main()
