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
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin"
sys.path.insert(0, str(HERE))
import tracker as tracker_mod  # noqa: E402
from hermetic import Sandbox, risks  # noqa: E402


class GoalReviewers(unittest.TestCase):
    """`boss-goal review` and `premortem` go through the reviewer chain: Codex, then a
    preset fallback. Hermetic: codex and claude are the sandbox's stubs."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.goal("init", "demo")

    def goal(self, *args, timeout=60):
        return subprocess.run([str(BIN / "boss-goal"), *args], env=self.sb.env, cwd=str(self.sb.work),
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)

    def test_review_prints_the_verdict_lines_and_who_answered(self):
        self.sb.stub("codex", answer="Some prose first.\nVERDICT: COMPLETE\nREASON: all there\nMISSING: nothing")
        r = self.goal("review", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "VERDICT: COMPLETE\nREASON: all there\nMISSING: nothing\n--- reviewer: codex\n")
        (call,) = self.sb.calls_of("codex")
        self.assertNotIn("-C", call.argv)
        self.assertIn("demo", call.argv[-1])            # {{TRACK}} filled
        self.assertNotIn("{{GOAL}}", call.argv[-1])

    def test_review_keeps_the_old_prefix_match_so_completed_still_counts(self):
        # The bash copy's grep took `VERDICT: COMPLETED` as COMPLETE; the chain's default
        # for these words would be whole tokens, so review asks for the prefix rule.
        self.sb.stub("codex", answer="VERDICT: COMPLETED\nREASON: fine")
        self.sb.stub("claude", answer="VERDICT: INCOMPLETE\nREASON: never asked")
        r = self.goal("review", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.sb.calls_of("claude"), [])

    def test_review_says_so_when_the_chain_itself_did_not_run(self):
        # A chain that exits without a Result (a usage error) is not "both silent".
        chain = HERE / "reviewer_chain.py"
        (self.sb.stubs / "python3").write_text('#!/bin/bash\n[[ "$1" == *reviewer_chain.py ]] && exit 2\nexec %s "$@"\n'
                                               % (self.sb.tools / "python3"))
        (self.sb.stubs / "python3").chmod(0o755)
        self.assertTrue(chain.is_file())
        r = self.goal("review", "demo")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("reviewer chain exited 2 without a result", r.stdout)

    def test_review_incomplete_is_exit_three_and_opus_is_the_fallback(self):
        self.sb.stub("codex", answer="I cannot say.")
        self.sb.stub("claude", answer="VERDICT: INCOMPLETE\nREASON: no done criterion")
        r = self.goal("review", "demo")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("--- reviewer: opus\n", r.stdout)
        self.assertEqual(self.sb.calls_of("claude")[0].argv[:3], ["-p", "--model", "claude-opus-5-5"])

    def test_review_with_no_answer_is_exit_four_and_says_why_each_reviewer_failed(self):
        self.sb.stub("codex", rc=1, err="usage limit")
        r = self.goal("review", "demo")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("codex: error, opus: absent", r.stdout)
        self.assertIn("not a pass", r.stdout)

    def test_premortem_numbers_the_risks_and_fable_is_its_fallback(self):
        self.sb.stub("codex", answer=risks(3))                  # too thin: not a sweep
        self.sb.stub("claude", answer="Week later.\n" + risks(9))
        r = self.goal("premortem", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "R1. risk number 1")
        self.assertEqual(lines[8], "R9. risk number 9")
        self.assertEqual(lines[9], "--- from: fable")
        self.assertEqual(self.sb.calls_of("claude")[0].argv[:3], ["-p", "--model", "claude-fable-5-1"])

    def test_premortem_with_a_directory_lets_both_reviewers_read_it_and_cuts_at_25(self):
        repo = self.sb.work / "repo"
        repo.mkdir()
        self.sb.stub("codex", answer=risks(30))
        r = self.goal("premortem", "demo", str(repo))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("\nR"), 24)
        self.assertIn("R25. risk number 25\n--- from: codex\n", r.stdout)
        self.assertIn("-C", self.sb.calls_of("codex")[0].argv)
        self.sb.stub("codex", answer="")
        self.sb.stub("claude", answer=risks(8))
        self.goal("premortem", "demo", str(repo))
        self.assertEqual(self.sb.calls_of("claude")[0].argv[:2], ["--allowedTools", "Read,Grep,Glob"])

    def test_premortem_with_no_sweep_is_exit_four(self):
        self.sb.stub("codex", answer=risks(7))
        r = self.goal("premortem", "demo")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("codex: noverdict, fable: absent", r.stdout)


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

    def goal_with_tickets(self, issues):
        self.run_tool("boss-goal", "init", "demo")
        goal = self.cfg / "pm" / "demo.goal.md"
        goal.write_text(goal.read_text().replace(
            "## Next, in priority order", "## Tickets\n%s\n\n## Next, in priority order" % issues))

    def test_check_reads_the_ticket_graph_instead_of_next(self):
        issues = self.cfg / "issues"
        issues.mkdir()
        (issues / "01-a.md").write_text("# 01: A\n\n**Blocked by:** None\n\n**Status:** ready\n")
        self.goal_with_tickets(issues)
        res = self.run_tool("boss-goal", "check", "demo")
        self.assertNotIn("unbound variable", res.stderr)
        self.assertIn("TICKETS: Ready now: 01", res.stdout)
        self.assertIn("| 1 queued |", res.stdout)
        self.assertNotIn('nothing under "Next', res.stdout)

    def test_check_names_a_broken_ticket_graph(self):
        issues = self.cfg / "issues"
        issues.mkdir()
        (issues / "01-a.md").write_text("# 01: A\n\n**Status:** ready\n")
        self.goal_with_tickets(issues)
        out = self.run_tool("boss-goal", "check", "demo")
        self.assertIn("TICKET GRAPH BROKEN", out.stdout)
        self.assertIn("no **Blocked by:** field", out.stdout)
        self.assertNotEqual(out.returncode, 0)

    def test_append_waits_for_the_tracker_lock(self):
        # boss-jev and the ladder routine rewrite the tracker by temp file and
        # rename under pm/.<track>.md.lock. An append that ignores the lock can
        # land in the file the rename is about to replace.
        self.run_tool("boss-tracker", "init", "demo", "Boss")
        tracker = self.cfg / "pm" / "demo.md"
        # The lock boss-jev and the ladder take, from the module they share.
        with open(tracker_mod.lock_path(tracker), "a") as lock:
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
