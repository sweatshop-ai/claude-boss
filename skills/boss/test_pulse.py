#!/usr/bin/env python3
"""Tests for pulse.py — what the pulse tells a boss, decided before it is worded.

Run: python3 skills/boss/test_pulse.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pulse  # noqa: E402


class Decide(unittest.TestCase):
    def test_a_busy_team_with_nothing_due_is_left_alone(self):
        self.assertIsNone(pulse.decide(pulse.Facts(track="demo")))

    def test_an_open_blocker_comes_first_as_a_question(self):
        d = pulse.decide(pulse.Facts(track="demo", blockers=["- waiting on the org"],
                                     idle=[("Ada", "w:1.0")]))
        self.assertEqual(kinds(d), ["ask", "dispatch-next", "refill-next"])

    def test_ready_tickets_beyond_the_idle_workers_ask_for_that_many_more(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=2, ready=["01 API", "02 UI", "03 Docs"]))
        self.assertEqual(d.actions, [pulse.Action("dispatch-ready"), pulse.Action("spawn", 2)])

    def test_the_spawn_stops_at_the_span(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=10,
                                     ready=["%02d T" % n for n in range(5)]))
        self.assertEqual(d.actions, [pulse.Action("spawn", 2)])

    def test_a_full_team_dispatches_without_growing(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=12, ready=["01 API", "02 UI"]))
        self.assertEqual(kinds(d), ["dispatch-ready"])

    def test_nothing_ready_and_nobody_idle_is_silence(self):
        self.assertIsNone(pulse.decide(pulse.Facts(track="demo", source="issues", size=3)))

    def test_with_a_ticket_graph_next_is_not_handed_out(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=1))
        self.assertEqual(kinds(d), [])

    def test_a_broken_graph_is_fixed_before_anything_is_dispatched(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     ready=["01 API", "02 UI"], broken="cycle"))
        self.assertEqual(kinds(d), ["fix-graph"])

    def test_a_broken_graph_speaks_even_with_nobody_idle(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, broken="cycle"))
        self.assertEqual(kinds(d), ["fix-graph"])

    def test_a_due_rung_is_run_last_and_marked_fired(self):
        rungs = [("ka", 60, 100, "- A blocked"), ("kb", 15, 20, "- B blocked")]
        d = pulse.decide(pulse.Facts(track="demo", rungs=rungs, fired={"old": 120},
                                     blockers=["- A blocked", "- B blocked"]))
        self.assertEqual(d.actions, [pulse.Action("ask"), pulse.Action("run-rung", 60)])
        self.assertEqual(d.fired, {"old": 120, "ka": 60, "kb": 15})

    def test_only_the_three_rungs_shown_are_marked(self):
        rungs = [("k%d" % i, 15, 20, "- %d" % i) for i in range(4)]
        d = pulse.decide(pulse.Facts(track="demo", rungs=rungs))
        self.assertEqual(d.overdue, rungs[:3])
        self.assertEqual(sorted(d.fired), ["k0", "k1", "k2"])

    def test_the_facts_are_not_changed_by_deciding(self):
        fired = {"old": 120}
        pulse.decide(pulse.Facts(track="demo", rungs=[("ka", 60, 100, "- A")], fired=fired))
        self.assertEqual(fired, {"old": 120})


class Render(unittest.TestCase):
    def say(self, **facts):
        f = pulse.Facts(track="demo", **facts)
        return pulse.render(f, pulse.decide(f)).splitlines()

    def test_the_actions_are_numbered_in_the_order_decided(self):
        lines = self.say(blockers=["- waiting on the org"], source="issues", size=2,
                         ready=["01 API", "02 UI"])
        self.assertTrue(lines[0].startswith("[boss pulse - track `demo`]"))
        self.assertIn("BLOCKED, and you are ending your turn without asking: "
                      "- waiting on the org", lines)
        self.assertTrue([x for x in lines if x.startswith("1. **Ask the owner")])
        self.assertIn("2. Spawn 2 more workers (team 2 of 12) and dispatch the "
                      "remaining READY tickets to them.", lines)

    def test_each_overdue_rung_is_named_and_the_first_is_run(self):
        lines = self.say(rungs=[("ka", 60, 100, "- A blocked"), ("kb", 15, 20, "- B")])
        self.assertIn("OVERDUE: blocker open 100 min, rung 60 due - - A blocked", lines)
        self.assertIn("OVERDUE: blocker open 20 min, rung 15 due - - B", lines)
        self.assertIn('1. Run the due rung: `boss-alert 60 "<one action, where, '
                      'what it costs>"`.', lines)

    def test_the_objective_comes_before_the_team(self):
        lines = self.say(idle=[("Ada", "w:1.0")], outcome="Ship it.\nmore",
                         unmet=["- [ ] it ships"], next=["- do a thing"])
        self.assertEqual(lines[2:7], ["OUTCOME: Ship it.", "NOT YET MET:", "  - [ ] it ships",
                                      "NEXT, in priority order:", "  - do a thing"])
        self.assertIn("IDLE NOW, yours: Ada (w:1.0)", lines)


def kinds(decision):
    return [a.kind for a in decision.actions]


if __name__ == "__main__":
    unittest.main(verbosity=2)
