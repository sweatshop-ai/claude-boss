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

    def test_an_empty_cleared_is_not_cleared_and_gets_the_time(self):
        for empty in ('cleared=', 'cleared=""'):
            with self.subTest(empty):
                line = LINE.replace(' ask=', ' %s ask=' % empty)
                self.assertEqual(validate(scan_marker(line)[1])["cleared"], "")
                out = tracker.mark_cleared(line, WHEN)
                self.assertEqual(out, LINE.replace(' ask=', ' cleared=2026-09-18T12:07+02:00 ask='))
                self.assertEqual(validate(scan_marker(out)[1])["cleared"], "2026-09-18T12:07+02:00")


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

    def test_an_exception_from_fn_keeps_its_cause(self):
        inner = ValueError("inner")
        def fn(text):
            try:
                raise inner
            except ValueError as err:
                raise OSError("outer") from err
        with self.assertRaises(OSError) as got:
            tracker.update(self.path, fn, self.far())
        self.assertIs(got.exception.__cause__, inner)
        def fn2(text):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "x") from None
        with self.assertRaises(UnicodeDecodeError) as got2:
            tracker.update(self.path, fn2, self.far())
        self.assertIsNone(got2.exception.__cause__)
        self.assertTrue(got2.exception.__suppress_context__)

    def test_an_oserror_or_decode_error_from_fn_propagates_and_changes_nothing(self):
        before = self.path.read_bytes()
        for exc in (OSError("from fn"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "from fn")):
            def fn(text, exc=exc):
                raise exc
            with self.subTest(type(exc).__name__):
                with self.assertRaises(type(exc)):
                    tracker.update(self.path, fn, self.far())
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.temps(), [])
                self.assertEqual(tracker.update(self.path, lambda t: None, time.monotonic() + 0.2),
                                 "done (no change)")

    def test_a_change_of_inode_alone_is_noticed(self):
        calls = []

        def fn(text):
            calls.append(text)
            if len(calls) == 1:
                st = self.path.stat()
                other = self.dir / "other.md"
                other.write_bytes(self.path.read_bytes().replace(b"one", b"two"))
                os.utime(other, ns=(st.st_atime_ns, st.st_mtime_ns))
                os.replace(other, self.path)
                new = self.path.stat()
                assert (new.st_size, new.st_mtime_ns) == (st.st_size, st.st_mtime_ns)
                assert new.st_ino != st.st_ino
            return text + "- mine\n"
        self.assertEqual(tracker.update(self.path, fn, self.far()), "done")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.path.read_text(), "# T\n\n## Open blockers\n- two\n- mine\n")

    def test_the_text_is_utf8_whatever_the_locale(self):
        self.path.write_bytes("# T\n\n## Open blockers\n- caf\u00e9\n".encode())
        code = ("import sys, time\nsys.path.insert(0, sys.argv[1])\nimport tracker\n"
                "print(tracker.update(sys.argv[2], lambda t: t + '- na\\u00efve\\n', time.monotonic() + 5))\n")
        env = {"PATH": os.environ["PATH"], "LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
        out = subprocess.run([sys.executable, "-c", code, str(HERE), str(self.path)], env=env,
                             cwd=str(self.dir), capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "done", out.stderr)
        self.assertEqual(self.path.read_bytes(),
                         "# T\n\n## Open blockers\n- caf\u00e9\n- na\u00efve\n".encode())

    def test_a_symlinked_tracker_is_not_followed(self):
        real = self.dir / "real.md"
        real.write_text("# real\n\n## Open blockers\n")
        self.path.unlink()
        self.path.symlink_to(real)
        calls = []
        got = tracker.update(self.path, lambda t: calls.append(t) or t + "- x\n", self.far())
        self.assertEqual(got, "failed: the tracker is a symbolic link")
        self.assertEqual((calls, real.read_text(), self.path.is_symlink(), self.temps()),
                         ([], "# real\n\n## Open blockers\n", True, []))

    def test_a_symlink_swapped_in_during_the_pass_is_not_written_through(self):
        real = self.dir / "real.md"
        real.write_text("# real\n\n## Open blockers\n")
        calls = []

        def fn(text):
            calls.append(text)
            if len(calls) == 1:
                link = self.dir / "link.md"
                link.symlink_to(real)
                os.replace(link, self.path)
            return text + "- mine\n"
        got = tracker.update(self.path, fn, self.far())
        self.assertEqual(got, "failed: the tracker is a symbolic link")
        self.assertEqual((len(calls), real.read_text(), self.temps()), (1, "# real\n\n## Open blockers\n", []))

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

    def test_a_tag_that_is_the_prefix_of_a_longer_id_is_not_there(self):
        self.assertEqual(self.add("- a id=ab12cd345", "id=ab12cd345"), "done")
        self.assertEqual(self.add("- b id=ab12cd34", "id=ab12cd34"), "done")
        self.assertEqual(self.add("- b again id=ab12cd34", "id=ab12cd34"), "done (already there)")
        self.assertEqual(self.path.read_text().count("id=ab12cd34\n"), 1)

    def test_a_tag_in_prose_or_another_section_is_not_there(self):
        self.path.write_text("# T\n\nnote: [x1] is how a blocker is tagged\n\n## Open blockers\n- one\n\n"
                             "## Decisions in force\n- d [x1]\n")
        self.assertEqual(self.add(), "done")
        self.assertIn("- one\n- two [x1]\n\n## Decisions", self.path.read_text())
        self.assertEqual(self.add(), "done (already there)")

    def test_a_cleared_marker_does_not_count_as_there(self):
        tracker_line = ('- b [ladder id=ab12cd34 t0=2026-09-18T10:53+02:00 last=0 '
                        'next=2026-09-18T10:58+02:00 %sask="x"]')
        tag = tracker.marker_tag("ab12cd34")
        cleared = tracker_line % "cleared=2026-09-18T11:00+02:00 "
        self.path.write_text("## Open blockers\n%s\n" % cleared)
        self.assertEqual(self.add(tracker_line % "", tag), "done")
        self.assertEqual(self.add(tracker_line % "", tag), "done (already there)")
        self.assertEqual(self.path.read_text().count("id=ab12cd34 "), 2)
        # an empty cleared= is not cleared (validate says so too)
        self.path.write_text("## Open blockers\n%s\n" % (tracker_line % "cleared= "))
        self.assertEqual(self.add(tracker_line % "", tag), "done (already there)")

    def test_a_crlf_tracker_gets_a_crlf_line(self):
        self.path.write_bytes(b"# T\r\n\r\n## Open blockers\r\n- one\r\n\r\n## Decisions in force\r\n- d\r\n")
        self.assertEqual(self.add(), "done")
        self.assertEqual(self.path.read_bytes(), b"# T\r\n\r\n## Open blockers\r\n- one\r\n- two [x1]\r\n"
                         b"\r\n## Decisions in force\r\n- d\r\n")
        self.assertEqual(self.add(title="Pending", line="- p [p1]", tag="[p1]"), "done")
        self.assertTrue(self.path.read_bytes().endswith(b"- d\r\n\r\n## Pending\r\n- p [p1]\r\n"))
        self.assertNotIn(b"\n", self.path.read_bytes().replace(b"\r\n", b""))

    def test_marker_tag_is_not_found_in_prose_and_a_bare_tag_is_found_in_any_line(self):
        # Ticket 28: the tag is the caller's. A caller that wants "a marker with this id" passes
        # marker_tag(id), which holds the token, so a note that only says the id is not "there";
        # a caller that passes a bare tag gets "any line of the section holding it".
        marker = ('- b [ladder id=ab12cd34 t0=2026-09-18T10:53+02:00 last=0 '
                  'next=2026-09-18T10:58+02:00 ask="x"]')
        self.path.write_text("## Open blockers\n- resolved id=ab12cd34, see PR 90\n")
        self.assertEqual(self.add(marker, tracker.marker_tag("ab12cd34")), "done")
        self.assertEqual(self.add(marker, tracker.marker_tag("ab12cd34")), "done (already there)")
        self.assertEqual(self.path.read_text().count("[ladder id=ab12cd34 "), 1)
        self.path.write_text("## Open blockers\n- resolved id=ab12cd34, see PR 90\n")
        self.assertEqual(self.add("- new id=ab12cd34", "id=ab12cd34"), "done (already there)")

    def test_a_malformed_marker_holding_the_tag_is_there(self):
        # Fail safe: a hand-damaged marker is not a reason to add a second line beside it.
        broken = "- b [ladder id=ab12cd34 t0=garbage"
        self.path.write_text("## Open blockers\n%s\n" % broken)
        self.assertEqual(self.add("- n", tracker.marker_tag("ab12cd34")), "done (already there)")

    def test_a_non_ascii_edge_of_the_tag_gets_no_word_boundary(self):
        # The boundary class is ASCII; an edge that is a non-ASCII letter must not switch it on.
        self.path.write_text("## Open blockers\n- xé1\n")
        self.assertEqual(self.add("- e1", "é1"), "done (already there)")
        self.path.write_text("## Open blockers\n- xa1\n")
        self.assertEqual(self.add("- a1", "a1"), "done")
        self.assertEqual(self.add("- é", "é"), "done")
        self.assertEqual(self.add("- é", "é"), "done (already there)")

    def test_a_crlf_file_without_a_final_newline_keeps_one_ending(self):
        self.path.write_bytes(b"## Open blockers\r\n- a")
        self.assertEqual(self.add(), "done")
        self.assertEqual(self.path.read_bytes(), b"## Open blockers\r\n- a\r\n- two [x1]")
        self.assertNotIn(b"\n", self.path.read_bytes().replace(b"\r\n", b""))
        self.assertEqual(tracker.insert_in_section("## Open blockers\r\n- a", "Open blockers", "new"),
                         "## Open blockers\r\n- a\r\nnew")

    def test_an_lf_file_without_a_final_newline_is_unchanged(self):
        self.assertEqual(tracker.insert_in_section("## Open blockers\n- a", "Open blockers", "new"),
                         "## Open blockers\n- a\nnew")

    def test_failures_come_back_as_text(self):
        self.assertEqual(tracker.add_line(self.dir / "no.md", "T", "- l", "t", time.monotonic() + 1),
                         "failed: FileNotFoundError")


ADD_ONE = """
import sys, time
sys.path.insert(0, sys.argv[1])
import tracker
tag = sys.argv[3] if len(sys.argv) > 3 else "ab12cd34"
print(tracker.add_line(sys.argv[2], "Open blockers", "- the one [ladder id=%s]" % tag,
                       "id=%s]" % tag, time.monotonic() + 60))
"""


class Concurrent(unittest.TestCase):
    """Eight processes add one tag, then twelve add a tag each, while boss-tracker append writers run beside them."""

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

    def adders(self, tags):
        return [subprocess.Popen(["python3", "-I", "-c", ADD_ONE, str(HERE), str(self.path), tag],
                                 env=self.sb.env, stdout=subprocess.PIPE, text=True)
                for tag in tags]

    def test_every_adder_with_its_own_tag_keeps_its_line(self):
        # Every adder renames, so without the lock the last rename would drop the others' lines.
        tags = ["ab12cd%02d" % i for i in range(12)]
        results = [p.communicate(timeout=60)[0].strip() for p in self.adders(tags)]
        self.assertEqual(results, ["done"] * 12)
        text = self.path.read_text()
        for tag in tags:
            self.assertEqual(text.count("id=%s]" % tag), 1, tag)

    def test_one_line_and_no_append_lost(self):
        adders = self.adders(["ab12cd34"] * 8)
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


NON_UTF8 = {"LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
ROUTINES = HERE.parent.parent / "routines"


def under_c_locale(code: str, *args: str) -> subprocess.CompletedProcess:
    """`code` in a child whose default text encoding is ASCII (locale C, coercion and UTF-8 mode off)."""
    env = {**os.environ, **NON_UTF8}
    return subprocess.run([sys.executable, "-X", "utf8=0", "-c", code, *args], env=env,
                          capture_output=True, text=True, timeout=60)


class ReadersPinUtf8(unittest.TestCase):
    """Ticket 28: `tracker.update` reads and writes UTF-8, so every other reader and writer of a tracker must
    too, or a non-UTF-8 locale makes the ladder rewrite the file in that encoding and every later `update`
    fail with UnicodeDecodeError."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="boss-tracker-utf8-"))
        probe = under_c_locale("import locale; print(locale.getpreferredencoding(False))")
        if probe.stdout.strip().lower().replace("-", "") in ("utf8", "utf8"):
            self.skipTest("this interpreter cannot be made to default to a non-UTF-8 encoding")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_the_provisional_readers_of_boss_review_read_utf8(self):
        entry = "- [prov owner/repo#7] head=%s round=01 base=main at=2026-11-12T10:00:00Z" % ("a" * 40)
        path = self.dir / "t.md"
        path.write_bytes(("## Open blockers\n- caf\u00e9\n\n## Provisional GO\n%s\n" % entry).encode())
        code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); import boss_review as br\n"
                "p = pathlib.Path(sys.argv[2])\n"
                "e = br._entry_of(%r)\n"
                "print('listed', br._listed(p, e))\n"
                "br.codex_blocker.usable_tracker = lambda track: p\n"
                "print('pruned', br.prune_provisional('t', 'other/repo'))\n" % entry)
        got = under_c_locale(code, str(HERE), str(path))
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("listed True", got.stdout)
        self.assertNotIn("cannot be read", got.stderr)

    def test_the_ladder_reads_and_writes_utf8(self):
        t0 = "2026-09-18T10:00+02:00"
        body = ('## Open blockers\n- note \u2014 caf\u00e9\n'
                '- b [ladder id=u123 t0=%s last=0 next=2026-09-18T10:05+02:00 ask="sign in"]\n' % t0)
        (self.dir / "ut.goal.md").write_bytes("# Objective \u2014 ut\n_Status: OPEN_\n".encode())
        tracker_file = self.dir / "ut.md"
        tracker_file.write_bytes(body.encode())
        alert = self.dir / "alert"
        alert.write_text("#!/bin/sh\nexit 0\n")
        alert.chmod(0o755)
        code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); import boss_ladder_core as c\n"
                "from datetime import datetime, timedelta, timezone\n"
                "d = pathlib.Path(sys.argv[2])\n"
                "c.PM_DIR, c.STATE, c.BOSS_ALERT, c.DRY_RUN = d, d / 'state.json', sys.argv[3], False\n"
                "c.post = lambda rung, text: True  # the alert text is not under test, and has a dash\n"
                "c.run(datetime(2026, 9, 18, 10, 20, tzinfo=timezone(timedelta(hours=2))))\n")
        got = under_c_locale(code, str(ROUTINES), str(self.dir), str(alert))
        self.assertEqual(got.returncode, 0, got.stderr)
        after = tracker_file.read_bytes().decode("utf-8")
        self.assertIn("caf\u00e9", after)
        self.assertIn("- note \u2014 caf\u00e9\n", after)
        self.assertIn("last=15", after)
        self.assertEqual(tracker.update(tracker_file, lambda t: None, time.monotonic() + 1),
                         "done (no change)")


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
