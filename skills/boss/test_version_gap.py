#!/usr/bin/env python3
"""version_gap reports installed < released and live sessions on an older version.

Run: python3 skills/boss/test_version_gap.py

Every case builds its own config directory; nothing reads the real ~/.claude or the network
(`fetch` is a stub). The first test prints the path version_gap was imported from.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import version_gap

LIVE = os.getpid()       # a pid that certainly exists


class Gap(unittest.TestCase):

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="version-gap-test-"))
        (self.cfg / "plugins").mkdir()
        self.addCleanup(shutil.rmtree, self.cfg, True)

    def install(self, version):
        rec = {"plugins": {"claude-boss@sweatshop-ai": [{"version": version}]}}
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(rec))

    def mark(self, version, pid, start="auto"):
        d = self.cfg / "plugins" / "cache" / "m" / "claude-boss" / version / ".in_use"
        d.mkdir(parents=True, exist_ok=True)
        if start == "auto":
            try:
                start = version_gap.proc_start(pid)
            except OSError:
                start = "1"
        (d / str(pid)).write_text(json.dumps({"pid": pid, "procStart": start}))

    def gaps(self, released, now=1000):
        return version_gap.gaps(self.cfg, fetch=lambda: released, now=now)

    def test_runs_the_copy_under_test(self):
        self.assertTrue(Path(version_gap.__file__).resolve().is_relative_to(
            Path(__file__).resolve().parent), version_gap.__file__)

    def test_agreement_is_silent(self):
        self.install("0.21.0")
        self.mark("0.21.0", LIVE)
        self.assertEqual(self.gaps("0.21.0"), [])

    def test_installed_behind_released(self):
        self.install("0.19.1")
        out = self.gaps("0.20.0")
        self.assertEqual(len(out), 1)
        self.assertIn("0.19.1 is installed, 0.20.0 is released", out[0])

    def test_numeric_not_textual_order(self):
        self.install("0.9.1")
        self.assertEqual(len(self.gaps("0.10.0")), 1)
        self.install("0.10.0")
        self.assertEqual(self.gaps("0.9.1"), [])    # ahead of released (a branch build): no gap

    def test_live_session_on_older_version(self):
        self.install("0.21.0")
        self.mark("0.19.2", LIVE)
        self.mark("0.21.0", LIVE)
        out = self.gaps("0.21.0")
        self.assertEqual(len(out), 1)
        self.assertIn("1 live session(s)", out[0])
        self.assertIn("0.19.2", out[0])

    def test_dead_pid_is_not_a_session(self):
        self.install("0.21.0")
        self.mark("0.19.2", 2 ** 22 + 12345)       # above pid_max on this kernel
        self.assertEqual(self.gaps("0.21.0"), [])

    def test_reused_pid_is_not_a_session(self):
        self.install("0.21.0")
        self.mark("0.19.2", LIVE, start="1")        # alive, but not the process that wrote the file
        self.assertEqual(self.gaps("0.21.0"), [])

    def test_offline_is_silent_and_retried_after_ten_minutes(self):
        self.install("0.21.0")
        calls = []
        def boom():
            calls.append(1)
            raise OSError("no network")
        self.assertEqual(version_gap.gaps(self.cfg, fetch=boom, now=1000), [])
        version_gap.gaps(self.cfg, fetch=boom, now=1000 + 300)
        self.assertEqual(calls, [1])
        version_gap.gaps(self.cfg, fetch=boom, now=1000 + 700)
        self.assertEqual(calls, [1, 1])

    def test_short_and_suffixed_versions(self):
        self.assertEqual(version_gap.vkey("1.0"), version_gap.vkey("1.0.0"))
        self.assertEqual(version_gap.vkey("0.21.0-rc1"), version_gap.vkey("0.21.0"))

    def test_update_command_names_the_installed_marketplace(self):
        rec = {"plugins": {"claude-boss@fork": [{"scope": "user", "version": "0.19.1"}]}}
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(rec))
        self.assertIn("update claude-boss@fork`", self.gaps("0.20.0")[0])

    def test_only_the_user_scope_install_counts(self):
        rec = {"plugins": {"claude-boss@x": [{"scope": "project", "version": "0.1.0"}],
                           "claude-boss@sweatshop-ai": [{"scope": "user", "version": "0.20.0"}]}}
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(rec))
        self.assertEqual(version_gap.installed(self.cfg)[0], "0.20.0")

    def test_corrupt_cache_is_refetched(self):
        self.install("0.19.1")
        cache = self.cfg / "pm" / ".pulse" / "version-gap.json"
        cache.parent.mkdir(parents=True)
        cache.write_text("{not json")
        self.assertIn("0.20.0 is released", self.gaps("0.20.0")[0])

    def test_released_is_cached_for_six_hours(self):
        self.install("0.19.1")
        self.gaps("0.20.0", now=1000)
        calls = []
        again = version_gap.gaps(self.cfg, fetch=lambda: calls.append(1) or "9.9.9", now=1000 + 3600)
        self.assertEqual(calls, [])
        self.assertIn("0.20.0 is released", again[0])
        version_gap.gaps(self.cfg, fetch=lambda: calls.append(1) or "9.9.9", now=1000 + 7 * 3600)
        self.assertEqual(calls, [1])

    def test_no_install_record_is_silent(self):
        self.assertEqual(self.gaps("0.21.0"), [])


if __name__ == "__main__":
    unittest.main()
