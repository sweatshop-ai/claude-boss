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

MARKER = HERE / "bin" / "boss-marker"
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


if __name__ == "__main__":
    unittest.main()
