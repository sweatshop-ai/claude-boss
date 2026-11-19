#!/usr/bin/env python3
"""Tests for park.py and boss-park: why an idle worker is idle, and the event that ends it.

Run: python3 skills/boss/test_park.py

Every case points the config directory at its own throwaway directory.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin" / "boss-park"
sys.path.insert(0, str(HERE))
import park  # noqa: E402

NOW = 1_800_000_000


class Parse(unittest.TestCase):
    def test_the_three_local_events_parse(self):
        self.assertEqual(park.parse_event("ticket:12"), ("ticket", "12"))
        self.assertEqual(park.parse_event("worker:Ada"), ("worker", "Ada"))
        self.assertEqual(park.parse_event("owner:q7"), ("owner", "q7"))

    def test_an_unknown_kind_is_refused_with_the_allowed_events(self):
        with self.assertRaises(ValueError) as cm:
            park.parse_event("pr-merged:5")
        for kind in ("ticket:<id>", "worker:<name>", "owner:<question id>"):
            self.assertIn(kind, str(cm.exception))

    def test_a_missing_target_is_refused_with_the_allowed_events(self):
        for text in ("ticket", "ticket:", "worker:", "owner: ", ""):
            with self.assertRaises(ValueError, msg=text) as cm:
                park.parse_event(text)
            self.assertIn("ticket:<id>", str(cm.exception))

    def test_a_clock_time_is_not_an_event(self):
        for text in ("14:30", "at:14:30", "time:14:30", "in 2h", "ticket:14:30", "after:5pm"):
            with self.assertRaises(ValueError, msg=text):
                park.parse_event(text)


class Wake(unittest.TestCase):
    def world(self, **kw):
        return park.World(**kw)

    def p(self, event, age_s=60):
        return park.Park("Ada", event, NOW - age_s)

    def test_a_ticket_park_waits_until_the_frontier_reports_it_done(self):
        self.assertEqual(park.state(self.p("ticket:12"), NOW, self.world(done={"11"})), "waiting")
        self.assertEqual(park.state(self.p("ticket:12"), NOW, self.world(done={"12"})), "over")

    def test_ticket_numbers_match_with_or_without_leading_zeros(self):
        self.assertEqual(park.state(self.p("ticket:3"), NOW, self.world(done={"03"})), "over")
        self.assertEqual(park.state(self.p("ticket:03"), NOW, self.world(done={"3"})), "over")

    def test_a_worker_park_wakes_when_that_worker_goes_idle(self):
        w = self.world(workers={"Bea": "busy"})
        self.assertEqual(park.state(self.p("worker:Bea"), NOW, w), "waiting")
        w = self.world(workers={"Bea": "idle"})
        self.assertEqual(park.state(self.p("worker:Bea"), NOW, w), "over")

    def test_a_worker_park_wakes_when_that_worker_is_gone(self):
        self.assertEqual(park.state(self.p("worker:Bea"), NOW, self.world(workers={"Ada": "idle"})),
                         "over")

    def test_an_owner_park_wakes_when_no_open_blocker_names_the_question(self):
        held = self.world(blockers=("- waiting for the org name q7 [ladder id=ab12cd34]",))
        self.assertEqual(park.state(self.p("owner:q7"), NOW, held), "waiting")
        self.assertEqual(park.state(self.p("owner:q7"), NOW, self.world(blockers=("- other, q70",))),
                         "over")
        self.assertEqual(park.state(self.p("owner:q7"), NOW, self.world()), "over")

    def test_a_park_older_than_two_hours_is_expired(self):
        w = self.world(done=set())
        self.assertEqual(park.state(self.p("ticket:12", 2 * 3600 - 1), NOW, w), "waiting")
        self.assertEqual(park.state(self.p("ticket:12", 2 * 3600), NOW, w), "expired")

    def test_an_event_that_happened_beats_the_expiry(self):
        self.assertEqual(park.state(self.p("ticket:12", 5 * 3600), NOW, self.world(done={"12"})),
                         "over")


class Store(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="park-test-"))
        self.addCleanup(shutil.rmtree, self.cfg, True)

    def test_a_park_is_kept_with_its_start_time(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        self.assertEqual(park.read_parks("demo", self.cfg),
                         {"Ada": park.Park("Ada", "ticket:12", NOW)})

    def test_parking_again_replaces_the_park_and_restarts_the_clock(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        park.set_park("demo", "Ada", "worker:Bea", now=NOW + 5, cfg=self.cfg)
        self.assertEqual(park.read_parks("demo", self.cfg),
                         {"Ada": park.Park("Ada", "worker:Bea", NOW + 5)})

    def test_clear_drops_one_park_and_says_whether_there_was_one(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        park.set_park("demo", "Bea", "ticket:13", now=NOW, cfg=self.cfg)
        self.assertTrue(park.clear("demo", "Ada", self.cfg))
        self.assertFalse(park.clear("demo", "Ada", self.cfg))
        self.assertEqual(list(park.read_parks("demo", self.cfg)), ["Bea"])

    def test_retire_keeps_the_event_and_marks_the_park(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        self.assertTrue(park.retire("demo", "Ada", self.cfg))
        self.assertFalse(park.retire("demo", "Bea", self.cfg))
        got = park.read_parks("demo", self.cfg)["Ada"]
        self.assertEqual((got.event, got.since, got.retired), ("ticket:12", NOW, True))
        park.set_park("demo", "Ada", "ticket:13", now=NOW + 1, cfg=self.cfg)   # a new park is not retired
        self.assertFalse(park.read_parks("demo", self.cfg)["Ada"].retired)

    def test_a_torn_or_foreign_file_reads_as_no_parks(self):
        f = park.boss_store.parks_path("demo", self.cfg)
        f.parent.mkdir(parents=True)
        f.write_text("{not json")
        self.assertEqual(park.read_parks("demo", self.cfg), {})
        f.write_text(json.dumps({"Ada": {"event": "ticket:1"}, "Bea": "x", "Cy": {
            "event": "ticket:2", "since": 5}}))
        self.assertEqual(list(park.read_parks("demo", self.cfg)), ["Cy"])

    def test_parks_belong_to_one_track(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        self.assertEqual(park.read_parks("other", self.cfg), {})


class Cli(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="park-cli-"))
        self.addCleanup(shutil.rmtree, self.cfg, True)
        (self.cfg / "pm").mkdir()
        (self.cfg / "pm" / "demo.md").write_text(
            "# T\n\n## Open blockers\n- the org name q7\n\n## Decisions\n")

    def run_cli(self, *args):
        env = {"CLAUDE_CONFIG_DIR": str(self.cfg), "PATH": "/usr/bin:/bin"}
        return subprocess.run([str(BIN), *args], env=env, capture_output=True, text=True, timeout=20)

    def test_park_list_and_clear(self):
        r = self.run_cli("demo", "Ada", "--until", "ticket:12")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("demo", "--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ada", r.stdout)
        self.assertIn("ticket:12", r.stdout)
        r = self.run_cli("demo", "Ada", "--clear")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Ada", self.run_cli("demo", "--list").stdout)

    def test_a_bad_event_exits_2_and_lists_the_allowed_ones(self):
        r = self.run_cli("demo", "Ada", "--until", "14:30")
        self.assertEqual(r.returncode, 2)
        self.assertIn("worker:<name>", r.stderr)
        self.assertEqual(self.run_cli("demo", "--list").stdout.strip(), "no parks")

    def test_a_missing_target_exits_2(self):
        r = self.run_cli("demo", "Ada", "--until", "ticket:")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ticket:<id>", r.stderr)

    def test_an_owner_park_needs_the_question_open_in_the_tracker(self):
        self.assertEqual(self.run_cli("demo", "Ada", "--until", "owner:q7").returncode, 0)
        r = self.run_cli("demo", "Ada", "--until", "owner:q9")
        self.assertEqual(r.returncode, 2)
        self.assertIn("q9", r.stderr)

    def test_a_track_that_is_no_plain_name_is_refused(self):
        self.assertEqual(self.run_cli("../x", "Ada", "--until", "ticket:1").returncode, 2)

    def test_the_list_marks_an_expired_park(self):
        park.set_park("demo", "Ada", "ticket:12", now=1, cfg=self.cfg)
        self.assertIn("expired", self.run_cli("demo", "--list").stdout)

    def test_the_list_does_not_call_a_worker_park_over_for_want_of_a_fleet(self):
        park.set_park("demo", "Ada", "worker:Bea", cfg=self.cfg)
        self.assertIn("waiting", self.run_cli("demo", "--list").stdout)

    def test_a_worker_name_with_odd_characters_is_refused(self):
        self.assertEqual(self.run_cli("demo", "a b;c", "--until", "ticket:1").returncode, 2)


if __name__ == "__main__":
    unittest.main()
