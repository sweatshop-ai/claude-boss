#!/usr/bin/env python3
"""Tests for objective.py — the one reader and writer of pm/<track>.goal.md.

Run: python3 skills/boss/test_objective.py
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import objective  # noqa: E402


class Status(unittest.TestCase):
    def test_the_first_status_line_counts_wherever_it_sits(self):
        body = "# Objective — t\n\nsome note\n_Status: PAUSED — away_\n"
        self.assertEqual(objective.status(body), "PAUSED — away")
        self.assertFalse(objective.is_open(body))

    def test_a_stale_second_header_does_not_count(self):
        body = ("# Objective — t\n_Status: MET 2026-10-01 — done_\n"
                "# Objective — t\n_Status: OPEN_\n")
        self.assertEqual(objective.status(body), "MET 2026-10-01 — done")
        self.assertFalse(objective.is_open(body))

    def test_open_with_or_without_a_note_in_any_case(self):
        self.assertTrue(objective.is_open("# O\n_Status: OPEN_\n"))
        self.assertTrue(objective.is_open("# O\n_Status: open — reopened_\n"))

    def test_a_broken_first_status_is_not_rescued_by_a_stale_copy(self):
        # Codex on PR #10: matching the first *well-formed* line let line 4 win.
        body = "# O\n_Status: MET 2026-10-01 — done\n# O\n_Status: OPEN_\n"
        self.assertEqual(objective.status(body), "")
        self.assertFalse(objective.is_open(body))

    def test_prose_mentioning_the_status_is_not_one(self):
        self.assertFalse(objective.is_open("# O\n_Status: PAUSED — x_\nwrite `_Status: OPEN_` to resume\n"))
        self.assertEqual(objective.status("# O\nno status\n"), "")


class SetStatus(unittest.TestCase):
    def test_rewrites_the_first_status_line_and_nothing_else(self):
        body = "# Objective — t\nkept note\n_Status: OPEN_\n## Outcome\nx\n_Status: OPEN_\n"
        self.assertEqual(objective.set_status(body, "MET 2026-10-25 — proof"),
                         "# Objective — t\nkept note\n_Status: MET 2026-10-25 — proof_\n"
                         "## Outcome\nx\n_Status: OPEN_\n")

    def test_with_no_status_line_one_goes_under_the_heading(self):
        body = "# Objective — t\n## Outcome\nx\n"
        self.assertEqual(objective.set_status(body, "OPEN"),
                         "# Objective — t\n_Status: OPEN_\n## Outcome\nx\n")

    def test_with_no_heading_either_it_goes_first(self):
        self.assertEqual(objective.set_status("## Outcome\nx\n", "OPEN"),
                         "_Status: OPEN_\n## Outcome\nx\n")


class WithBody(unittest.TestCase):
    def test_keeps_the_heading_and_the_status_wherever_it_was(self):
        old = "# Objective — t\nstray line\n_Status: PAUSED — away_\n## Outcome\nold\n"
        self.assertEqual(objective.with_body(old, "## Outcome\nnew\n"),
                         "# Objective — t\n_Status: PAUSED — away_\n## Outcome\nnew\n")

    def test_a_file_with_no_status_keeps_none(self):
        self.assertEqual(objective.with_body("# Objective — t\n## Outcome\nold\n", "## Outcome\nnew\n"),
                         "# Objective — t\n## Outcome\nnew\n")


GOAL = """# Objective — t
_Status: OPEN_

## Outcome
Ship it.

## Done when
- [x] built
- [ ] `gh pr view 3` says MERGED

## Tickets
`/w/.scratch/t/issues`

## Next, in priority order
1. first
- a bullet counts too

## Notes
3. not in Next
"""


class Sections(unittest.TestCase):
    def test_section_stops_at_the_next_heading(self):
        self.assertEqual(objective.section(GOAL, "Outcome"), "Ship it.")
        self.assertEqual(objective.section(GOAL, "Missing"), "")

    def test_the_ticket_source_is_the_first_line_without_backticks(self):
        self.assertEqual(objective.tickets_source(GOAL), "/w/.scratch/t/issues")
        self.assertEqual(objective.tickets_source("# O\n## Tickets\n\n## Next, in priority order\n1. x\n"), "")

    def test_next_is_every_line_of_its_own_section(self):
        self.assertEqual(objective.next_items(GOAL), ["1. first", "- a bullet counts too"])

    def test_the_queue_counts_items_not_their_continuation_lines(self):
        body = ("## Next, in priority order\n1. first,\n   wrapped\n- second\n"
                "  * nested detail\n2. third\n## Notes\n3. not in Next\n")
        self.assertEqual(objective.next_count(body), 3)
        self.assertEqual(objective.next_count(GOAL), 2)

    def test_unmet_is_the_unticked_criteria(self):
        self.assertEqual(objective.unmet(GOAL), ["`gh pr view 3` says MERGED"])


class CommandLine(unittest.TestCase):
    """What bin/boss-goal calls instead of its own sed and awk."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="objective-cli-"))
        self.f = self.dir / "t.goal.md"
        self.f.write_text("# Objective — t\nstray\n_Status: OPEN_\n" + GOAL.split("\n", 2)[2])

    def tearDown(self):
        for p in self.dir.iterdir():
            p.unlink()
        self.dir.rmdir()

    def call(self, *args, stdin=""):
        return subprocess.run([sys.executable, str(HERE / "objective.py"), *args],
                              input=stdin, capture_output=True, text=True, timeout=30)

    def test_reads_print_one_value(self):
        self.assertEqual(self.call("status", str(self.f)).stdout, "OPEN\n")
        self.assertEqual(self.call("tickets", str(self.f)).stdout, "/w/.scratch/t/issues\n")
        self.assertEqual(self.call("next-count", str(self.f)).stdout, "2\n")

    def test_set_status_rewrites_the_status_line_not_line_two(self):
        r = self.call("set-status", str(self.f), "PAUSED — away")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.f.read_text().splitlines()
        self.assertEqual(lines[1:3], ["stray", "_Status: PAUSED — away_"])
        self.assertEqual([p.name for p in self.dir.iterdir()], ["t.goal.md"])   # no temp file left

    def test_set_body_keeps_the_header_and_reads_stdin(self):
        r = self.call("set-body", str(self.f), stdin="## Outcome\nnew\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.f.read_text(), "# Objective — t\n_Status: OPEN_\n## Outcome\nnew\n")

    def test_a_missing_file_is_exit_one_and_a_bad_call_exit_two(self):
        r = self.call("status", str(self.dir / "nope.goal.md"))
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("nope.goal.md", r.stderr)
        self.assertEqual(self.call("frobnicate", str(self.f)).returncode, 2)
        self.assertEqual(self.call("set-status", str(self.f)).returncode, 2)
        self.assertFalse((self.dir / "nope.goal.md").exists())


if __name__ == "__main__":
    unittest.main()
