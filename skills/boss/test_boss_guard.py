#!/usr/bin/env python3
"""Tests for boss-guard.py, the PreToolUse guard on boss sessions.

Run: python3 skills/boss/test_boss_guard.py

Every test runs the hook the way the harness does — as a process, JSON on
stdin — against a throwaway CLAUDE_CONFIG_DIR. Nothing here touches the real
~/.claude/pm.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "boss-guard.py"


class GuardCase(unittest.TestCase):
    """A boss session registered in a scratch config dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="boss-guard-test-")
        self.cfg = Path(self.tmp)
        self.markers = self.cfg / "pm" / ".boss-sessions"
        self.markers.mkdir(parents=True)
        self.sid = "11111111-2222-3333-4444-555555555555"
        (self.markers / self.sid).write_text("demo\n", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fire(self, command="rm -rf build", tool="Bash", sid=None, tool_input=None):
        """One PreToolUse call. Returns the additionalContext, or '' if silent."""
        if tool_input is None:
            tool_input = ({"command": command} if tool == "Bash"
                          else {"file_path": command})
        payload = {
            "session_id": sid or self.sid,
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
        }
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg))
        res = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        if not out:
            return ""
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def log_lines(self):
        f = self.cfg / "pm" / "boss-guard.log"
        if not f.exists():
            return []
        return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


class Deduplication(GuardCase):
    """2,589 firings over 14 days repeated one 330-character sentence."""

    def test_full_text_once_then_never_again(self):
        first = self.fire("rm -rf build")
        self.assertIn("is implementation work", first)
        self.assertIn("Dispatch it to a worker", first)

        second = self.fire("rm -rf dist")
        self.assertNotIn("Dispatch it to a worker", second,
                         "the full sentence repeated on the second firing")

    def test_every_firing_is_still_logged(self):
        for i in range(5):
            self.fire("touch f%d" % i)
        self.assertEqual(len(self.log_lines()), 5,
                         "the log is the evidence base and must stay complete")

    def test_a_runaway_is_still_visible(self):
        """Silence after one nudge hides a boss doing 725 of these."""
        said = [bool(self.fire("touch f%d" % i)) for i in range(1, 40)]
        # firings 2, 4, 8, 16, 32 speak; the rest are silent.
        spoke = [i + 1 for i, v in enumerate(said) if v]
        self.assertEqual(spoke, [1, 2, 4, 8, 16, 32])

    def test_the_repeat_is_a_count_not_the_sentence(self):
        self.fire("touch a")
        second = self.fire("touch b")
        self.assertNotIn("Dispatch it to a worker", second)
        self.assertIn("2nd", second)
        self.assertLess(len(second), 160, "the repeat must stay short")


class Scope(GuardCase):
    """What the guard must go on doing, dedup or not."""

    def test_each_session_gets_its_own_first_warning(self):
        other = "99999999-8888-7777-6666-555555555555"
        (self.markers / other).write_text("other\n", encoding="utf-8")
        self.fire("touch a")
        self.assertIn("Dispatch it to a worker", self.fire("touch b", sid=other),
                      "a second boss inherited the first one's counter")

    def test_a_session_with_no_marker_is_left_alone(self):
        self.assertEqual(self.fire("rm -rf /", sid="not-a-boss"), "")
        self.assertEqual(self.log_lines(), [])

    def test_allowed_commands_never_spend_the_budget(self):
        for _ in range(4):
            self.assertEqual(self.fire("gh pr list"), "")
        self.assertIn("Dispatch it to a worker", self.fire("touch x"),
                      "coordination calls consumed the one full warning")


class Precision(GuardCase):
    """1,227 of the 2,589 logged firings named a coordination tool.

    The guard was scolding the boss for running the boss's own commands.
    """

    def test_the_bosss_own_tools_are_coordination(self):
        for cmd in ("boss-goal next demo",
                    "${CLAUDE_PLUGIN_ROOT}/skills/boss/bin/boss-goal status demo",
                    "boss-start demo",
                    "/opt/whatever/claude-team/hooks/team-line abc --did x --n 0"):
            self.assertEqual(self.fire(cmd), "", "scolded for `%s`" % cmd)

    def test_a_cd_prefix_does_not_hide_an_allowed_command(self):
        self.assertEqual(self.fire("cd ${CLAUDE_PLUGIN_ROOT}/skills/boss/bin && ./boss-tracker list"), "")

    def test_a_variable_prefix_does_not_hide_an_allowed_command(self):
        self.assertEqual(self.fire("B=${CLAUDE_PLUGIN_ROOT}/skills/boss/bin; $B/boss-goal next demo"), "")

    def test_the_prefix_strip_does_not_wave_through_real_work(self):
        self.assertNotEqual("", self.fire("cd /repo && npm run build"))
        self.assertNotEqual("", self.fire("FOO=1 python3 train.py"))


class AgentTeams(GuardCase):
    """A named Agent call in a boss starts an agent-teams teammate.

    With CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 the harness launches it without
    asking: no pane, no stamp, invisible to `list --mine`, the pulse and the
    workers watch, and it dies with the boss. Rare and costly, so every one is
    named out loud; the power-of-two throttle is for the cheap, frequent kind.
    """

    def spawn(self, **extra):
        ti = {"description": "x", "prompt": "do the thing"}
        ti.update(extra)
        return self.fire(tool="Agent", tool_input=ti)

    def test_a_named_agent_call_is_called_a_teammate(self):
        said = self.spawn(name="reviewer")
        self.assertIn("agent-teams teammate", said)
        self.assertIn("reviewer", said)

    def test_it_speaks_off_the_power_of_two_counts(self):
        for i in range(4):
            self.fire("touch f%d" % i)
        self.assertIn("agent-teams teammate", self.spawn(name="fifth"),
                      "a teammate spawn on call 5 went unsaid")

    def test_every_spawn_speaks(self):
        for i in range(3):
            self.assertIn("agent-teams teammate", self.spawn(name="t%d" % i))

    def test_spawns_are_logged(self):
        self.spawn(name="reviewer")
        self.assertEqual([l["tool"] for l in self.log_lines()], ["Agent"])

    def test_an_unnamed_agent_call_is_counted_like_the_rest(self):
        self.assertIn("Dispatch it to a worker", self.spawn())
        self.assertIn("2nd", self.spawn())
        self.assertEqual(self.spawn(), "", "the 3rd ordinary call should be silent")

    def test_a_named_fork_or_isolated_call_is_not_a_teammate(self):
        """The harness runs these as subagents even with a name."""
        self.assertNotIn("agent-teams teammate",
                         self.spawn(name="f", subagent_type="fork"))
        self.assertNotIn("agent-teams teammate",
                         self.spawn(name="w", isolation="worktree"))

    def test_a_session_with_no_marker_is_left_alone(self):
        self.assertEqual(self.fire(tool="Agent", sid="not-a-boss",
                                   tool_input={"name": "x", "prompt": "y"}), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
