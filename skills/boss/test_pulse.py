#!/usr/bin/env python3
"""Tests for pulse.py — what the pulse tells a boss, decided before it is worded.

Run: python3 skills/boss/test_pulse.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy  # noqa: E402
import pulse  # noqa: E402

R = pulse.Rung
W = pulse.Woken


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

    def test_twenty_ready_and_two_idle_ask_for_eighteen_spawns(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=14,
                                     idle=[("Ada", "w:1.0"), ("Bo", "w:1.1")],
                                     ready=["%02d T" % n for n in range(20)]))
        self.assertEqual(d.actions, [pulse.Action("dispatch-ready"), pulse.Action("spawn", 18)])

    def test_a_workers_line_with_a_reason_caps_the_spawn(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=1, cap=3,
                                     cap_reason="one change at a time",
                                     ready=["%02d T" % n for n in range(20)]))
        self.assertEqual(d.actions, [pulse.Action("spawn", 2)])

    def test_a_track_at_its_cap_gets_no_spawn_pulse(self):
        # the merge desk: capped at 3, it was told "spawn 6" in 51 pulses
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, cap=3,
                                     cap_reason="one at a time",
                                     ready=["%02d T" % n for n in range(9)]))
        self.assertIsNone(d)

    def test_a_zero_cap_with_a_reason_spawns_nothing(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=0, cap=0,
                                     cap_reason="paused", ready=["01 T"]))
        self.assertIsNone(d)

    def test_a_cap_without_a_reason_does_not_cap(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, cap=3,
                                     ready=["%02d T" % n for n in range(9)]))
        self.assertEqual(d.actions, [pulse.Action("spawn", 9)])

    def test_nothing_ready_and_nobody_idle_is_silence(self):
        self.assertIsNone(pulse.decide(pulse.Facts(track="demo", source="issues", size=3)))

    def test_with_a_ticket_graph_and_no_next_nothing_is_handed_out(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=1))
        self.assertEqual(kinds(d), [])

    def test_ready_tickets_go_out_before_next(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=1, ready=["01 API"], next_items=["- side fix"]))
        self.assertEqual(kinds(d), ["dispatch-ready"])

    def test_a_graph_with_nothing_ready_falls_back_to_next(self):
        # 2026-10-30, track action-list: the graph's open tickets all waited on a
        # person, so READY was "none" in 155 pulses while NEXT held four side
        # tickets nobody needed to unblock. The boss answered "parked on purpose"
        # 174 times and four workers sat idle until the owner noticed.
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=1, next_items=["- #188 fix the reopen"]))
        self.assertEqual(kinds(d), ["dispatch-next", "refill-next"])

    def test_a_broken_graph_is_fixed_before_anything_is_dispatched(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     ready=["01 API", "02 UI"], broken="cycle"))
        self.assertEqual(kinds(d), ["fix-graph"])

    def test_a_broken_graph_speaks_even_with_nobody_idle(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, broken="cycle"))
        self.assertEqual(kinds(d), ["fix-graph"])

    def test_a_woken_worker_is_a_reason_to_speak_and_comes_before_the_dispatch(self):
        d = pulse.decide(pulse.Facts(track="demo", idle=[("Ada", "w:1.0")],
                                     parks=[W("Ada", "ticket:12", "over", 30)]))
        self.assertEqual(kinds(d), ["wake", "dispatch-next", "refill-next"])

    def test_a_woken_worker_with_nothing_to_hand_out_still_speaks(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=1, parks=[W("Ada", "ticket:12", "over", 30)]))
        self.assertEqual(kinds(d), ["wake"])

    def test_a_due_rung_is_run_last_and_marked_fired(self):
        rungs = [R("ka", 60, 100, "- A blocked"), R("kb", 15, 20, "- B blocked")]
        d = pulse.decide(pulse.Facts(track="demo", rungs=rungs, fired={"old": 120},
                                     blockers=["- A blocked", "- B blocked"]))
        self.assertEqual(d.actions, [pulse.Action("ask"), pulse.Action("run-rung", 60)])
        self.assertEqual(d.fired, {"old": 120, "ka": 60, "kb": 15})

    def test_only_the_three_rungs_shown_are_marked(self):
        rungs = [R("k%d" % i, 15, 20, "- %d" % i) for i in range(4)]
        d = pulse.decide(pulse.Facts(track="demo", rungs=rungs))
        self.assertEqual(d.overdue, rungs[:3])
        self.assertEqual(sorted(d.fired), ["k0", "k1", "k2"])

    def test_the_facts_are_not_changed_by_deciding(self):
        fired = {"old": 120}
        pulse.decide(pulse.Facts(track="demo", rungs=[R("ka", 60, 100, "- A")], fired=fired))
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
        self.assertIn("2. Spawn 2 more workers (team 2 now, no worker limit; the spawn "
                      "refuses below %d GB free memory) and dispatch the remaining READY "
                      "tickets to them." % policy.MEMORY_FLOOR_GB, lines)

    def test_a_capped_spawn_line_gives_the_reason(self):
        lines = self.say(source="issues", size=1, cap=3, cap_reason="one change at a time",
                         ready=["01 API", "02 UI", "03 Docs"])
        self.assertIn("1. Spawn 2 more workers (team 3 of 3: one change at a time) and "
                      "dispatch the remaining READY tickets to them.", lines)

    def test_a_cap_without_a_reason_is_ignored_with_a_note(self):
        lines = self.say(source="issues", size=1, cap=3, ready=["01 API", "02 UI"])
        self.assertIn("NOTE: `Workers: 3` in the goal file is ignored: it needs a reason "
                      "(`Workers: 3 - <reason>`).", lines)

    def test_each_overdue_rung_is_named_and_the_first_is_run(self):
        lines = self.say(rungs=[R("ka", 60, 100, "- A blocked"), R("kb", 15, 20, "- B")])
        self.assertIn("OVERDUE: blocker open 100 min, rung 60 due - - A blocked", lines)
        self.assertIn("OVERDUE: blocker open 20 min, rung 15 due - - B", lines)
        self.assertIn('1. Run the due rung: `boss-alert 60 "<one action, where, '
                      'what it costs>"`.', lines)

    def test_the_objective_comes_before_the_team(self):
        lines = self.say(idle=[("Ada", "w:1.0")], outcome="Ship it.\nmore",
                         unmet=["- [ ] it ships"], next_items=["- do a thing"])
        self.assertEqual(lines[2:7], ["OUTCOME: Ship it.", "NOT YET MET:", "  - [ ] it ships",
                                      "NEXT, in priority order:", "  - do a thing"])
        self.assertIn("IDLE NOW, yours: Ada (w:1.0)", lines)

    def test_a_graph_with_nothing_ready_still_shows_next(self):
        lines = self.say(idle=[("Ada", "w:1.0")], source="issues",
                         next_items=["- #188 fix the reopen"])
        self.assertIn("READY NOW: none", lines)
        self.assertIn("NEXT, in priority order:", lines)
        self.assertIn("  - #188 fix the reopen", lines)

    def test_prose_is_no_park_and_the_command_is_named(self):
        text = "\n".join(self.say(idle=[("Ada", "w:1.0")]))
        self.assertIn("`boss-park demo <worker> --until <event>`", text)
        self.assertIn("\"parked on purpose\" in words is not a park", text)

    def test_a_woken_worker_is_told_its_wait_is_over(self):
        lines = self.say(idle=[("Ada", "w:1.0"), ("Bea", "w:1.1"), ("Cy", "w:1.2")],
                         parks=[W("Ada", "ticket:12", "over", 30),
                                W("Bea", "worker:Cy", "over", 5),
                                W("Cy", "owner:q7", "over", 61)])
        self.assertIn("Ada's wait is over (ticket 12 done): dispatch it", lines)
        self.assertIn("Bea's wait is over (Cy finished): dispatch it", lines)
        self.assertIn("Cy's wait is over (q7 answered): dispatch it", lines)

    def test_an_expired_park_says_how_long_and_on_what(self):
        lines = self.say(idle=[("Ada", "w:1.0")], parks=[W("Ada", "ticket:12", "expired", 125)])
        self.assertIn("Ada has waited 2 h on ticket:12: dispatch, re-park or retire", lines)


def kinds(decision):
    return [a.kind for a in decision.actions]


if __name__ == "__main__":
    unittest.main(verbosity=2)
