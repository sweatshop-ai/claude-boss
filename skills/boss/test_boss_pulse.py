#!/usr/bin/env python3
"""Tests for boss-pulse.py, the Stop hook that keeps a boss working.

Run: python3 skills/boss/test_boss_pulse.py

The hook runs the way the harness runs it — as a process, JSON on stdin —
against a throwaway CLAUDE_CONFIG_DIR with no tmux and no live peers, so
`idle_workers()` returns empty without shelling out.
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

PULSE = Path(__file__).resolve().parent / "boss-pulse.py"
TRACK = "demo"


class PulseCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-pulse-test-"))
        for d in ("pm/.boss-sessions", "pm/.pulse", "sessions"):
            (self.tmp / d).mkdir(parents=True)
        self.sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        (self.tmp / "pm/.boss-sessions" / self.sid).write_text(TRACK + "\n")
        self.goal(open_=True)
        self.tracker(blockers="")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def goal(self, open_=True):
        (self.tmp / "pm" / (TRACK + ".goal.md")).write_text(
            "# Objective\n\n_Status: %s_\n\n## Outcome\nShip the thing.\n\n"
            "## Done when\n- [ ] it ships\n\n## Next, in priority order\n- do a thing\n"
            % ("OPEN" if open_ else "MET"), encoding="utf-8")

    def tracker(self, blockers=""):
        (self.tmp / "pm" / (TRACK + ".md")).write_text(
            "# Tracker\n\n## Roster\n| none |\n\n## Open blockers\n%s\n\n## Decisions\n- d\n"
            % blockers, encoding="utf-8")

    def register(self, status="busy", waiting_for=None):
        """This boss's own record in Claude Code's session registry."""
        rec = {"pid": os.getpid(), "sessionId": self.sid, "tmux": "9:@1.%901",
               "name": "Boss", "status": status, "cwd": str(self.tmp)}
        if waiting_for is not None:
            rec["waitingFor"] = waiting_for
        (self.tmp / "sessions" / (self.sid + ".json")).write_text(json.dumps(rec))

    def stop(self, sid=None):
        payload = {"session_id": sid or self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": False}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


class StuckBoss(PulseCase):
    """The failure to kill: the boss ends its turn while blocked, saying nothing."""

    def test_an_open_blocker_at_stop_makes_the_boss_ask(self):
        self.tracker(blockers="- waiting on the owner to pick the org")
        out = self.stop()
        self.assertIn("AskUserQuestion", out)
        self.assertIn("pick the org", out)

    def test_no_blocker_no_pulse(self):
        self.assertEqual(self.stop(), "",
                         "a boss with nothing open must stay silent")

    def test_a_boss_already_asking_is_not_pushed(self):
        """It is visibly waiting. Pushing it again would stack on the dialog."""
        self.tracker(blockers="- waiting on the owner to pick the org")
        self.register(status="waiting", waiting_for="input needed")
        self.assertEqual(self.stop(), "")

    def test_a_permission_prompt_also_counts_as_asking(self):
        self.tracker(blockers="- waiting on the owner to pick the org")
        self.register(status="busy", waiting_for="permission prompt")
        self.assertEqual(self.stop(), "")

    def test_three_blockers_still_produce_one_question(self):
        self.tracker(blockers="- pick the org\n- approve the spend\n- confirm the deploy")
        out = self.stop()
        self.assertIn("One question", out)
        self.assertIn("hold the rest", out)

    def test_a_met_objective_ends_the_pulse(self):
        self.tracker(blockers="- pick the org")
        self.goal(open_=False)
        self.assertEqual(self.stop(), "",
                         "a finished objective must not keep nagging")

    def test_a_stop_hook_already_blocking_is_left_alone(self):
        self.tracker(blockers="- pick the org")
        payload = {"session_id": self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": True}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.stdout.strip(), "")

    def test_background_work_still_running_is_not_a_stuck_boss(self):
        self.tracker(blockers="- pick the org")
        payload = {"session_id": self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": False,
                   "background_tasks": [{"status": "running"}]}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
