#!/usr/bin/env python3
"""Tests for tracker.py, and for the bash tools that write the same formats.

Run: python3 -m pytest skills/boss/test_tracker.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tracker  # noqa: E402
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


class GoalStatus(unittest.TestCase):
    def test_the_first_status_line_wins(self):
        body = ("# Objective — t\n_Status: MET 2026-10-01 — done_\n"
                "# Objective — t\n_Status: OPEN_\n")
        self.assertEqual(tracker.goal_status(body), "MET 2026-10-01 — DONE")
        self.assertFalse(tracker.goal_open(body))

    def test_open_with_or_without_a_note(self):
        self.assertTrue(tracker.goal_open("# O\n_Status: OPEN_\n"))
        self.assertTrue(tracker.goal_open("# O\n_Status: open — reopened_\n"))

    def test_a_broken_first_status_is_not_rescued_by_a_stale_copy(self):
        # Codex on PR #10: matching the first *well-formed* line let line 4 win.
        body = "# O\n_Status: MET 2026-10-01 — done\n# O\n_Status: OPEN_\n"
        self.assertEqual(tracker.goal_status(body), "")
        self.assertFalse(tracker.goal_open(body))

    def test_prose_mentioning_the_status_is_not_one(self):
        self.assertFalse(tracker.goal_open("# O\n_Status: PAUSED — x_\nwrite `_Status: OPEN_` to resume\n"))
        self.assertEqual(tracker.goal_status("# O\nno status\n"), "")


class LadderReadsTheObjective(unittest.TestCase):
    def setUp(self):
        self.pm = Path(tempfile.mkdtemp(prefix="boss-tracker-pm-"))

    def tearDown(self):
        shutil.rmtree(self.pm)

    def test_a_met_track_with_a_stale_open_copy_is_closed(self):
        # The ladder looked for `_Status: OPEN_` anywhere in the file, so
        # purpleshares, tray-indicator-state and ai-consultancy still counted
        # as open on 2026-10-02, and a marker there would have kept escalating.
        sys.path.insert(0, str(HERE.parent.parent / "routines"))
        import boss_ladder_core
        (self.pm / "t.md").write_text("## Open blockers\n")
        (self.pm / "t.goal.md").write_text("# Objective — t\n_Status: MET 2026-10-01 — done_\n"
                                           "# Objective — t\n_Status: OPEN_\n")
        self.assertEqual(list(boss_ladder_core.open_tracks(self.pm)),
                         [("t", self.pm / "t.md", "goal not OPEN")])


class BashTools(unittest.TestCase):
    """bin/boss-tracker and bin/boss-goal write these formats in bash."""

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

    def test_status_written_by_boss_goal_is_read_back(self):
        self.run_tool("boss-goal", "init", "demo")
        goal = self.pm / "demo.goal.md"
        self.assertEqual(tracker.goal_status(goal.read_text()), "OPEN")
        self.run_tool("boss-goal", "status", "demo", "paused", "waiting on the owner")
        self.assertTrue(tracker.goal_status(goal.read_text()).startswith("PAUSED — WAITING ON THE OWNER"))
        self.run_tool("boss-goal", "status", "demo", "met", "PR merged")
        self.assertFalse(tracker.goal_open(goal.read_text()))

    def test_set_with_the_header_on_stdin_keeps_one_status(self):
        # What happened to six objectives before 2026-10-02: the body came from
        # `show`, header included, and `set` kept both.
        self.run_tool("boss-goal", "init", "demo")
        goal = self.pm / "demo.goal.md"
        shown = self.run_tool("boss-goal", "show", "demo").stdout
        out = self.run_tool("boss-goal", "set", "demo", stdin=shown.replace("<REPLACE", "<FILLED"))
        self.assertIn("dropped the header", out.stderr)
        body = goal.read_text()
        self.assertEqual(body.count("_Status:"), 1, body)
        self.assertEqual(body.count("# Objective"), 1, body)
        self.assertIn("<FILLED", body)
        self.run_tool("boss-goal", "status", "demo", "met", "done")
        self.assertFalse(tracker.goal_open(goal.read_text()))

    def test_boss_goal_reads_the_status_the_module_reads(self):
        # boss-goal list and check read line 2 with sed; the module reads the
        # first _Status: line. The same file must give the same answer.
        self.run_tool("boss-goal", "init", "demo")
        goal = self.pm / "demo.goal.md"
        for args in (("paused", "waiting on the owner"), ("met", "PR merged"), ("open",)):
            self.run_tool("boss-goal", "status", "demo", *args)
            listed = self.run_tool("boss-goal", "list").stdout.split(None, 1)[1].strip()
            self.assertEqual(listed.upper(), tracker.goal_status(goal.read_text()), args)

    def test_set_keeps_a_body_heading_and_skips_leading_blanks(self):
        self.run_tool("boss-goal", "init", "demo")
        goal = self.pm / "demo.goal.md"
        self.run_tool("boss-goal", "set", "demo", stdin="# Objectives and constraints\nx\n")
        self.assertIn("# Objectives and constraints", goal.read_text())
        self.run_tool("boss-goal", "set", "demo",
                      stdin="\n# Objective — demo\n_Status: OPEN_\n## Outcome\ny\n")
        self.assertEqual(goal.read_text().count("_Status:"), 1)

    def test_set_without_a_header_is_left_alone(self):
        self.run_tool("boss-goal", "init", "demo")
        out = self.run_tool("boss-goal", "set", "demo", stdin="## Outcome\nx\n")
        self.assertNotIn("dropped", out.stderr)
        self.assertEqual((self.pm / "demo.goal.md").read_text(),
                         "# Objective — demo\n_Status: OPEN_\n## Outcome\nx\n")


if __name__ == "__main__":
    unittest.main()
