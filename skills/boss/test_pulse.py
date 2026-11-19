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
SHORT = ("not spawning: 6.0 GB free, a new worker costs about 1.0 GB, and the 8 GB floor "
         "would not hold (5.0 GB left)")


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

    def test_a_cap_with_a_reason_also_caps_the_spawn_for_next_items(self):
        d = pulse.decide(pulse.Facts(track="demo", size=1, cap=2, cap_reason="one at a time",
                                     workers=("Ada",), next_items=["- a", "- b", "- c", "- d"]))
        self.assertEqual(d.actions, [pulse.Action("spawn-next", 1)])

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

    def test_next_with_five_items_two_marked_has_three_unassigned(self):
        items = ["1. a (→ Ada)", "2. b", "3. c (→ Bo)", "4. d", "   wrapped line of d", "5. e"]
        self.assertEqual(pulse.unassigned(items, ["Ada", "Bo"]),
                         (["2. b", "4. d wrapped line of d", "5. e"], []))

    def test_a_mark_naming_an_idle_worker_is_unassigned_but_not_gone(self):
        items = ["1. a (→ Ada)", "2. b (→ Bo)"]
        self.assertEqual(pulse.unassigned(items, ["Ada", "Bo"], idle=["Ada"]),
                         (["1. a (→ Ada)"], []))

    def test_an_idle_worker_with_every_item_marked_to_itself_is_still_dispatched(self):
        d = pulse.decide(pulse.Facts(track="demo", size=1, idle=[("Ada", "w:1.0")],
                                     workers=("Ada",), next_items=["- a (→ Ada)"]))
        self.assertEqual(kinds(d), ["dispatch-next", "refill-next"])

    def test_a_mark_on_a_wrapped_line_belongs_to_its_item(self):
        items = ["1. a long item", "   that wraps (→ Ada)", "2. b"]
        self.assertEqual(pulse.unassigned(items, ["Ada"]), (["2. b"], []))

    def test_a_typed_arrow_and_a_list_of_workers_are_read(self):
        items = ["1. a (-> Ada)", "2. b (→ Ada, Bo)", "3. c (→ Ada, Zed)"]
        self.assertEqual(pulse.unassigned(items, ["Ada", "Bo"]), (["3. c (→ Ada, Zed)"], ["Zed"]))

    def test_a_mark_naming_a_retired_worker_is_unassigned_and_named(self):
        items = ["1. a (→ Ada)", "2. b (→ Zed)"]
        self.assertEqual(pulse.unassigned(items, ["Ada"]), (["2. b (→ Zed)"], ["Zed"]))

    def test_no_idle_worker_and_three_unassigned_items_ask_for_three_spawns(self):
        d = pulse.decide(pulse.Facts(track="demo", size=2, workers=("Ada", "Bo"),
                                     next_items=["- a (→ Ada)", "- b (→ Bo)", "- c", "- d", "- e"]))
        self.assertEqual(d.actions, [pulse.Action("spawn-next", 3)])

    def test_the_idle_workers_take_unassigned_items_before_a_spawn(self):
        d = pulse.decide(pulse.Facts(track="demo", size=2, idle=[("Ada", "w:1.0")],
                                     workers=("Ada", "Bo"),
                                     next_items=["- a", "- b (→ Bo)", "- c"]))
        self.assertEqual(d.actions, [pulse.Action("dispatch-next"), pulse.Action("spawn-next", 1)])

    def test_next_with_every_item_marked_to_a_live_worker_is_silence(self):
        self.assertIsNone(pulse.decide(pulse.Facts(
            track="demo", size=2, workers=("Ada", "Bo"), next_items=["- a (→ Ada)", "- b (→ Bo)"])))

    def test_marked_items_do_not_make_the_pulse_ask_to_refill_next(self):
        d = pulse.decide(pulse.Facts(track="demo", size=2, idle=[("Ada", "w:1.0")],
                                     workers=("Ada", "Bo"), next_items=["- a", "- b (→ Bo)"]))
        self.assertEqual(kinds(d), ["dispatch-next"])

    def test_stale_marks_alone_do_not_silence_the_refill(self):
        d = pulse.decide(pulse.Facts(track="demo", size=1, idle=[("Ada", "w:1.0")],
                                     workers=("Ada",), next_items=["- a (→ Zed)"]))
        self.assertEqual(kinds(d), ["dispatch-next", "refill-next"])

    def test_a_next_of_plain_prose_still_goes_to_an_idle_worker(self):
        d = pulse.decide(pulse.Facts(track="demo", size=1, idle=[("Ada", "w:1.0")],
                                     workers=("Ada",), next_items=["Fix the reopen bug"]))
        self.assertEqual(kinds(d), ["dispatch-next", "refill-next"])

    def test_an_unreadable_roster_does_not_ask_for_spawns(self):
        self.assertIsNone(pulse.decide(pulse.Facts(track="demo", next_items=["- a", "- b"])))

    def test_with_a_graph_the_marks_are_ignored(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=1, workers=("Ada",),
                                     next_items=["- a", "- b", "- c"]))
        self.assertIsNone(d)
        d = pulse.decide(pulse.Facts(track="demo", source="issues", idle=[("Ada", "w:1.0")],
                                     size=1, workers=("Ada",), next_items=["- a (→ Ada)"]))
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

    def test_a_refused_spawn_retires_the_worker_parked_longest(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, memshort=SHORT,
                                     ready=["01 API", "02 UI"],
                                     parked=[W("Ada", "ticket:12", "waiting", 20),
                                             W("Bea", "owner:q7", "waiting", 90)]))
        self.assertEqual(d.actions, [pulse.Action("retire-parked", 2)])
        self.assertEqual(pulse.longest_parked(pulse.Facts(
            track="demo", parked=[W("Ada", "ticket:12", "waiting", 20), W("Bea", "owner:q7", "waiting", 90)])).worker, "Bea")

    def test_an_expired_or_over_park_is_dispatched_never_retired(self):
        # such a worker is idle already: retiring it frees nothing the spawn needs
        f = pulse.Facts(track="demo", parked=[W("Ada", "ticket:12", "waiting", 20)],
                        parks=[W("Bea", "ticket:9", "expired", 125), W("Cy", "ticket:3", "over", 300)])
        self.assertEqual(pulse.longest_parked(f).worker, "Ada")
        self.assertIsNone(pulse.longest_parked(pulse.Facts(track="demo", parks=f.parks)))

    def test_a_retired_workers_park_ending_says_to_hand_its_work_on(self):
        lines = pulse.render(*(lambda f: (f, pulse.decide(f)))(pulse.Facts(
            track="demo", parks=[W("Bea", "ticket:9", "retired", 30)]))).splitlines()
        self.assertTrue([x for x in lines if x.startswith("Bea was retired for memory")
                         and "`boss-park demo Bea --clear --retired`" in x])

    def test_a_refused_spawn_that_speaks_for_another_reason_says_why_nobody_is_started(self):
        f = pulse.Facts(track="demo", source="issues", size=3, memshort=SHORT,
                        ready=["01 API", "02 UI"], idle=[("Ada", "w:1.0")])
        text = pulse.render(f, pulse.decide(f))
        self.assertIn("MEMORY: " + SHORT, text)
        self.assertIn("start nobody", text)
        self.assertNotIn("Spawn", text)

    def test_a_refused_spawn_with_nobody_parked_starts_nobody_and_does_not_speak(self):
        f = pulse.Facts(track="demo", source="issues", size=3, memshort=SHORT, ready=["01 API"])
        self.assertIsNone(pulse.decide(f))
        self.assertEqual(pulse.shortfall(f), SHORT)

    def test_a_refused_spawn_still_dispatches_to_the_idle_and_asks(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, memshort=SHORT,
                                     blockers=["- q7"], idle=[("Ada", "w:1.0")],
                                     ready=["01 API", "02 UI"]))
        self.assertEqual(kinds(d), ["ask", "dispatch-ready"])

    def test_enough_memory_leaves_the_spawn_alone(self):
        d = pulse.decide(pulse.Facts(track="demo", source="issues", size=3, ready=["01 API"],
                                     parked=[W("Bea", "owner:q7", "waiting", 90)]))
        self.assertEqual(d.actions, [pulse.Action("spawn", 1)])

    def test_no_spawn_wanted_means_no_shortfall(self):
        f = pulse.Facts(track="demo", source="issues", size=3, memshort=SHORT, ready=["01 API"],
                        idle=[("Ada", "w:1.0")])
        self.assertIsNone(pulse.shortfall(f))

    def test_a_refused_spawn_for_next_items_retires_the_longest_parked_too(self):
        facts = dict(track="demo", size=2, workers=("Ada",), memshort=SHORT,
                     next_items=["- one", "- two"],
                     parked=[W("Bea", "owner:q7", "waiting", 90)])
        d = pulse.decide(pulse.Facts(**facts))
        self.assertEqual(kinds(d), ["retire-parked"])
        facts["parked"] = ()
        self.assertIsNone(pulse.decide(pulse.Facts(**facts)))


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

    def test_unassigned_items_and_gone_workers_are_said(self):
        lines = self.say(size=1, workers=("Ada",),
                         next_items=["- a (→ Ada)", "- b (→ Zed)", "- c"])
        self.assertIn("UNASSIGNED in NEXT: 2 of 3; marks naming a worker that is gone: Zed", lines)
        self.assertIn("1. Spawn up to 2 more workers (team 1 now, no worker limit; the spawn "
                      "refuses below %d GB free memory) and dispatch the unassigned "
                      "NEXT items to them; none for an item that waits on work in progress."
                      % policy.MEMORY_FLOOR_GB, lines)

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

    def test_the_retire_line_names_the_worker_keeps_its_park_and_retries_once(self):
        text = "\n".join(self.say(source="issues", size=3, memshort=SHORT, ready=["01 API", "02 UI"],
                                  parked=[W("Ada", "ticket:12", "waiting", 20),
                                          W("Bea", "owner:q7", "waiting", 135)]))
        self.assertIn(SHORT, text)
        self.assertIn("Bea (parked 2 h 15 min on owner:q7)", text)
        self.assertNotIn("Ada (parked", text)
        self.assertIn("`boss-park demo Bea --retire`", text)
        self.assertIn("Tracker", text)
        self.assertIn("Retry the spawn once", text)
        self.assertIn("start nobody", text)
        self.assertNotIn("Spawn 2", text)


def kinds(decision):
    return [a.kind for a in decision.actions]


if __name__ == "__main__":
    unittest.main(verbosity=2)
