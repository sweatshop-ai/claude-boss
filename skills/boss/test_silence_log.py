#!/usr/bin/env python3
"""Tests for silence_log.py and the pulse's use of it.

Run: python3 -m pytest skills/boss/test_silence_log.py

Every test points CLAUDE_CONFIG_DIR at a throwaway directory (PulseCase), so
nothing is written into the real ~/.claude/pm/.
"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402
import silence_log  # noqa: E402
from test_boss_pulse import PULSE, TRACK, PulseCase  # noqa: E402


class Lines(PulseCase):

    def stop(self, background=None):
        payload = {"session_id": self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": False, "background_tasks": background or []}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def log(self):
        p = self.tmp / "pm/.pulse" / (self.sid + ".silence.log")
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    def test_a_gate_that_holds_the_pulse_back_writes_one_line_naming_it(self):
        self.goal(open_=False)
        self.assertEqual(self.stop(), "")
        (line,) = self.log()
        _, track, gate = line.split("\t")[:3]
        self.assertEqual((track, gate), (TRACK, "objective-closed"))

    def test_no_goal_is_its_own_gate(self):
        (self.tmp / "pm" / (TRACK + ".goal.md")).unlink()
        self.stop()
        self.assertEqual([l.split("\t")[2] for l in self.log()], ["no-goal"])

    def test_nothing_to_say_records_the_idle_count(self):
        self.stop()
        (line,) = self.log()
        fields = line.split("\t")
        self.assertEqual(fields[2], "nothing-to-say")
        self.assertIn("idle=0", fields)

    def test_an_open_question_is_named(self):
        self.tracker(blockers="- pick the org")
        self.register(status="waiting", waiting_for="input needed")
        self.stop()
        self.assertEqual([l.split("\t")[2] for l in self.log()], ["open-question"])

    def test_background_tasks_are_named(self):
        self.stop(background=[{"status": "running"}])
        self.assertEqual([l.split("\t")[2] for l in self.log()], ["background-tasks"])

    def test_the_rate_gate_is_named(self):
        self.tracker(blockers="- pick the org")
        self.assertNotEqual(self.stop(), "")
        self.stop()
        self.assertEqual([l.split("\t")[2] for l in self.log()], ["fired", "rate-gate"])

    def test_a_boss_with_no_track_is_named(self):
        (self.tmp / "pm/.boss-sessions" / self.sid).write_text("\n")
        self.assertEqual(self.stop(), "")
        self.assertEqual([l.split("\t")[2] for l in self.log()], ["no-track"])

    def test_a_session_that_is_not_a_boss_logs_nothing_and_writes_no_file(self):
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        other = "11111111-2222-3333-4444-555555555555"
        for payload in ({"session_id": other, "hook_event_name": "Stop"},
                        {"session_id": "", "hook_event_name": "Stop"},
                        {"hook_event_name": "Stop"},
                        {"session_id": self.sid, "hook_event_name": "PreToolUse"}):
            res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                                 capture_output=True, text=True, env=env, timeout=20)
            self.assertEqual((res.returncode, res.stdout), (0, ""), res.stderr)
        res = subprocess.run([sys.executable, str(PULSE)], input="not json",
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual((res.returncode, res.stdout), (0, ""), res.stderr)
        self.assertEqual(sorted(str(p) for p in self.tmp.rglob("*")), before)

    def test_a_pulse_that_fires_writes_its_decision(self):
        self.tracker(blockers="- pick the org")
        self.assertNotEqual(self.stop(), "")
        (line,) = self.log()
        fields = line.split("\t")
        self.assertEqual(fields[2], "fired")
        self.assertIn("actions=ask", fields)
        self.assertIn("idle=0", fields)

    def test_an_unwritable_log_never_fails_the_hook(self):
        # a directory where the log file should be
        (self.tmp / "pm/.pulse" / (self.sid + ".silence.log")).mkdir()
        self.tracker(blockers="- pick the org")
        self.assertIn("AskUserQuestion", self.stop())


class Rotation(unittest.TestCase):

    def test_the_log_rotates_at_one_megabyte(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            p = Path(d) / "pm/.pulse" / (sid + ".silence.log")
            p.parent.mkdir(parents=True)
            p.write_bytes(b"x" * silence_log.MAX_BYTES)
            silence_log.record(sid, "demo", "no-goal", cfg=d)
            self.assertEqual(p.read_text().count("\n"), 1)
            self.assertEqual((p.parent / (sid + ".silence.log.1")).stat().st_size,
                             silence_log.MAX_BYTES)

    def test_reap_takes_the_log_and_its_rotation_with_the_session(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            silence_log.record(sid, "demo", "no-goal", cfg=d)
            p = boss_store.state_path(sid, "silence", d)
            p.with_name(p.name + ".1").write_text("old\n")
            found = {q.name for q, s in boss_store.reap_candidates(d) if s == sid}
            self.assertEqual(found, {p.name, p.name + ".1"})

    def test_a_bad_session_id_is_not_an_error(self):
        silence_log.record("../x", "demo", "no-goal", cfg="/nonexistent")


class Why(PulseCase):

    def why(self, *args):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE), "why", *args],
                             capture_output=True, text=True, env=env, timeout=20)
        return res

    def test_why_counts_per_gate_and_names_the_last_firing(self):
        now = time.time()
        for age, gate in ((30, "rate-gate"), (20, "rate-gate"), (10, "fired"),
                          (5, "nothing-to-say"), (3 * 86400, "no-goal")):
            silence_log.record(self.sid, TRACK, gate, now=now - age, cfg=self.tmp)
        silence_log.record(self.sid, "other", "rate-gate", now=now, cfg=self.tmp)
        res = self.why(TRACK)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout
        self.assertRegex(out, r"rate-gate\s+2")
        self.assertRegex(out, r"fired\s+1")
        self.assertRegex(out, r"nothing-to-say\s+1")
        self.assertNotIn("no-goal", out)          # older than a day
        self.assertIn("last fired", out)
        self.assertIn(time.strftime("%H:%M:%S", time.localtime(now - 10)), out)

    def test_why_with_no_log_says_so(self):
        res = self.why(TRACK)
        self.assertEqual(res.returncode, 0)
        self.assertIn("no Stop", res.stdout)

    def test_why_needs_a_track(self):
        self.assertEqual(self.why().returncode, 2)


class SpokeGates(unittest.TestCase):
    def test_a_block_counts_as_the_last_firing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            import pathlib
            cfg = pathlib.Path(d)
            silence_log.record("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "t", "blocked", cfg=cfg)
            self.assertIsNotNone(silence_log.summary("t", cfg=cfg)[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
