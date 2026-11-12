#!/usr/bin/env python3
"""Tests for tracker.py, and for the bash tools that write the same formats.

Run: python3 -m pytest skills/boss/test_tracker.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tracker  # noqa: E402
from hermetic import Sandbox  # noqa: E402
from tracker import MarkerError, scan_marker, validate  # noqa: E402

BIN = HERE / "bin"
TZ = timezone(timedelta(hours=2))


class Marker(unittest.TestCase):
    def test_fields(self):
        raw, f = scan_marker('- x [ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 '
                             'next=2026-09-18T10:58+02:00 pane=20:0.2 ask="do the thing"]')
        self.assertEqual(f["ask"], "do the thing")
        self.assertEqual(f["pane"], "20:0.2")
        self.assertTrue(raw.startswith("[ladder ") and raw.endswith("]"))

    def test_no_marker(self):
        self.assertIsNone(scan_marker("- a plain blocker line, no marker"))
        self.assertIsNone(scan_marker("- see [ladderish] elsewhere"))
        self.assertFalse(tracker.has_marker("- see [ladderish] elsewhere"))

    def test_a_bracket_inside_a_quoted_value(self):
        _, f = scan_marker('x [ladder id=ab12 t0=2026-09-18T10:53Z last=0 '
                           'next=2026-09-18T10:58Z ask="brackets ] inside"]')
        self.assertEqual(f["ask"], "brackets ] inside")

    def test_invalid_fields_are_refused(self):
        for bad, why in [
            ('[ladder id=ab12 last=0 ask="x"]', "missing t0/next"),
            ('[ladder id=AB t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 ask="x"]', "bad id"),
            ('[ladder id=ab12 t0=2026-09-18T10:53 last=0 next=2026-09-18T10:58+02:00 ask="x"]', "naive t0"),
            ('[ladder id=ab12 t0=nope last=0 next=2026-09-18T10:58+02:00 ask="x"]', "unparseable t0"),
            ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=x next=2026-09-18T10:58+02:00 ask="x"]',
             "last not a number"),
            ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 ask=""]', "empty ask"),
            ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 ask="x" wat=1]',
             "unknown field"),
        ]:
            with self.subTest(why), self.assertRaises(MarkerError):
                validate(scan_marker(bad)[1])

    def test_broken_tokens_are_refused(self):
        for bad, why in [('[ladder id=ab12 ask="unterminated]', "no closing quote"),
                         ('[ladder id=ab12 ask="x"', "not closed"),
                         ('[ladder id]', "no '='"),
                         ('[ladder Id=ab12]', "bad field name"),
                         ('[ladder id=ab id=cd]', "duplicate field")]:
            with self.subTest(why), self.assertRaises(MarkerError):
                scan_marker(bad)
            self.assertTrue(tracker.has_marker(bad), why)

    def test_render_reads_back(self):
        t0 = datetime(2026, 9, 18, 10, 53, tzinfo=TZ)
        raw = tracker.render_marker("a1b2c3d4", t0, t0 + timedelta(minutes=5), pane="20:0.2")
        m = validate(scan_marker("- line " + raw)[1])
        self.assertEqual((m["id"], m["t0"], m["last"], m["pane"], m["ask"]),
                         ("a1b2c3d4", t0, 0, "20:0.2", tracker.PLACEHOLDER))
        self.assertEqual(m["next"] - m["t0"], timedelta(minutes=5))
        self.assertIn(tracker.marker_tag("a1b2c3d4"), raw)

    def test_render_without_pane_and_with_an_ask(self):
        t0 = datetime(2026, 9, 18, 10, 53, tzinfo=TZ)
        raw = tracker.render_marker("ab12", t0, t0, ask="put the u2 file on lab-0")
        m = validate(scan_marker(raw)[1])
        self.assertEqual((m["pane"], m["ask"]), ("", "put the u2 file on lab-0"))

    def test_render_refuses_a_quote_in_ask(self):
        t0 = datetime(2026, 9, 18, 10, 53, tzinfo=TZ)
        with self.assertRaises(MarkerError):
            tracker.render_marker("ab12", t0, t0, ask='say "hi"')

    def test_rewrite_touches_only_last_and_next(self):
        before = ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 '
                  'next=2026-09-18T10:58+02:00 pane=20:0.2 ask="keep me"]')
        after = tracker.rewrite(before, 15, datetime(2026, 9, 18, 11, 23, tzinfo=TZ))
        self.assertEqual(after, '[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=15 '
                                'next=2026-09-18T11:23:00+02:00 pane=20:0.2 ask="keep me"]')


TRACKER = """# PM Tracker — t
| Suraya | reads `[ladder id= t0= last= next= ask=]` markers |

## Open blockers
- one
* two

  plain prose, not an entry
- three [ladder id=ab12 ask="x"]

## Decisions in force
- d

## Open blockers
- a second section is not read
"""


class OpenBlockers(unittest.TestCase):
    def test_only_the_first_section_is_read(self):
        self.assertEqual(tracker.open_blockers(TRACKER),
                         ["one", "two", 'three [ladder id=ab12 ask="x"]'])

    def test_range_matches_the_lines(self):
        lines = TRACKER.splitlines(keepends=True)
        lo, hi = tracker.blockers_range(lines)
        self.assertEqual("".join(lines[lo:hi]).splitlines(), tracker.blocker_lines(TRACKER))
        self.assertEqual(lines[hi], "## Decisions in force\n")

    def test_no_section(self):
        self.assertEqual(tracker.blockers_range(["# T\n", "- x\n"]), (0, 0))
        self.assertEqual(tracker.open_blockers("# T\n- x\n"), [])

    def test_a_heading_with_a_suffix_still_counts(self):
        self.assertEqual(tracker.open_blockers("## Open blockers / open steps\n- x\n"), ["x"])

    def test_insert_goes_before_the_trailing_blank(self):
        out = tracker.insert_in_section(TRACKER, tracker.BLOCKERS, "- four")
        self.assertIn('ask="x"]\n- four\n\n## Decisions in force', out)
        self.assertEqual(tracker.open_blockers(out)[-1], "four")

    def test_insert_creates_a_missing_section(self):
        out = tracker.insert_in_section("# T\n", tracker.BLOCKERS, "- two")
        self.assertEqual(tracker.open_blockers(out), ["two"])

    def test_the_lock_is_a_dot_sibling(self):
        self.assertEqual(tracker.lock_path(Path("/x/pm/demo.md")), Path("/x/pm/.demo.md.lock"))



LINE = ('- ship it [ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 '
        'next=2026-09-18T10:58+02:00 pane=20:0.2 ask="put the u2 file on lab-0"]')
WHEN = datetime(2026, 9, 18, 12, 7, 31, tzinfo=TZ)


class SetAsk(unittest.TestCase):
    def test_only_the_ask_value_changes(self):
        out = tracker.set_ask(LINE, "Codex down; owner chose wait")
        self.assertEqual(out, LINE.replace('ask="put the u2 file on lab-0"', 'ask="Codex down; owner chose wait"'))
        self.assertEqual(validate(scan_marker(out)[1])["ask"], "Codex down; owner chose wait")

    def test_a_quote_is_refused_and_a_line_without_a_marker_comes_back_as_it_was(self):
        with self.assertRaises(tracker.MarkerError):
            tracker.set_ask(LINE, 'a "b"')
        self.assertEqual(tracker.set_ask("- no marker ask=\"x\"", "y"), "- no marker ask=\"x\"")
        broken = "- x [ladder id=ab12 bogus]"
        self.assertEqual(tracker.set_ask(broken, "y"), broken)


class MarkCleared(unittest.TestCase):
    def test_cleared_goes_before_ask_and_nothing_else_moves(self):
        out = tracker.mark_cleared(LINE, WHEN)
        self.assertEqual(out, LINE.replace(' ask=', ' cleared=2026-09-18T12:07+02:00 ask='))
        _, fields = scan_marker(out)
        m = validate(fields)
        self.assertEqual(fields["cleared"], "2026-09-18T12:07+02:00")
        self.assertEqual(m["cleared"], "2026-09-18T12:07+02:00")
        before = validate(scan_marker(LINE)[1])
        self.assertEqual((m["last"], m["next"], m["t0"], m["ask"]),
                         (before["last"], before["next"], before["t0"], before["ask"]))

    def test_a_value_that_holds_the_text_ask_is_not_the_ask_key(self):
        line = ('- x [ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 '
                'next=2026-09-18T10:58+02:00 cost="idle, see ask= below" ask="go"]')
        out = tracker.mark_cleared(line, WHEN)
        self.assertEqual(validate(scan_marker(out)[1])["cost"], "idle, see ask= below")
        self.assertEqual(validate(scan_marker(out)[1])["cleared"], "2026-09-18T12:07+02:00")

    def test_lines_it_leaves_alone(self):
        for line in ["- a plain blocker, no marker",
                     "- see [ladderish] elsewhere",
                     '- broken [ladder id=ab12 ask="x"',
                     LINE.replace(' ask=', ' cleared=2026-09-18T11:00+02:00 ask='),
                     '- no ask [ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00]']:
            with self.subTest(line):
                self.assertEqual(tracker.mark_cleared(line, WHEN), line)

    def test_a_naive_when_is_a_value_error(self):
        with self.assertRaises(ValueError):
            tracker.mark_cleared(LINE, datetime(2026, 9, 18, 12, 7))


def held_lock(path):
    """A child process that holds the tracker's lock until its stdin closes."""
    code = ("import fcntl,sys\nf=open(sys.argv[1],'w')\nfcntl.flock(f,fcntl.LOCK_EX)\n"
            "print('held',flush=True)\nsys.stdin.read()\n")
    proc = subprocess.Popen([sys.executable, "-I", "-c", code, str(tracker.lock_path(path))],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


class Update(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="boss-tracker-upd-"))
        self.path = self.dir / "t.md"
        self.path.write_text("# T\n\n## Open blockers\n- one\n")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def far(self):
        return time.monotonic() + 5

    def temps(self):
        return sorted(p.name for p in self.dir.glob(".boss-tracker-*"))

    def test_done_writes_the_new_text(self):
        got = tracker.update(self.path, lambda t: t + "- two\n", self.far())
        self.assertEqual(got, "done")
        self.assertEqual(self.path.read_text(), "# T\n\n## Open blockers\n- one\n- two\n")
        self.assertEqual(self.temps(), [])

    def test_none_is_no_change_and_writes_nothing(self):
        ino = self.path.stat().st_ino
        before = self.path.read_bytes()
        self.assertEqual(tracker.update(self.path, lambda t: None, self.far()), "done (no change)")
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_ino), (before, ino))
        self.assertEqual(self.temps(), [])

    def test_the_mode_is_kept(self):
        self.path.chmod(0o640)
        tracker.update(self.path, lambda t: t + "x\n", self.far())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_line_ends_are_kept(self):
        self.path.write_bytes(b"# T\r\n- one\r\n")
        tracker.update(self.path, lambda t: t + "- two\r\n", self.far())
        self.assertEqual(self.path.read_bytes(), b"# T\r\n- one\r\n- two\r\n")

    def test_a_lock_held_past_the_deadline_fails_without_a_hang(self):
        holder = held_lock(self.path)
        calls = []
        try:
            t0 = time.monotonic()
            got = tracker.update(self.path, lambda t: calls.append(1) or t + "x", t0 + 0.2)
            took = time.monotonic() - t0
        finally:
            holder.stdin.close()
            holder.wait(timeout=10)
        self.assertTrue(got.startswith("failed: "), got)
        self.assertLess(took, 3)
        self.assertEqual(calls, [])
        self.assertEqual(self.path.read_text(), "# T\n\n## Open blockers\n- one\n")
        self.assertEqual(self.temps(), [])

    def test_a_lock_released_before_the_deadline_is_taken(self):
        holder = held_lock(self.path)
        timer = threading.Timer(0.3, holder.stdin.close)
        timer.start()
        try:
            t0 = time.monotonic()
            got = tracker.update(self.path, lambda t: t + "x\n", t0 + 10)
            took = time.monotonic() - t0
        finally:
            timer.join()
            holder.wait(timeout=10)
        self.assertEqual(got, "done")
        self.assertGreaterEqual(took, 0.25)

    def test_a_file_that_changes_on_every_try_fails_after_three_calls(self):
        calls = []

        def fn(text):
            calls.append(1)
            # The boss's Edit tool takes no lock: the file moves under us.
            self.path.write_text(self.path.read_text() + "edit %d\n" % len(calls))
            return text + "- mine\n"
        got = tracker.update(self.path, fn, self.far())
        self.assertTrue(got.startswith("failed: "), got)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("- mine", self.path.read_text())
        self.assertEqual(self.temps(), [])

    def test_a_file_that_changes_once_is_redone_on_the_new_text(self):
        calls = []

        def fn(text):
            calls.append(text)
            if len(calls) == 1:
                self.path.write_text(text + "- edited\n")
            return text + "- mine\n"
        self.assertEqual(tracker.update(self.path, fn, self.far()), "done")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.path.read_text(), "# T\n\n## Open blockers\n- one\n- edited\n- mine\n")

    def test_an_oserror_is_a_return_value_named_for_the_error(self):
        got = tracker.update(self.dir / "missing.md", lambda t: t, self.far())
        self.assertEqual(got, "failed: FileNotFoundError")
        got = tracker.update(self.dir / "no-dir" / "t.md", lambda t: t, self.far())
        self.assertEqual(got, "failed: FileNotFoundError")

    def test_a_failed_write_leaves_no_temp_file(self):
        self.dir.chmod(0o500)
        try:
            if os.access(self.dir, os.W_OK):
                self.skipTest("directory permissions are not enforced here")
            got = tracker.update(self.path, lambda t: t + "x", self.far())
        finally:
            self.dir.chmod(0o700)
        self.assertEqual(got, "failed: PermissionError")
        self.assertEqual(self.temps(), [])

    def test_an_exception_from_fn_is_not_swallowed_and_changes_nothing(self):
        before = self.path.read_bytes()

        def fn(text):
            raise KeyError("boom")
        with self.assertRaises(KeyError):
            tracker.update(self.path, fn, self.far())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.temps(), [])
        # and the lock was let go
        self.assertEqual(tracker.update(self.path, lambda t: None, time.monotonic() + 0.2),
                         "done (no change)")

    def test_a_naive_when_through_update_leaves_the_file_untouched(self):
        self.path.write_text("## Open blockers\n" + LINE + "\n")
        before = self.path.read_bytes()
        naive = datetime(2026, 9, 18, 12, 7)

        def fn(text):
            return text.replace(LINE, tracker.mark_cleared(LINE, naive))
        with self.assertRaises(ValueError):
            tracker.update(self.path, fn, self.far())
        self.assertEqual(self.path.read_bytes(), before)


class AddLine(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="boss-tracker-add-"))
        self.path = self.dir / "t.md"
        self.path.write_text("# T\n\n## Open blockers\n- one\n\n## Decisions in force\n- d\n")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def add(self, line="- two [x1]", tag="[x1]", title="Open blockers"):
        return tracker.add_line(self.path, title, line, tag, time.monotonic() + 5)

    def test_adds_under_the_section_before_the_blank_line(self):
        self.assertEqual(self.add(), "done")
        self.assertIn("- one\n- two [x1]\n\n## Decisions", self.path.read_text())

    def test_the_same_tag_twice_is_one_line(self):
        self.assertEqual(self.add(), "done")
        self.assertEqual(self.add(), "done (already there)")
        self.assertEqual(self.path.read_text().count("[x1]"), 1)

    def test_a_missing_section_is_created(self):
        self.assertEqual(self.add(title="Pending"), "done")
        self.assertTrue(self.path.read_text().endswith("\n## Pending\n- two [x1]\n"))

    def test_an_empty_tag_is_refused(self):
        with self.assertRaises(ValueError):
            self.add(tag="")

    def test_a_file_that_is_not_utf8_is_a_failure_not_a_raise(self):
        self.path.write_bytes(b"# T\n\xff\n")
        self.assertEqual(self.add(), "failed: UnicodeDecodeError")
        self.assertEqual(self.path.read_bytes(), b"# T\n\xff\n")

    def test_failures_come_back_as_text(self):
        self.assertEqual(tracker.add_line(self.dir / "no.md", "T", "- l", "t", time.monotonic() + 1),
                         "failed: FileNotFoundError")


ADD_ONE = """
import sys, time
sys.path.insert(0, sys.argv[1])
import tracker
print(tracker.add_line(sys.argv[2], "Open blockers", "- the one [ladder id=ab12cd34]",
                       "id=ab12cd34", time.monotonic() + 60))
"""


class Concurrent(unittest.TestCase):
    """Eight processes add one tag while boss-tracker append writers run beside them."""

    def setUp(self):
        self.sb = Sandbox(extra_tools=("flock", "stat"))
        real_stat = shutil.which("stat")
        # A stub in front of the real stat: boss-tracker append calls it once per append,
        # so the test can prove the writers it counts on really ran.
        self.sb.stub_script("stat", 'exec %s "$@"' % real_stat)
        self.pm = self.sb.cfg / "pm"
        self.pm.mkdir()
        self.path = self.pm / "demo.md"
        self.path.write_text("# T\n\n## Open blockers\n\n## Decisions in force\n- d\n")

    def tearDown(self):
        self.sb.cleanup()

    def test_one_line_and_no_append_lost(self):
        adders = [subprocess.Popen(["python3", "-I", "-c", ADD_ONE, str(HERE), str(self.path)],
                                   env=self.sb.env, stdout=subprocess.PIPE, text=True)
                  for _ in range(8)]
        appenders = []
        for i in range(12):
            p = subprocess.Popen([str(BIN / "boss-tracker"), "append", "demo"], env=self.sb.env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            p.stdin.write("- appended %d\n" % i)
            p.stdin.close()
            appenders.append(p)
        results = []
        for p in adders:
            results.append(p.communicate(timeout=60)[0].strip())
        for p in appenders:
            p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0)
        self.assertEqual(sorted(results), ["done"] + ["done (already there)"] * 7)
        text = self.path.read_text()
        self.assertEqual(text.count("id=ab12cd34"), 1)
        for i in range(12):
            self.assertEqual(text.count("- appended %d\n" % i), 1, i)
        self.assertEqual(len(self.sb.calls_of("stat")), 12)
        self.assertEqual(sorted(p.name for p in self.pm.glob(".boss-tracker-*")), [])
        for name in ("codex", "claude", "gh", "tmux"):
            self.assertEqual(self.sb.calls_of(name), [])


class LadderReadsTheObjective(unittest.TestCase):
    def setUp(self):
        self.pm = Path(tempfile.mkdtemp(prefix="boss-tracker-pm-"))

    def tearDown(self):
        shutil.rmtree(self.pm)

    def test_a_met_track_with_a_stale_open_copy_is_closed(self):
        # The ladder looked for `_Status: OPEN_` anywhere in the file, so
        # example-fund, tray-indicator-state and ai-consultancy still counted
        # as open on 2026-10-02, and a marker there would have kept escalating.
        sys.path.insert(0, str(HERE.parent.parent / "routines"))
        import boss_ladder_core
        (self.pm / "t.md").write_text("## Open blockers\n")
        (self.pm / "t.goal.md").write_text("# Objective — t\n_Status: MET 2026-10-01 — done_\n"
                                           "# Objective — t\n_Status: OPEN_\n")
        self.assertEqual(list(boss_ladder_core.open_tracks(self.pm)),
                         [("t", self.pm / "t.md", "goal not OPEN")])


class BashTools(unittest.TestCase):
    """bin/boss-tracker writes this format in bash."""

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="boss-tracker-cfg-"))
        self.env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), HOME=str(self.cfg))
        self.pm = self.cfg / "pm"

    def tearDown(self):
        shutil.rmtree(self.cfg)

    def run_tool(self, *args, stdin=""):
        out = subprocess.run([str(BIN / args[0]), *args[1:]], input=stdin, env=self.env,
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def test_the_tracker_template_has_an_empty_blockers_section(self):
        self.run_tool("boss-tracker", "init", "demo", "Boss")
        lines = (self.pm / "demo.md").read_text().splitlines()
        lo, hi = tracker.blockers_range(lines)
        self.assertGreater(hi, 0)
        self.assertEqual([ln for ln in lines[lo:hi] if ln.strip()], [])


if __name__ == "__main__":
    unittest.main()
