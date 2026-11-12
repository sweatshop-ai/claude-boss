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
from datetime import datetime, timedelta, timezone, tzinfo
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
LATER = (NOW + timedelta(seconds=20)).isoformat()     # a failure logged after clear_by_hand (which clears at NOW)


def entry(reason, repo="o/r", pr=1, reviewer="codex", ts="2026-11-12T10:00:00+01:00"):
    return {"ts": ts, "repo": repo, "pr": pr, "round": 1, "reviewer": reviewer,
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

    def add(self, *reasons, **kw):            # ts=<ISO string> dates the lines; the default is before NOW
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
        self.assertEqual(m["ask"], codex_blocker.ASK)
        for word in ("wait", "fallback review", "tests alone"):      # 09c: tests alone is offered again
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

    def test_a_tzinfo_without_an_offset_is_a_value_error_and_nothing_is_written(self):
        class NoOffset(tzinfo):
            def utcoffset(self, dt):
                return None

            def dst(self, dt):
                return None

        class Broken(NoOffset):
            def utcoffset(self, dt):
                raise TypeError("utcoffset() must return a timedelta")

        for tz in (NoOffset(), Broken()):
            with self.subTest(tz=type(tz).__name__):
                self.add(F, F, F)
                before = self.text()
                with self.assertRaises(ValueError):
                    codex_blocker.sync("t", now=datetime(2026, 11, 12, 10, 30, 15, tzinfo=tz))
                self.assertEqual((self.text(), self.alerts()), (before, []))

    def test_two_outages_in_one_minute_get_two_ids_and_both_lines_stay(self):
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.add(F, ts=LATER)
        self.sync(NOW + timedelta(seconds=20))
        ids = [CD.search(ln).group() for ln in self.cd_lines()]
        self.assertEqual(len(set(ids)), 2, ids)
        self.assertEqual(len(self.alerts("0")), 2)

    def test_two_outages_with_the_same_injected_now_get_two_ids(self):
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.add(F, ts=LATER)
        self.sync()
        ids = [CD.search(ln).group() for ln in self.cd_lines()]
        self.assertEqual(ids, ["id=cd261112103015", "id=cd261112103016"])
        self.assertEqual(len(self.alerts("0")), 2)

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


class HandClear(Base):
    """09a: a blocker the owner closed by hand holds until a failure with a later ts is logged."""

    def cleared(self, **kw):
        """Down, raised at NOW, then cleared by hand at NOW (10:30); the log holds three failures at 10:00."""
        self.add(F, F, F)
        self.sync()
        self.clear_by_hand()
        self.assertEqual(len(self.alerts("0")), 1)

    def set_cleared(self, value):
        self.path.write_text(re.sub(r" cleared=\S+", " cleared=" + value, self.text()), encoding="utf-8")

    def test_the_same_log_after_a_hand_clear_raises_nothing(self):
        self.cleared()
        before = self.text()
        err = self.sync(NOW + timedelta(hours=1))
        self.assertEqual((self.text(), len(self.alerts()), err), (before, 1, ""))

    def test_a_noverdict_after_the_clear_raises_nothing(self):
        self.cleared()
        self.add(NV, ts=LATER)
        self.sync(NOW + timedelta(hours=1))
        self.assertEqual((len(self.cd_lines()), len(self.alerts())), (1, 1))

    def test_one_more_failure_with_a_later_ts_raises_a_new_line_and_one_alert(self):
        self.cleared()
        self.add(F, ts=LATER)
        self.sync(NOW + timedelta(minutes=1))
        self.assertEqual(len(self.cd_lines()), 2)
        self.assertEqual(len(self.alerts("0")), 2)
        self.assertEqual(len({CD.search(ln).group() for ln in self.cd_lines()}), 2)

    def test_a_failure_in_the_clears_minute_counts_as_new(self):
        for at in ("2026-11-12T10:30:00+01:00", "2026-11-12T10:30:05+01:00"):    # HH:MM:00 and later in the minute
            with self.subTest(at=at):
                self.setUp()
                self.cleared()
                self.add(F, ts=at)
                self.sync(NOW + timedelta(minutes=1))
                self.assertEqual(len(self.alerts("0")), 2)

    def test_a_failure_in_the_minute_before_the_clear_does_not(self):
        self.cleared()
        self.add(F, ts="2026-11-12T10:29:59+01:00")
        self.sync(NOW + timedelta(minutes=1))
        self.assertEqual(len(self.alerts()), 1)

    def test_a_ts_in_another_offset_is_compared_as_an_instant(self):
        self.cleared()
        self.add(F, ts="2026-11-12T09:31:00Z")                   # 10:31+01:00, after the 10:30+01:00 clear
        self.sync(NOW + timedelta(minutes=2))
        self.assertEqual(len(self.alerts("0")), 2)

    def test_the_line_deleted_raises_again(self):
        self.cleared()
        self.path.write_text(TRACKER, encoding="utf-8")
        self.sync(NOW + timedelta(hours=1))
        self.assertEqual((len(self.cd_lines()), len(self.alerts("0"))), (1, 2))

    def test_an_up_syncs_clear_is_a_clear_and_three_later_failures_raise(self):
        self.add(F, F, F)
        self.sync()
        self.add(OK, OK, ts="2026-11-12T10:31:00+01:00")
        self.sync(NOW + timedelta(minutes=2))
        self.assertEqual(len(self.alerts("clear")), 1)
        self.add(F, F, F, ts="2026-11-12T10:40:00+01:00")
        self.sync(NOW + timedelta(minutes=12))
        self.assertEqual((len(self.cd_lines()), len(self.alerts("0"))), (2, 2))

    def test_an_unreadable_or_empty_cleared_does_not_hold(self):
        for value in ("", "yesterday", "2026-11-12T10:30"):         # empty, not ISO, no offset
            with self.subTest(value=value):
                self.setUp()
                self.add(F, F, F)
                self.sync()
                self.clear_by_hand()
                self.set_cleared(value)
                self.sync(NOW + timedelta(hours=1))
                # an empty value reads as open (no second line); the others are broken lines closed by hand
                self.assertEqual(len(self.alerts("0")), 1 if value == "" else 2, self.text())

    def test_a_last_ts_of_none_raises(self):
        self.cleared()
        real = codex_health.health

        def no_ts(path=None):
            return dict(real(path), last_ts=None)

        with mock.patch.object(codex_health, "health", no_ts):
            self.sync(NOW + timedelta(hours=1))
        self.assertEqual(len(self.alerts("0")), 2)

    def test_a_cleared_an_hour_ahead_is_ignored_with_a_note_on_stderr(self):
        self.cleared()
        self.set_cleared("2026-11-12T11:30+01:00")                  # last failure 10:00, now 10:30
        err = self.sync(NOW)
        self.assertEqual(len(self.alerts("0")), 2)
        self.assertIn("cleared=2026-11-12T11:30+01:00", err)
        self.assertIn("ignored", err)

    def test_a_clear_at_now_plus_60_s_holds_and_one_at_61_s_does_not(self):
        for second, value, raises in ((0, "2026-11-12T10:31+01:00", 1), (59, "2026-11-12T10:32+01:00", 2)):
            now = datetime(2026, 11, 12, 10, 30, second, tzinfo=NOW.tzinfo)       # the clear is at now + 60 s, now + 61 s
            with self.subTest(value=value):
                self.setUp()
                self.add(F, F, F, ts="2026-11-12T10:00:00+01:00")
                self.sync(now)
                self.clear_by_hand()
                self.set_cleared(value)
                err = self.sync(now)
                self.assertEqual(len(self.alerts("0")), raises, self.text())
                self.assertEqual("ignored" in err, raises == 2)

    def test_the_newest_of_two_clears_decides(self):
        self.cleared()
        self.add(F, ts="2026-11-12T10:25:00+01:00")                 # after the first clear below, before the second
        older = tracker.render_marker("cd261112080000", NOW, NOW, ask="x")
        older = tracker.mark_cleared(older, NOW - timedelta(minutes=30))
        self.path.write_text(self.text().replace("## Open blockers\n", "## Open blockers\n- old %s\n" % older),
                             encoding="utf-8")
        self.sync(NOW + timedelta(hours=1))
        self.assertEqual(len(self.alerts("0")), 1)                  # the 10:30 clear is the newest: 10:25 is old


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


class Choice(Base):
    """Ticket 09b: the owner's choice is a line in Decisions in force, written by --choose, read by --choice."""

    DEC = "\n## Decisions in force\n"

    def cli(self, *args):
        """The command in a process of its own, as the boss runs it (a restart between two calls)."""
        return subprocess.run([sys.executable, str(HERE / "codex_blocker.py"), *args], env=dict(os.environ),
                              capture_output=True, text=True, timeout=60)

    def raised(self, text=None):
        if text is not None:
            self.path.write_text(text, encoding="utf-8")
        self.add(F, F, F)
        self.sync()
        (ln,) = self.cd_lines()
        return tracker.validate(tracker.scan_marker(ln)[1])["id"]

    def lines_of(self, id_):
        return [ln for ln in self.text().split("\n") if ln.startswith("- [codex-choice %s]" % id_)]

    def same_blockers(self, before):
        """Open blockers hold the same entries as `before` (the Codex down entry's ask= is rewritten by
        --choose, so compare the count) and none of them is a choice line."""
        now = tracker.open_blockers(self.text())
        return len(now) == len(before) and not any(e.startswith("[codex-choice") for e in now)

    def decisions(self):
        lines = self.text().split("\n")
        head = next(i for i, ln in enumerate(lines) if ln.startswith("## Decisions in force"))
        end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        return lines[head + 1:end]

    def test_no_blocker_prints_no_blocker_and_exits_2_and_choose_writes_nothing(self):
        before = self.text()
        run = self.cli("--choice", "t")
        self.assertEqual((run.stdout.strip(), run.returncode), ("no-blocker", 2))
        run = self.cli("--choose", "t", "wait")
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn("no-blocker", run.stderr)
        self.assertEqual(self.text(), before)
        self.assertEqual(codex_blocker.choice("t"), ("no-blocker", None, None))

    def test_an_open_blocker_without_a_line_is_none_and_exits_1(self):
        id_ = self.raised()
        run = self.cli("--choice", "t")
        self.assertEqual((run.stdout.strip(), run.returncode), ("none", 1))
        self.assertEqual(codex_blocker.choice("t"), ("none", id_, None))

    def test_each_choice_survives_a_restart(self):
        for value in ("wait", "accept-fallback"):          # tests-alone: test_waiver.py, it needs the token
            with self.subTest(value):
                self.path.write_text(TRACKER, encoding="utf-8")
                self.log.write_text("", encoding="utf-8")
                id_ = self.raised()
                run = self.cli("--choose", "t", value)               # one process writes ...
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(id_, run.stdout)
                run = self.cli("--choice", "t")                      # ... another reads
                self.assertEqual((run.stdout.strip(), run.returncode), (value, 0), run.stderr)
                self.assertEqual(codex_blocker.choice("t"), ("chosen", id_, value))
                (ln,) = self.lines_of(id_)
                self.assertRegex(ln, r"^- \[codex-choice cd[0-9]{12}\] %s - \S+$" % value)
                self.assertNotIn(tracker.TOKEN, ln)

    def test_the_line_goes_into_decisions_and_not_into_open_blockers(self):
        id_ = self.raised()
        blockers_before = tracker.open_blockers(self.text())
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 0)
        self.assertEqual(len(self.lines_of(id_)), 1)
        self.assertIn(self.lines_of(id_)[0], self.decisions())
        lines = self.text().split("\n")
        lo, hi = tracker.blockers_range(lines)
        self.assertNotIn(self.lines_of(id_)[0], lines[lo:hi])
        self.assertEqual(self.same_blockers(blockers_before), True)

    def test_with_open_blockers_as_the_last_section_the_line_still_lands_in_decisions(self):
        for tail in ("# t\n\n## Decisions in force\n\n## Notes\nx\n\n## Open blockers\n",
                     "# t\n\n## Notes\nx\n\n## Open blockers\n"):          # the second has no Decisions section
            with self.subTest(tail=tail):
                self.log.write_text("", encoding="utf-8")
                id_ = self.raised(tail)
                before = tracker.open_blockers(self.text())
                self.assertEqual(len(before), 1)
                self.assertEqual(self.cli("--choose", "t", "accept-fallback").returncode, 0)
                (ln,) = self.lines_of(id_)
                self.assertIn(ln, self.decisions())
                self.assertTrue(self.same_blockers(before))
                self.assertEqual(codex_blocker.choice("t")[2], "accept-fallback")

    def test_choosing_the_same_twice_writes_one_line_and_changes_nothing_the_second_time(self):
        id_ = self.raised()
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 0)
        once = self.text()
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 0)
        self.assertEqual(self.text(), once)
        self.assertEqual(len(self.lines_of(id_)), 1)

    def test_a_revocation_is_not_dropped_by_an_identical_earlier_line(self):
        id_ = self.raised()
        for value in ("wait", "accept-fallback", "wait"):
            self.assertEqual(self.cli("--choose", "t", value).returncode, 0)
        lines = self.lines_of(id_)
        self.assertEqual([ln.split("] ")[1].split(" - ")[0] for ln in lines], ["wait", "accept-fallback", "wait"])
        self.assertEqual(codex_blocker.choice("t"), ("chosen", id_, "wait"))
        self.assertEqual(self.cli("--choice", "t").stdout.strip(), "wait")

    def test_choose_rewrites_the_markers_ask_and_leaves_the_marker_valid(self):
        self.raised()
        (before,) = self.cd_lines()
        mb = tracker.validate(tracker.scan_marker(before)[1])
        self.assertEqual(self.cli("--choose", "t", "accept-fallback").returncode, 0)
        (after,) = self.cd_lines()
        ma = tracker.validate(tracker.scan_marker(after)[1])
        self.assertEqual(ma["ask"], "Codex down; owner chose accept-fallback")
        for key in ("id", "last", "t0", "next", "cleared"):
            self.assertEqual(ma[key], mb[key])
        self.assertEqual(before.split("ask=")[0], after.split("ask=")[0])
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 0)
        self.assertEqual(tracker.validate(tracker.scan_marker(self.cd_lines()[0])[1])["ask"],
                         "Codex down; owner chose wait")

    def test_choose_posts_no_alert(self):
        self.raised()
        self.assertEqual(len(self.alerts()), 1)                # the raise's own, seen by the stub
        self.cli("--choose", "t", "wait")
        self.assertEqual(len(self.alerts()), 1)

    def test_a_choice_not_offered_is_refused_and_writes_nothing(self):
        self.raised()
        before = self.text()
        for value in ("yes", ""):
            run = self.cli("--choose", "t", value)
            self.assertEqual(run.returncode, 2, value)
            self.assertTrue(run.stderr.strip())
        self.assertEqual(self.text(), before)

    def test_an_invalid_track_is_exit_2_for_both_commands(self):
        for args in (("--choice", "../x"), ("--choose", "../x", "wait"), ("--choice", ""), ("--choice", "a/b")):
            run = self.cli(*args)
            self.assertEqual(run.returncode, 2, args)
            self.assertTrue(run.stderr.strip(), args)
            if args[0] == "--choice":
                self.assertEqual(run.stdout.strip(), "malformed", args)
        with self.assertRaises(ValueError):
            codex_blocker.choice("../x")

    def test_the_last_line_for_an_id_wins(self):
        id_ = self.raised()
        text = self.text()
        extra = "- [codex-choice %s] wait - 2026-11-12T10:31:00+01:00\n- [codex-choice %s] accept-fallback - x\n" % (id_, id_)
        self.path.write_text(text.replace("## Notes", "## Decisions in force\n" + extra + "\n## Notes", 1), encoding="utf-8")
        self.assertEqual(codex_blocker.choice("t"), ("chosen", id_, "accept-fallback"))

    def test_a_choice_for_a_cleared_blockers_id_does_not_count_for_a_new_one(self):
        old = self.raised()
        self.assertEqual(self.cli("--choose", "t", "accept-fallback").returncode, 0)
        self.clear_by_hand()
        self.assertEqual(codex_blocker.choice("t"), ("no-blocker", None, None))
        self.add(F, ts=LATER)
        self.sync(NOW + timedelta(minutes=5))
        (ln,) = [c for c in self.cd_lines() if " cleared=" not in c]
        new = tracker.validate(tracker.scan_marker(ln)[1])["id"]
        self.assertNotEqual(new, old)
        self.assertEqual(codex_blocker.choice("t"), ("none", new, None))
        self.assertEqual(self.cli("--choice", "t").returncode, 1)

    def test_lookalike_lines_are_ignored(self):
        id_ = self.raised()
        other = "cd000000000001"
        lookalikes = [
            "- [codex-choice %s] wait - 2026-11-12T10:31:00+01:00 and more" % id_,         # trailing text
            "- [codex-choice %s] wait" % id_,                                                # no timestamp
            "  - [codex-choice %s] wait - 2026-11-12T10:31:00+01:00" % id_,                  # indented
            "- [codex-choice %s] maybe - 2026-11-12T10:31:00+01:00" % id_,                   # not a choice
            "- [codex-choice %s] wait - 2026-11-12T10:31:00+01:00" % other,                  # another id
            "- [codex-choice cd26111210301] wait - 2026-11-12T10:31:00+01:00",               # short id
        ]
        outside = "- [codex-choice %s] accept-fallback - 2026-11-12T10:31:00+01:00" % id_  # wrong section
        text = self.text().replace("## Notes\n", "## Decisions in force\n" + "\n".join(lookalikes) + "\n\n## Notes\n" + outside + "\n", 1)
        self.path.write_text(text, encoding="utf-8")
        self.assertEqual(codex_blocker.choice("t"), ("none", id_, None))

    def test_a_broken_cd_line_alone_is_malformed_not_no_blocker(self):
        self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- Codex down: x [ladder id=cd261112103015 bogus]\n"),
                             encoding="utf-8")
        run = self.cli("--choice", "t")
        self.assertEqual((run.stdout.strip(), run.returncode), ("malformed", 2))
        self.assertTrue(run.stderr.strip())
        before = self.text()
        run = self.cli("--choose", "t", "wait")
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(self.text(), before)
        status, id_, why = codex_blocker.choice("t")
        self.assertEqual((status, id_), ("malformed", None))
        self.assertTrue(why)

    def test_two_open_valid_lines_are_malformed_and_choose_writes_nothing(self):
        a = tracker.render_marker("cd261112080000", NOW, NOW, ask="x")
        b = tracker.render_marker("cd261112080001", NOW, NOW, ask="x")
        self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- a %s\n- b %s\n" % (a, b)),
                             encoding="utf-8")
        before = self.text()
        run = self.cli("--choice", "t")
        self.assertEqual((run.stdout.strip(), run.returncode), ("malformed", 2))
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 2)
        self.assertEqual(self.text(), before)

    def test_a_tracker_that_is_not_a_regular_file_of_the_user_is_malformed(self):
        self.path.unlink()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, id_, why = codex_blocker.choice("t")
        self.assertEqual((status, id_), ("malformed", None))
        self.assertTrue(why and err.getvalue().strip())
        run = self.cli("--choice", "t")
        self.assertEqual((run.stdout.strip(), run.returncode), ("malformed", 2))
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 2)

    def test_a_held_lock_is_exit_1_with_nothing_written(self):
        self.raised()
        before = self.text()
        with mock.patch.object(codex_blocker, "LOCK_WAIT", 0.05), \
                mock.patch.object(tracker, "update", return_value="failed: lock held past the deadline"):
            rc, msg = codex_blocker.choose("t", "wait", now=NOW)
        self.assertEqual(rc, 1)
        self.assertIn("lock held", msg)
        self.assertEqual(self.text(), before)

    def test_a_naive_now_is_a_value_error(self):
        self.raised()
        with self.assertRaises(ValueError):
            codex_blocker.choose("t", "wait", now=datetime(2026, 11, 12, 10, 0))

    def test_a_tzinfo_without_an_offset_is_a_value_error(self):
        class NoOffset(tzinfo):
            def utcoffset(self, dt):
                return None

        self.raised()
        with self.assertRaises(ValueError):
            codex_blocker.choose("t", "wait", now=datetime(2026, 11, 12, 10, 0, tzinfo=NoOffset()))

    def test_the_ladder_and_classify_never_read_the_line(self):
        id_ = self.raised()
        self.assertEqual(self.cli("--choose", "t", "wait").returncode, 0)
        lines = self.text().split("\n")
        opened, broken = codex_blocker._classify(lines)
        self.assertEqual((len(opened), broken), (1, []))
        self.assertFalse(any(tracker.has_marker(ln) for ln in self.lines_of(id_)))


class Edges(Base):
    """Ticket 20: the edge cases found in the review of 05c."""

    def test_a_hand_written_empty_cleared_is_open_and_the_next_up_sync_clears_it(self):
        for empty in ("cleared=", 'cleared=""'):
            with self.subTest(empty=empty):
                self.setUp()
                marker = tracker.render_marker("cd261112080000", NOW, NOW, ask="x").replace(" ask=", " %s ask=" % empty)
                self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n- a %s\n" % marker),
                                     encoding="utf-8")
                self.assertEqual(codex_blocker._classify(self.text().split("\n"))[0], [3])
                self.add(OK, OK)
                self.sync()
                (ln,) = self.cd_lines()
                self.assertEqual(tracker.validate(tracker.scan_marker(ln)[1])["cleared"], "2026-11-12T10:30+01:00")
                self.assertEqual(codex_blocker._classify(self.text().split("\n")), ([], []))
                self.assertEqual(len(self.alerts("clear")), 1)
                after = self.text()
                self.sync(NOW + timedelta(minutes=1))
                self.assertEqual((self.text(), len(self.alerts())), (after, 1))

    def test_a_symlink_swapped_in_after_the_check_is_not_written_through(self):
        target = self.path.with_name("elsewhere.md")
        real_usable = codex_blocker.usable_tracker
        swapped = []

        def swap(track):
            path = real_usable(track)
            target.write_text(self.text(), encoding="utf-8")
            self.path.unlink()
            self.path.symlink_to(target)
            swapped.append(path)
            return path

        self.add(F, F, F)
        with mock.patch.object(codex_blocker, "usable_tracker", swap):
            err = self.sync()
        self.assertEqual(len(swapped), 1)
        self.assertIn("symbolic link", err)
        self.assertEqual((target.read_text(encoding="utf-8"), self.alerts()), (TRACKER, []))

    def test_a_symlink_swapped_in_after_the_check_is_not_chosen_through(self):
        self.add(F, F, F)
        self.sync()
        target = self.path.with_name("elsewhere.md")
        target.write_text(self.text(), encoding="utf-8")
        before = self.text()
        real_usable = codex_blocker.usable_tracker

        def swap(track):
            path = real_usable(track)
            self.path.unlink()
            self.path.symlink_to(target)
            return path

        with mock.patch.object(codex_blocker, "usable_tracker", swap):
            rc, msg = codex_blocker.choose("t", "wait", now=NOW)
        self.assertEqual(rc, 1)
        self.assertIn("symbolic link", msg)
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_an_id_that_is_not_the_markers_own_is_not_a_cd_line(self):
        lookalikes = (
            '- see id=cd261112090000 here [ladder id=zz11 t0=bad last=0 next=x ask="a"]',     # prose before the marker
            '- x [ladder id=cd2611120900001 t0=bad last=0 next=x ask="a"]',                   # a thirteenth digit
            '- x [ladder xid=cd261112090000 t0=bad last=0 next=x ask="a"]',                   # another field
            '- x [ladder id=zz11 t0=bad last=0 next=x ask="see id=cd261112090000"]',          # inside another's ask
        )
        for line in lookalikes:
            with self.subTest(line=line):
                self.setUp()
                self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n%s\n" % line),
                                     encoding="utf-8")
                self.assertEqual(codex_blocker._classify(self.text().split("\n")), ([], []))
                self.add(F, F, F)
                err = self.sync()
                self.assertEqual((err, len(self.alerts("0"))), ("", 1))
                self.assertEqual(codex_blocker._classify(self.text().split("\n"))[0], [4])

    def test_a_cd_id_in_the_markers_own_field_is_still_a_broken_cd_line(self):
        line = '- x see xid=cd261112090000 [ladder id=cd261112090000 t0=bad last=0 next=x ask="a"]'
        self.path.write_text(TRACKER.replace("## Open blockers\n", "## Open blockers\n%s\n" % line), encoding="utf-8")
        opened, broken = codex_blocker._classify(self.text().split("\n"))
        self.assertEqual((opened, [i for i, _ in broken]), ([], [3]))

    def test_a_repo_with_marker_characters_gives_one_valid_marker(self):
        repo = 'a]b"c[ladder x\nd'
        self.add(F, F, F, repo=repo)
        before = self.text().count("\n")
        self.sync()
        self.assertEqual(self.text().count("\n"), before + 1)
        self.assertEqual(self.text().count(tracker.TOKEN), 1)
        (ln,) = self.cd_lines()
        self.assertIn("(last: a?b?c?ladder?x?d#1 ", ln)
        self.assertEqual(tracker.validate(tracker.scan_marker(ln)[1])["ask"], codex_blocker.ASK)
        self.assertEqual(len(self.alerts("0")), 1)

    def test_a_crlf_tracker_is_raised_classified_chosen_and_cleared_with_its_line_ends(self):
        def raw():
            return self.path.read_bytes().decode("utf-8")

        self.path.write_bytes(TRACKER.replace("\n", "\r\n").encode("utf-8"))
        self.add(F, F, F)
        self.sync()
        self.assertEqual(len(self.alerts("0")), 1)
        self.assertNotRegex(raw(), r"(?<!\r)\n")
        self.assertEqual(len(codex_blocker._classify(raw().split("\n"))[0]), 1)
        self.assertEqual(codex_blocker.choice("t")[0], "none")
        self.sync(NOW + timedelta(minutes=1))
        self.assertEqual(len(self.alerts()), 1)
        self.assertEqual(codex_blocker.choose("t", "wait", now=NOW)[0], 0)
        self.assertEqual(codex_blocker.choice("t")[0], "chosen")
        self.assertNotRegex(raw(), r"(?<!\r)\n")
        self.add(OK, OK)
        self.sync(NOW + timedelta(minutes=2))
        self.assertEqual(len(self.alerts("clear")), 1)
        self.assertEqual(codex_blocker._classify(raw().split("\n")), ([], []))
        self.assertIn(" cleared=", raw())
        self.assertNotRegex(raw(), r"(?<!\r)\n")


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
