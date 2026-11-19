#!/usr/bin/env python3
"""Tests for goal_graph.py — the ticket graph at the top of a goal page (goal-graph ticket 01).

Run: python3 skills/boss/test_goal_graph.py
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
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_store  # noqa: E402
import goal_graph  # noqa: E402
import objective  # noqa: E402

FIXTURE = HERE / "fixtures" / "goal-graph"
GOAL_GRAPH = HERE / "goal_graph.py"
FRONTIER = HERE.parent / "hand-to-boss" / "frontier.py"
PULSE = HERE / "boss-pulse.py"
TRACK = "demo"
NOW = 1763550000.0          # a fixed read time; TZ is UTC below, so it prints 11:00


def goal(source=None, extra=""):
    text = ("# Objective — demo\n\n_Status: OPEN_\n\n## Outcome\nShip the thing.\n\n"
            "## Done when\n- [ ] it ships\n- [ ] it is documented\n\n")
    if source is not None:
        text += "## Tickets\n%s\n\n" % source
    return text + "## Next, in priority order\n- do a thing\n" + extra


class GoalCase(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.cfg = Path(tempfile.mkdtemp(prefix="goal-graph-test-"))
        (self.cfg / "pm" / ".pulse").mkdir(parents=True)
        (self.cfg / "pm" / (TRACK + ".md")).write_text("# Tracker\n", encoding="utf-8")
        self.issues = self.cfg / "issues"
        shutil.copytree(FIXTURE / "issues", self.issues)
        self.path = self.cfg / "pm" / (TRACK + ".goal.md")

    def tearDown(self):
        shutil.rmtree(self.cfg, ignore_errors=True)
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    def write_goal(self, text):
        self.path.write_text(text, encoding="utf-8")

    def update(self, now=NOW):
        return goal_graph.update(TRACK, now=now, cfg=self.cfg)

    def text(self):
        return self.path.read_text(encoding="utf-8")

    def env(self):
        return dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg))


class Form(GoalCase):
    def test_the_fixture_gives_the_checked_in_block_byte_for_byte(self):
        """All four states, one external blocker, one ticket blocked by two."""
        out, error = goal_graph.read(str(self.issues), TRACK)
        self.assertIsNone(error)
        got = "\n".join(goal_graph.block(out, NOW)) + "\n"
        self.assertEqual(got, (FIXTURE / "expected-block.md").read_text(encoding="utf-8"))

    def test_titles_lose_quotes_backticks_and_angle_brackets_and_are_cut(self):
        out, _ = goal_graph.read(str(self.issues), TRACK)
        node = next(ln for ln in goal_graph.diagram(out) if ln.startswith("  t02["))
        label = node.split('"')[1]
        for bad in "`<>":
            self.assertNotIn(bad, label.replace("<br/>", ""))
        self.assertIn("…", label)
        self.assertTrue(label.endswith("<br/>Farid"))


class Place(GoalCase):
    def test_the_section_goes_at_the_top_and_the_goal_still_reads(self):
        self.write_goal(goal(self.issues))
        self.assertEqual(self.update(), "written")
        text = self.text()
        lines = text.split("\n")
        self.assertLess(lines.index("## Ticket graph"), lines.index("## Outcome"))
        self.assertGreater(lines.index("## Ticket graph"), lines.index("_Status: OPEN_"))
        self.assertEqual(objective.section(text, "Outcome"), "Ship the thing.")
        self.assertEqual(objective.criteria(text), [(False, "it ships"), (False, "it is documented")])
        self.assertEqual(objective.tickets_source(text), str(self.issues))
        self.assertTrue(objective.is_open(text))

    def test_a_goal_without_tickets_is_left_alone(self):
        self.write_goal(goal(None))
        before = self.text()
        self.assertEqual(self.update(), "none")
        self.assertEqual(self.text(), before)

    def test_a_heading_without_its_block_gets_the_block_under_it(self):
        self.write_goal(goal(self.issues, extra="\n## Ticket graph\n"))
        self.update()
        text = self.text()
        self.assertEqual(text.count("## Ticket graph"), 1)
        self.assertEqual(text.count(goal_graph.START), 1)


class OnlyTheBlock(GoalCase):
    def test_an_unchanged_frontier_writes_nothing_even_later(self):
        self.write_goal(goal(self.issues))
        self.update()
        mtime = self.path.stat().st_mtime_ns
        before = self.text()
        self.assertEqual(self.update(now=NOW + 3600), "unchanged")
        self.assertEqual(self.path.stat().st_mtime_ns, mtime)
        self.assertEqual(self.text(), before)

    def test_a_changed_state_rewrites_the_block_and_keeps_the_owners_paragraph(self):
        self.write_goal(goal(self.issues))
        self.update()
        typed = self.text().replace("Ship the thing.", "Ship the thing.\n\nThierry typed this.")
        self.write_goal(typed)
        t = self.issues / "03-claim.md"
        t.write_text(t.read_text().replace("ready-for-agent", "done"))
        self.assertEqual(self.update(now=NOW + 60), "written")
        text = self.text()
        self.assertIn("Thierry typed this.", text)
        self.assertIn('t03["03 · A claim updates the graph<br/>done"]', text)
        self.assertIn("· read 11:01", text)
        a, b = goal_graph._span(text.split("\n")), goal_graph._span(typed.split("\n"))
        self.assertEqual(text.split("\n")[:a[0]], typed.split("\n")[:b[0]])
        self.assertEqual(text.split("\n")[a[1] + 1:], typed.split("\n")[b[1] + 1:])

    def test_a_write_against_a_changed_file_is_not_made(self):
        self.write_goal(goal(self.issues))
        self.assertFalse(goal_graph._write_if_same(self.path, "something else", "new"))
        self.assertEqual(self.text(), goal(self.issues))

    def test_a_broken_source_keeps_the_graph_and_names_the_error(self):
        self.write_goal(goal(self.issues))
        self.update()
        t = self.issues / "01-store.md"
        t.write_text(t.read_text().replace("**Blocked by:** None", "**Blocked by:** 04"))
        self.assertEqual(self.update(now=NOW + 120), "written")
        text = self.text()
        self.assertIn('t01["01 · Paths come from the track store<br/>done"]', text)
        line = next(ln for ln in text.split("\n") if ln.startswith("Ticket source unreadable"))
        self.assertIn("at 11:02", line)
        self.assertIn("cycle", line)


class GitHub(GoalCase):
    SOURCE = "gh:acme/widgets#7"

    def cache(self):
        out, _ = goal_graph.read(str(self.issues), TRACK)
        path = boss_store.frontier_cache(TRACK, self.SOURCE, self.cfg)
        path.write_text(json.dumps(out), encoding="utf-8")
        old = time.time() - 600
        os.utime(path, (old, old))

    def test_a_graph_nobody_has_read_draws_nothing(self):
        self.write_goal(goal(self.SOURCE))
        self.assertEqual(goal_graph.update(TRACK, fetch=False, now=NOW, cfg=self.cfg), "none")

    def test_the_cache_is_drawn_and_a_failed_read_is_named_under_it(self):
        self.write_goal(goal(self.SOURCE))
        self.cache()
        self.assertEqual(goal_graph.update(TRACK, fetch=False, now=NOW, cfg=self.cfg), "written")
        with mock.patch.object(boss_store, "refresh_frontier", return_value="gh: HTTP 502") as r:
            self.assertEqual(goal_graph.update(TRACK, now=NOW + 60, cfg=self.cfg), "written")
            self.assertEqual(r.call_count, 1)
        text = self.text()
        self.assertIn('t03["03 · A claim updates the graph<br/>ready"]', text)
        self.assertIn("Ticket source unreadable at 11:01: gh: HTTP 502", text)
        with mock.patch.object(boss_store, "refresh_frontier", return_value="gh: HTTP 502"):
            self.assertEqual(goal_graph.update(TRACK, now=NOW + 120, cfg=self.cfg), "unchanged")


class Callers(GoalCase):
    def test_the_sweep_draws_every_open_track_and_is_silent(self):
        self.write_goal(goal(self.issues))
        for _ in range(2):
            r = subprocess.run([sys.executable, str(GOAL_GRAPH), "sweep"], env=self.env(),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            self.assertIn(goal_graph.START, self.text())

    def test_a_claim_shows_the_worker_at_once(self):
        self.write_goal(goal(self.issues))
        self.update()
        r = subprocess.run([sys.executable, str(FRONTIER), "claim", str(self.issues), "03", "Ada"],
                           env=self.env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('t03["03 · A claim updates the graph<br/>Ada"]', self.text())

    def test_the_pulse_draws_the_graph(self):
        sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        (self.cfg / "pm" / ".boss-sessions").mkdir()
        (self.cfg / "pm" / ".boss-sessions" / sid).write_text(TRACK + "\n")
        (self.cfg / "sessions").mkdir()
        meminfo = self.cfg / "meminfo"
        meminfo.write_text("MemAvailable:   67108864 kB\n")
        self.write_goal(goal(self.issues))
        payload = {"session_id": sid, "hook_event_name": "Stop", "stop_hook_active": False}
        r = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                           env=dict(self.env(), BOSS_MEMINFO=str(meminfo)),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('t03["03 · A claim updates the graph<br/>ready"]', self.text())

    def test_a_bad_call_prints_the_usage(self):
        r = subprocess.run([sys.executable, str(GOAL_GRAPH), "bogus"], env=self.env(),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("goal_graph.py sweep", r.stderr)


if __name__ == "__main__":
    unittest.main()
