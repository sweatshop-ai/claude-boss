#!/usr/bin/env python3
"""Tests for boss_store.py and bin/boss-marker — the boss marker, one rule.

Run: python3 skills/boss/test_boss_store.py

`pm/.boss-sessions/<session_id>` says a session is a boss, and its first line
names the track. Every hook reads it through boss_store; the boss writes it
through `boss-marker register`.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_store  # noqa: E402

MARKER = HERE.parent.parent / "bin" / "boss-marker"
SID = "11111111-1111-1111-1111-111111111111"


class Store(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.markers = self.cfg / "pm" / ".boss-sessions"

    def cli(self, *args, sid=SID):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), CLAUDE_CODE_SESSION_ID=sid)
        return subprocess.run([str(MARKER), *args], env=env, capture_output=True, text=True)

    def test_register_makes_a_boss_and_names_its_track(self):
        out = self.cli("register", "lead-engine")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(boss_store.is_boss(SID, self.cfg))
        self.assertEqual(boss_store.track_of(SID, self.cfg), "lead-engine")

    def test_register_without_a_track_is_a_boss_with_no_track_yet(self):
        self.cli("register")
        self.assertTrue(boss_store.is_boss(SID, self.cfg))
        self.assertEqual(boss_store.track_of(SID, self.cfg), "")

    def test_a_track_that_is_not_a_plain_name_is_refused(self):
        # The track becomes a file name under pm/.
        for bad in ("../etc", "Lead Engine", ".hidden", "a/b", "x" * 65):
            out = self.cli("register", bad)
            self.assertNotEqual(out.returncode, 0, bad)
        self.assertFalse(boss_store.is_boss(SID, self.cfg))

    def test_a_marker_written_by_hand_with_a_bad_track_has_no_track(self):
        self.markers.mkdir(parents=True)
        (self.markers / SID).write_text("../../settings\n")
        self.assertTrue(boss_store.is_boss(SID, self.cfg))
        self.assertEqual(boss_store.track_of(SID, self.cfg), "")

    def test_a_symlink_or_a_directory_is_not_a_marker(self):
        self.markers.mkdir(parents=True)
        (self.markers / SID).symlink_to(self.cfg / "elsewhere")
        (self.cfg / "elsewhere").write_text("lead-engine\n")
        self.assertFalse(boss_store.is_boss(SID, self.cfg))
        other = "22222222-2222-2222-2222-222222222222"
        (self.markers / other).mkdir()
        self.assertFalse(boss_store.is_boss(other, self.cfg))

    def test_a_session_id_that_is_not_one_is_never_a_boss(self):
        self.assertFalse(boss_store.is_boss("../x", self.cfg))
        self.assertFalse(boss_store.is_boss("", self.cfg))

    def test_register_needs_the_session_id(self):
        out = self.cli("register", "lead-engine", sid="")
        self.assertNotEqual(out.returncode, 0)


class TrackFiles(unittest.TestCase):
    """The two files of a track: named and read by the store, never interpreted."""

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.pm = self.cfg / "pm"
        self.pm.mkdir()

    def test_the_paths_are_named_by_the_track(self):
        self.assertEqual(boss_store.objective_path("demo", self.cfg), self.pm / "demo.goal.md")
        self.assertEqual(boss_store.tracker_path("demo", self.cfg), self.pm / "demo.md")

    def test_no_path_is_built_for_a_bad_track_name(self):
        for bad in ("", "../evil", "a/b", "A", ".hidden", "x" * 65, None):
            self.assertIsNone(boss_store.objective_path(bad, self.cfg), repr(bad))
            self.assertIsNone(boss_store.tracker_path(bad, self.cfg), repr(bad))
            self.assertIsNone(boss_store.read_objective(bad, self.cfg), repr(bad))
            self.assertIsNone(boss_store.read_tracker(bad, self.cfg), repr(bad))

    def test_reads_return_the_text_as_written(self):
        (self.pm / "demo.goal.md").write_text("_Status: OPEN_\n", encoding="utf-8")
        (self.pm / "demo.md").write_text("# T \u2014 caf\u00e9\n", encoding="utf-8")
        self.assertEqual(boss_store.read_objective("demo", self.cfg), "_Status: OPEN_\n")
        self.assertEqual(boss_store.read_tracker("demo", self.cfg), "# T \u2014 caf\u00e9\n")

    def test_an_empty_file_is_empty_text_not_missing(self):
        (self.pm / "demo.md").write_text("")
        self.assertEqual(boss_store.read_tracker("demo", self.cfg), "")

    def test_a_missing_file_is_none(self):
        self.assertIsNone(boss_store.read_objective("demo", self.cfg))
        self.assertIsNone(boss_store.read_tracker("demo", self.cfg))

    def test_an_unreadable_file_is_none(self):
        (self.pm / "demo.goal.md").mkdir()          # a directory: open() fails with OSError
        self.assertIsNone(boss_store.read_objective("demo", self.cfg))
        f = self.pm / "demo.md"
        f.write_text("x")
        f.chmod(0)
        try:
            if os.access(f, os.R_OK):
                self.skipTest("running as a user who reads mode 000")
            self.assertIsNone(boss_store.read_tracker("demo", self.cfg))
        finally:
            f.chmod(0o600)

    def test_a_symlink_is_followed_as_today(self):
        real = self.cfg / "elsewhere.md"
        real.write_text("linked")
        (self.pm / "demo.md").symlink_to(real)
        self.assertEqual(boss_store.read_tracker("demo", self.cfg), "linked")

    def test_the_directory_follows_the_environment_at_call_time(self):
        (self.pm / "demo.md").write_text("here")
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.cfg)
        try:
            self.assertEqual(boss_store.read_tracker("demo"), "here")
        finally:
            if old is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
