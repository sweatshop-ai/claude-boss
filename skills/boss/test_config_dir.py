#!/usr/bin/env python3
"""An empty CLAUDE_CONFIG_DIR means ~/.claude, in every hook.

Run: python3 skills/boss/test_config_dir.py

Claude Code can hand a hook `CLAUDE_CONFIG_DIR=""`. That is unset, and the
config directory is `$HOME/.claude`. Each hook runs here as a process, with the
variable empty, HOME in a scratch directory and the working directory somewhere
else, and has to find (or write) its files under `<HOME>/.claude/pm`. A hook
that read the empty string as a path looked under `./pm` and never fired.
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

HERE = Path(__file__).resolve().parent
LADDER = HERE.parent.parent / "routines" / "boss_ladder_core.py"
SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
DEAD = "22222222-2222-2222-2222-222222222222"
TRACK = "demo"


class EmptyConfigDir(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-config-dir-test-"))
        self.home = self.tmp / "home"
        self.cwd = self.tmp / "cwd"
        self.pm = self.home / ".claude" / "pm"
        for d in (self.pm / ".boss-sessions", self.pm / ".pulse",
                  self.home / ".claude" / "sessions", self.cwd):
            d.mkdir(parents=True)
        (self.pm / ".boss-sessions" / SID).write_text(TRACK + "\n")
        (self.pm / (TRACK + ".goal.md")).write_text(
            "# Objective\n\n_Status: OPEN_\n\n## Outcome\nShip the thing.\n\n"
            "## Done when\n- [ ] it ships\n\n## Next, in priority order\n- do a thing\n",
            encoding="utf-8")
        (self.pm / (TRACK + ".md")).write_text(
            "# Tracker\n\n## Roster\n| none |\n\n## Open blockers\n"
            "- waiting on the owner to pick the org\n\n## Decisions\n- d\n",
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, script, payload=None, *args):
        env = dict(os.environ, CLAUDE_CONFIG_DIR="", HOME=str(self.home))
        for k in ("BOSS_LADDER_PM", "BOSS_LADDER_STATE"):
            env.pop(k, None)
        res = subprocess.run(
            [sys.executable, str(HERE / script), *args],
            input=json.dumps(payload or {}), capture_output=True, text=True,
            env=env, cwd=self.cwd, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout.strip()

    def test_no_stray_pm_in_the_working_directory(self):
        self.run_hook("boss-compact.py", {"session_id": SID, "hook_event_name": "SessionStart", "source": "compact"})
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_guard_fires_and_logs_under_home(self):
        out = self.run_hook("boss-guard.py", {
            "session_id": SID, "hook_event_name": "PreToolUse",
            "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}})
        self.assertIn("is implementation work", out)
        self.assertTrue((self.pm / "boss-guard.log").is_file())
        self.assertTrue((self.pm / ".pulse" / (SID + ".guard.json")).is_file())
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_pulse_reads_the_boss_and_writes_its_state_under_home(self):
        out = self.run_hook("boss-pulse.py", {
            "session_id": SID, "hook_event_name": "Stop", "stop_hook_active": False})
        self.assertIn("pick the org", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertTrue((self.pm / ".pulse" / (SID + ".json")).is_file())
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_compact_injects_the_objective_and_tracker_from_home(self):
        out = self.run_hook("boss-compact.py", {"session_id": SID, "hook_event_name": "SessionStart", "source": "compact"})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Ship the thing.", ctx)
        self.assertIn("pick the org", ctx)

    def test_reap_sweeps_the_files_under_home(self):
        old = time.time() - 48 * 3600
        for p in (self.pm / ".boss-sessions" / DEAD, self.pm / ".pulse" / (DEAD + ".json")):
            p.write_text("demo\n")
            os.utime(p, (old, old))
        self.run_hook("boss-reap.py", None, "--sweep")
        self.assertFalse((self.pm / ".boss-sessions" / DEAD).exists())
        self.assertFalse((self.pm / ".pulse" / (DEAD + ".json")).exists())

    def ladder_paths(self, **extra):
        """(PM_DIR, STATE) the ladder core resolves with CLAUDE_CONFIG_DIR empty."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("BOSS_LADDER_PM", "BOSS_LADDER_STATE")}
        env.update(CLAUDE_CONFIG_DIR="", HOME=str(self.home), **extra)
        code = ("import sys; sys.path.insert(0, %r); import boss_ladder_core as c; "
                "print(c.PM_DIR); print(c.STATE)" % str(LADDER.parent))
        res = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, cwd=self.cwd, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        return [Path(x) for x in res.stdout.split("\n") if x]

    def test_ladder_defaults_are_under_home(self):
        pm, state = self.ladder_paths()
        self.assertEqual(pm, self.pm)
        self.assertEqual(state, self.home / ".claude" / "routines" / "state" / "boss-ladder.json")

    def test_ladder_overrides_still_win(self):
        pm, state = self.ladder_paths(BOSS_LADDER_PM=str(self.tmp / "opm"),
                                      BOSS_LADDER_STATE=str(self.tmp / "ost.json"))
        self.assertEqual((pm, state), (self.tmp / "opm", self.tmp / "ost.json"))


if __name__ == "__main__":
    unittest.main()
