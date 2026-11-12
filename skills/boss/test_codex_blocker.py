#!/usr/bin/env python3
"""Tests for codex_blocker.py (ticket 05c): the "Codex down" blocker is raised after
policy.CODEX_DOWN_AFTER failed attempts and cleared after policy.CODEX_UP_AFTER answered ones.

Run: python3 -m pytest skills/boss/test_codex_blocker.py

No test posts a real alert or writes a real tracker: every test runs inside hermetic.Sandbox, with
BOSS_ALERT, BOSS_LADDER_PM, BOSS_LADDER_STATE, HOME and CLAUDE_CONFIG_DIR pinned into its temp dir,
and asserts the alert stub's call log (one `0` call per raise, one `clear` call per clear).
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_blocker  # noqa: E402
import codex_health  # noqa: E402
import policy  # noqa: E402
import tracker  # noqa: E402
from hermetic import Sandbox  # noqa: E402

LADDER = HERE.parent.parent / "routines" / "boss_ladder_core.py"
NOW = datetime(2026, 11, 12, 10, 30, 15, tzinfo=timezone(timedelta(hours=1)))
F, OK, NV = "timeout", "answered", "noverdict"
TRACKER = "# t\n\n## Open blockers\n\n## Notes\nprose with id=cd000000000000 outside the section\n"
CD = re.compile(r"id=cd[0-9]{12}")


def entry(reason, repo="o/r", pr=1, reviewer="codex"):
    return {"ts": "2026-11-12T10:00:00+01:00", "repo": repo, "pr": pr, "round": 1, "reviewer": reviewer,
            "reason": reason, "exit_code": 0}


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.alert = self.sb.stub("boss-alert")
        pm = self.sb.cfg / "pm"
        env = dict(self.sb.env, BOSS_ALERT=str(self.alert), BOSS_LADDER_PM=str(pm),
                   BOSS_LADDER_STATE=str(self.sb.side / "ladder.json"))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        (pm / "reviews").mkdir(parents=True)
        self.path = pm / "t.md"
        self.path.write_text(TRACKER, encoding="utf-8")
        self.log = pm / "reviews" / "attempts.jsonl"
        self.log.write_text("", encoding="utf-8")

    def tearDown(self):
        self.sb.guard()
        self.assertEqual(os.environ["BOSS_ALERT"], str(self.alert), "BOSS_ALERT must be the stub")

    def add(self, *reasons, **kw):
        with open(self.log, "a", encoding="utf-8") as fh:
            for r in reasons:
                fh.write(json.dumps(entry(r, **kw)) + "\n")

    def sync(self, now=NOW, track="t"):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            codex_blocker.sync(track, now=now)
        return err.getvalue()

    def text(self):
        return self.path.read_text(encoding="utf-8")

    def cd_lines(self):
        return [ln for ln in self.text().split("\n") if CD.search(ln)
                and tracker.has_marker(ln)]

    def alerts(self, rung=None):
        calls = [c.argv for c in self.sb.calls_of("boss-alert")]
        return calls if rung is None else [c for c in calls if c[0] == rung]

    def clear_by_hand(self):
        lines = self.text().split("\n")
        lines = [tracker.mark_cleared(ln, NOW) if self.is_cd(ln) else ln for ln in lines]
        self.path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def is_cd(ln):
        return bool(CD.search(ln)) and tracker.has_marker(ln)


class Raise(Base):
    def test_numbers_are_the_policys(self):
        self.assertEqual((policy.CODEX_DOWN_AFTER, policy.CODEX_UP_AFTER), (3, 2))

    def test_three_failures_raise_one_marked_line_and_one_alert(self):
        self.add(F, F)
        self.sync()
        self.assertEqual((self.cd_lines(), self.alerts()), ([], []))
        self.add("absent", pr=7)
        self.sync()
        (ln,) = self.cd_lines()
        self.assertRegex(ln, r"^- Codex down: 3 failed Codex attempts in a row \(last: o/r#7 absent; "
                             r"2 PRs affected\) - T\+0 2026-11-12T10:30\+01:00 \[ladder id=cd261112103015 ")
        raw, fields = tracker.scan_marker(ln)
        m = tracker.validate(fields)
        self.assertEqual((m["last"], m["id"], m["cleared"]), (0, "cd261112103015", ""))
        self.assertEqual(m["t0"], NOW.replace(second=0))
        self.assertEqual(m["next"], m["t0"] + timedelta(minutes=policy.RUNGS[0]))
        self.assertNotIn('"', m["ask"])
        for word in ("wait", "fallback review", "merge on tests alone"):
            self.assertIn(word, m["ask"])
        lines = self.text().split("\n")
        lo, hi = tracker.blockers_range(lines)
        self.assertIn(lines.index(ln), range(lo, hi))
        (call,) = self.alerts()
        self.assertEqual(call[0], "0")
        self.assertIn("Codex down", call[1])
        self.assertIn("t:", call[1])

    def test_a_second_run_adds_nothing_and_posts_nothing(self):
        self.add(F, F, F)
        self.sync()
        self.sync(NOW + timedelta(minutes=3))
        self.assertEqual((len(self.cd_lines()), len(self.alerts())), (1, 1))

    def test_a_tracker_without_the_section_gets_it_and_the_line_inside_it(self):
        self.path.write_text("# t\n\nprose\n", encoding="utf-8")
        self.add(F, F, F)
        self.sync()
        lines = self.text().split("\n")
        lo, hi = tracker.blockers_range(lines)
        (ln,) = self.cd_lines()
        self.assertIn(lines.index(ln), range(lo, hi))

    def test_a_naive_now_is_a_value_error_and_nothing_is_written(self):
        self.add(F, F, F)
        before = self.text()
        with self.assertRaises(ValueError):
            codex_blocker.sync("t", now=datetime(2026, 11, 12, 10, 30, 15))
        self.assertEqual((self.text(), self.alerts()), (before, []))

    def test_two_outages_in_one_minute_get_two_ids_and_both_lines_stay(self):
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.sync(NOW + timedelta(seconds=20))
        ids = [CD.search(ln).group() for ln in self.cd_lines()]
        self.assertEqual(len(set(ids)), 2, ids)
        self.assertEqual(len(self.alerts("0")), 2)

    def test_two_outages_with_the_same_injected_now_get_two_ids(self):
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.sync()
        ids = [CD.search(ln).group() for ln in self.cd_lines()]
        self.assertEqual(ids, ["id=cd261112103015", "id=cd261112103016"])

    def test_an_id_on_a_cleared_line_is_never_reused(self):
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.sync(NOW)
        self.assertEqual(len({CD.search(ln).group() for ln in self.cd_lines()}), 2)

    def test_prose_outside_the_blockers_section_does_not_hold_back_a_raise(self):
        # prose under ## Notes names the id the raise would take: the id is still never shared, so the next second
        self.path.write_text(TRACKER.replace("cd000000000000", "cd261112103015"), encoding="utf-8")
        self.add(F, F, F)
        self.sync()
        (ln,) = self.cd_lines()
        self.assertIn("id=cd261112103016", ln)

    def test_a_down_state_with_a_shorter_streak_raises_nothing(self):
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.add(OK)             # still down, failures 0, and the last_* fields name the old failure
        err = self.sync(NOW + timedelta(hours=1))
        self.assertEqual((codex_health.health()["state"], codex_health.health()["failures"]), ("down", 0))
        self.assertEqual(len(self.alerts("0")), 1)
        self.assertEqual(len(re.findall(r"^- Codex down", self.text(), re.M)), 1)
        self.assertEqual(self.alerts("clear"), [])
        self.assertEqual(err, "")
        self.add(F)              # one failure after the answer: a streak of one
        self.sync(NOW + timedelta(hours=2))
        self.assertEqual(len(self.alerts()), 1)

    def test_the_state_flipping_between_a_first_read_and_the_locked_step_raises_nothing(self):
        self.add(F, F, F)
        real = tracker.update

        def flipping(path, fn, deadline):
            self.add(OK, OK)     # the answers land after the caller looked, before the lock was taken
            return real(path, fn, deadline)

        with mock.patch.object(tracker, "update", flipping):
            self.sync()
        self.assertEqual((self.cd_lines(), self.alerts()), ([], []))

    def test_eight_processes_at_the_nth_failure_give_one_line_and_one_alert(self):
        self.add(F, F, F)
        code = "import codex_blocker; codex_blocker.sync('t')"
        env = dict(os.environ, PYTHONPATH=str(HERE))
        procs = [subprocess.Popen([sys.executable, "-c", code], env=env, stderr=subprocess.PIPE, text=True)
                 for _ in range(8)]
        errs = [p.communicate(timeout=60)[1] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 8, errs)
        self.assertEqual(len(self.cd_lines()), 1)
        self.assertEqual(len(self.alerts("0")), 1)

    def test_a_broken_open_cd_marker_gets_no_second_line(self):
        for broken in ('[ladder id=cd261112090000 t0=2026-11-12T09:00+01:00 last=0',      # never closed
                       '[ladder id=cd261112090000 t0=yesterday last=0 next=x ask="a"]'):   # validate refuses
            with self.subTest(broken=broken):
                self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- old " + broken + "\n"),
                                     encoding="utf-8")
                self.add(F, F, F)
                err = self.sync()
                self.assertEqual(len(self.cd_lines()), 1)
                self.assertTrue(err.strip(), "a broken marker is reported on stderr")
                self.assertEqual(self.alerts(), [])

    def test_a_broken_line_the_owner_closed_by_hand_does_not_hold_back_a_new_blocker(self):
        broken = '- old [ladder id=cd261112090000 t0=bad last=0 next=x cleared=zz ask="a"]\n'
        self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n" + broken), encoding="utf-8")
        self.add(F, F, F)
        self.sync()
        self.assertEqual(len(self.cd_lines()), 2)
        self.assertEqual(len(self.alerts("0")), 1)

    def test_a_failed_alert_is_reported_not_retried_and_keeps_the_line(self):
        self.sb.stub("boss-alert", rc=1)
        self.add(F, F, F)
        err = self.sync()
        self.sync(NOW + timedelta(minutes=1))
        self.assertIn("boss-alert", err)
        self.assertEqual((len(self.cd_lines()), len(self.alerts())), (1, 1))

    def test_a_failed_update_is_reported_and_posts_nothing(self):
        self.add(F, F, F)
        with mock.patch.object(tracker, "update", return_value="failed: lock held past the deadline"):
            err = self.sync()
        self.assertIn("lock held", err)
        self.assertEqual(self.alerts(), [])

    def test_a_tracker_that_is_not_a_regular_file_of_the_user_raises_nothing(self):
        real = self.path.with_name("real.md")
        real.write_text(TRACKER, encoding="utf-8")
        self.path.unlink()
        self.path.symlink_to(real)
        self.add(F, F, F)
        with mock.patch.object(codex_health, "health", side_effect=AssertionError("no health sync")):
            err = self.sync()
        self.assertIn("no blocker can be raised", err)
        self.assertEqual((self.alerts(), real.read_text(encoding="utf-8")), ([], TRACKER))
        for bad in ("a..b", "../x", "Upper"):
            with self.assertRaises(ValueError):
                codex_blocker.sync(bad, now=NOW)
        self.assertIn("no blocker can be raised", self.sync(track="nosuch"))


class Clear(Base):
    def test_one_answer_keeps_it_open_two_clear_it_once_and_a_third_run_is_silent(self):
        self.add(F, F, F)
        self.sync()
        self.add(OK)
        self.sync(NOW + timedelta(minutes=1))
        self.assertEqual(self.alerts("clear"), [])
        self.assertNotIn(" cleared=", self.text())
        self.add(OK)
        self.sync(NOW + timedelta(minutes=2))
        (call,) = self.alerts("clear")
        self.assertIn("Codex", call[1])
        (ln,) = self.cd_lines()
        self.assertEqual(tracker.validate(tracker.scan_marker(ln)[1])["cleared"], "2026-11-12T10:32+01:00")
        self.sync(NOW + timedelta(minutes=3))
        self.assertEqual((len(self.alerts("clear")), len(self.alerts("0"))), (1, 1))

    def test_one_answer_amid_failures_never_clears(self):
        self.add(F, F, F)
        self.sync()
        self.add(OK, F, OK)        # two answers, but not in a row
        self.sync(NOW + timedelta(minutes=1))
        self.assertEqual(self.alerts("clear"), [])
        self.assertNotIn(" cleared=", self.text())
        self.add(OK)
        self.sync(NOW + timedelta(minutes=2))
        self.assertEqual(len(self.alerts("clear")), 1)

    def test_codex_up_with_only_a_broken_cd_line_posts_no_clear(self):
        for broken in ('[ladder id=cd261112090000 t0=2026-11-12T09:00+01:00 last=0',
                       '[ladder id=cd261112090000 t0=yesterday last=0 next=x ask="a"]'):
            with self.subTest(broken=broken):
                self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- old " + broken + "\n"),
                                     encoding="utf-8")
                self.log.write_text("", encoding="utf-8")
                self.add(OK, OK)
                before = self.text()
                err1 = self.sync()
                self.sync()
                self.assertEqual((self.text(), self.alerts()), (before, []))
                self.assertTrue(err1.strip())

    def test_a_valid_open_line_beside_a_broken_one_is_cleared_without_an_alert(self):
        valid = tracker.render_marker("cd261112080000", NOW, NOW + timedelta(minutes=5), ask="x")
        broken = '[ladder id=cd261112090000 t0=bad last=0 next=x ask="a"]'
        self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- v %s\n- b %s\n" % (valid, broken)),
                             encoding="utf-8")
        self.add(OK, OK)
        err = self.sync()
        self.assertIn("cleared=2026-11-12T10:30+01:00", self.text().split("\n")[3])
        self.assertIn(broken, self.text())
        self.assertEqual(self.alerts(), [])
        self.assertTrue(err.strip())

    def test_every_open_cd_line_is_cleared_and_one_clear_is_posted(self):
        a = tracker.render_marker("cd261112080000", NOW, NOW, ask="x")
        b = tracker.render_marker("cd261112080001", NOW, NOW, ask="x")
        self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- a %s\n- b %s\n" % (a, b)),
                             encoding="utf-8")
        self.add(OK, OK)
        self.sync()
        self.assertEqual(self.text().count(" cleared="), 2)
        self.assertEqual(len(self.alerts("clear")), 1)

    def test_a_failed_clear_alert_is_reported_and_not_retried(self):
        self.add(F, F, F)
        self.sync()
        self.sb.stub("boss-alert", rc=1)
        self.add(OK, OK)
        err = self.sync(NOW + timedelta(minutes=1))
        self.sync(NOW + timedelta(minutes=2))
        self.assertIn("boss-alert", err)
        self.assertEqual(len(self.alerts("clear")), 1)


class Ladder(Base):
    def test_the_ladder_escalates_the_raised_line_at_rung_five_without_a_boss_turn(self):
        (self.sb.cfg / "pm" / "t.goal.md").write_text("# Objective - t\n_Status: OPEN_\n", encoding="utf-8")
        self.add(F, F, F)
        self.sync()
        (ln,) = self.cd_lines()
        self.assertEqual([c[0] for c in self.alerts()], ["0"])
        ladder_alert = self.sb.stub("boss-alert-ladder")       # a log of its own: only the ladder's calls
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
        env.update(BOSS_LADDER_PM=str(self.sb.cfg / "pm"), BOSS_LADDER_STATE=str(self.sb.side / "ladder.json"),
                   BOSS_ALERT=str(ladder_alert), CLAUDE_CONFIG_DIR=str(self.sb.cfg), HOME=str(self.sb.home))
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        t0 = tracker.validate(tracker.scan_marker(ln)[1])["t0"]
        run = subprocess.run([sys.executable, str(LADDER), "--now", (t0 + timedelta(minutes=6)).isoformat()],
                             env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        calls = [c.argv for c in self.sb.calls_of("boss-alert-ladder")]
        self.assertEqual([c[0] for c in calls], ["5"], run.stdout)
        self.assertTrue(calls[0][1].startswith("t: Codex"), calls[0][1])
        self.assertEqual(len(self.alerts()), 1)       # the ladder never reached the raise's stub
        m = tracker.validate(tracker.scan_marker(self.cd_lines()[0])[1])
        self.assertEqual(m["last"], 5)
        self.assertEqual(m["next"], t0 + timedelta(minutes=policy.RUNGS[1]))


if __name__ == "__main__":
    unittest.main()
