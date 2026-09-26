#!/usr/bin/env python3
"""Tests for boss-reap.py — marker and state lifecycle.

Run: python3 skills/boss/test_boss_reap.py

This is the one boss script that deletes things, so most of these tests are
about what it must NOT touch. `pm/.pulse/` holds jev.mode beside the per-session
files: reaping that would silently re-arm jev.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REAP = Path(__file__).resolve().parent / "boss-reap.py"
LIVE = "11111111-1111-1111-1111-111111111111"
DEAD = "22222222-2222-2222-2222-222222222222"


class ReapCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-reap-test-"))
        self.markers = self.tmp / "pm" / ".boss-sessions"
        self.pulse = self.tmp / "pm" / ".pulse"
        self.sessions = self.tmp / "sessions"
        for d in (self.markers, self.pulse, self.sessions):
            d.mkdir(parents=True)
        # one live session -- this test process, start time and all -- and one
        # long gone
        stat = Path("/proc/%d/stat" % os.getpid()).read_text()
        (self.sessions / ("%d.json" % os.getpid())).write_text(json.dumps(
            {"sessionId": LIVE, "pid": os.getpid(), "status": "idle",
             "entrypoint": "sdk-cli",
             "procStart": stat[stat.rindex(")") + 2:].split()[19]}))
        for sid in (LIVE, DEAD):
            (self.markers / sid).write_text("demo\n")
            for name in ("%s.json", "%s.guard.json", "jev-%s.json", "jev-%s.lock"):
                (self.pulse / (name % sid)).write_text("{}")
        # the files that must survive anything
        (self.pulse / "jev.mode").write_text("advisory\n")
        (self.pulse / "jev.log").write_text("a log line\n")
        (self.pulse / "jev.mode.bak-2026-09-20").write_text("armed\n")
        self.age_everything(hours=48)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def age_everything(self, hours):
        old = time.time() - hours * 3600
        for d in (self.markers, self.pulse):
            for p in d.iterdir():
                os.utime(p, (old, old))

    def run_reap(self, *args, session_id=None):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        payload = json.dumps({"session_id": session_id or "",
                              "hook_event_name": "SessionEnd"})
        res = subprocess.run([sys.executable, str(REAP), *args], input=payload,
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def names(self, d):
        return sorted(p.name for p in d.iterdir())


class SessionEnd(ReapCase):

    def test_a_session_ending_takes_its_own_files_with_it(self):
        self.run_reap(session_id=DEAD)
        self.assertNotIn(DEAD, self.names(self.markers))
        self.assertFalse([n for n in self.names(self.pulse) if DEAD in n])

    def test_it_touches_nobody_elses(self):
        self.run_reap(session_id=DEAD)
        self.assertIn(LIVE, self.names(self.markers))
        self.assertEqual(4, len([n for n in self.names(self.pulse) if LIVE in n]))


class Sweep(ReapCase):

    def test_sweep_removes_what_has_no_session_left(self):
        self.run_reap("--sweep")
        self.assertEqual([LIVE], self.names(self.markers))
        self.assertFalse([n for n in self.names(self.pulse) if DEAD in n])

    def test_sweep_keeps_the_live_one(self):
        self.run_reap("--sweep")
        self.assertEqual(4, len([n for n in self.names(self.pulse) if LIVE in n]))

    def test_sweep_reaps_a_session_whose_file_outlived_it(self):
        # Claude Code does not always remove the peer file. A file whose
        # process is gone is no session.
        (self.sessions / "4000000.json").write_text(json.dumps(
            {"sessionId": DEAD, "pid": 4000000, "status": "idle", "procStart": "1"}))
        self.run_reap("--sweep")
        self.assertFalse((self.markers / DEAD).exists())
        self.assertTrue((self.markers / LIVE).exists())

    def test_sweep_never_touches_jev_mode(self):
        """Deleting this silently re-arms jev. It has no session id in its name."""
        self.run_reap("--sweep")
        for keep in ("jev.mode", "jev.log", "jev.mode.bak-2026-09-20"):
            self.assertIn(keep, self.names(self.pulse))
        self.assertEqual("advisory\n", (self.pulse / "jev.mode").read_text())

    def test_sweep_spares_anything_recent(self):
        """A session that just started has no registry file yet."""
        self.age_everything(hours=0)
        self.run_reap("--sweep")
        self.assertIn(DEAD, self.names(self.markers))

    def test_dry_run_deletes_nothing(self):
        before = (self.names(self.markers), self.names(self.pulse))
        out = self.run_reap("--sweep", "--dry-run")
        self.assertEqual(before, (self.names(self.markers), self.names(self.pulse)))
        self.assertIn(DEAD, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
