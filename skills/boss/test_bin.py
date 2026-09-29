#!/usr/bin/env python3
"""Tests for the bash tools in bin/: where they write, what they accept.

Run: python3 skills/boss/test_bin.py

The hooks read `$CLAUDE_CONFIG_DIR/pm`; the tools must write there too, or a
boss with its own config dir writes a tracker no hook ever reads. HOME points
at a second throwaway directory, so a tool that still used $HOME/.claude could
never touch the real one.
"""
import fcntl
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent / "bin"


class Tools(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="boss-bin-cfg-"))
        self.home = Path(tempfile.mkdtemp(prefix="boss-bin-home-"))
        self.env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), HOME=str(self.home))

    def run_tool(self, tool, *args, stdin="", timeout=20):
        return subprocess.run([str(BIN / tool), *args], input=stdin, env=self.env,
                              capture_output=True, text=True, timeout=timeout)

    def test_the_tracker_lands_in_the_config_dir_the_hooks_read(self):
        out = self.run_tool("boss-tracker", "init", "demo", "Boss")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.cfg / "pm" / "demo.md").is_file())
        self.assertFalse((self.home / ".claude").exists())

    def test_the_objective_lands_in_the_config_dir_too(self):
        out = self.run_tool("boss-goal", "init", "demo")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.cfg / "pm" / "demo.goal.md").is_file())
        self.assertFalse((self.home / ".claude").exists())

    def test_a_track_that_is_not_a_plain_name_is_refused(self):
        for tool in ("boss-tracker", "boss-goal"):
            for bad in ("../escape", "Demo Track", ".hidden"):
                args = ("init", bad, "Boss") if tool == "boss-tracker" else ("init", bad)
                out = self.run_tool(tool, *args)
                self.assertNotEqual(out.returncode, 0, (tool, bad))
        self.assertFalse((self.cfg / "escape.md").exists())
        self.assertFalse((self.cfg / "escape.goal.md").exists())

    def test_the_pulse_counts_as_armed_when_the_plugin_is_enabled(self):
        self.run_tool("boss-goal", "init", "demo")
        (self.cfg / "settings.json").write_text(json.dumps(
            {"enabledPlugins": {"claude-boss@sweatshop-ai": True}}))
        out = self.run_tool("boss-goal", "check", "demo")
        self.assertNotIn("NOT ARMED", out.stdout)
        self.assertIn("armed", out.stdout)

    def test_the_pulse_is_not_armed_when_the_plugin_is_off(self):
        self.run_tool("boss-goal", "init", "demo")
        (self.cfg / "settings.json").write_text(json.dumps(
            {"enabledPlugins": {"claude-boss@sweatshop-ai": False}}))
        out = self.run_tool("boss-goal", "check", "demo")
        self.assertIn("NOT ARMED", out.stdout)

    def test_append_waits_for_the_tracker_lock(self):
        # boss-jev and the ladder routine rewrite the tracker by temp file and
        # rename under pm/.<track>.md.lock. An append that ignores the lock can
        # land in the file the rename is about to replace.
        self.run_tool("boss-tracker", "init", "demo", "Boss")
        tracker = self.cfg / "pm" / "demo.md"
        with open(self.cfg / "pm" / ".demo.md.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            proc = subprocess.Popen([str(BIN / "boss-tracker"), "append", "demo"],
                                    stdin=subprocess.PIPE, env=self.env, text=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.stdin.write("- appended line\n")
            proc.stdin.close()
            time.sleep(0.5)
            self.assertNotIn("appended line", tracker.read_text(), "wrote while locked")
        proc.wait(timeout=10)
        self.assertIn("appended line", tracker.read_text())


if __name__ == "__main__":
    unittest.main()
