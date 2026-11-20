#!/usr/bin/env python3
"""Tests for park.py and boss-park: why an idle worker is idle, and the event that ends it.

Run: python3 skills/boss/test_park.py

Every case points the config directory at its own throwaway directory.
"""
import json
import os
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


def gh_json(state="OPEN", runs=()):
    """What `gh pr view --json state,statusCheckRollup` prints: `runs` are CheckRun statuses."""
    return json.dumps({"state": state, "statusCheckRollup": [
        {"__typename": "CheckRun", "status": r, "conclusion": "SUCCESS" if r == "COMPLETED" else ""}
        for r in runs]})


class FakeGh:
    """A stand-in for park.gh_run: one canned answer per call, every call counted."""
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, args, timeout):
        self.calls.append(args)
        ans = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(ans, Exception):
            raise ans
        return ans


class GithubEvents(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="park-gh-"))
        self.addCleanup(shutil.rmtree, self.cfg, True)

    def lookup(self, gh, now=NOW):
        return park.pr_lookup("demo", now=now, cfg=self.cfg, run=gh)

    def p(self, event):
        return park.Park("Ada", event, NOW - 60)

    def test_the_two_github_events_parse(self):
        self.assertEqual(park.parse_event("pr:acme/app#5-merged"), ("pr", "acme/app#5-merged"))
        self.assertEqual(park.parse_event("ci:acme/app#5"), ("ci", "acme/app#5"))

    def test_a_github_event_needs_its_exact_form(self):
        for text in ("pr:acme/app#5", "pr:5-merged", "pr:acme/app#-merged", "ci:acme/app",
                     "ci:acme/app#5-merged", "ci:5", "ci:acme/app#x", "ci:-x/app#5", "ci:acme/--upload-pack#5"):
            with self.assertRaises(ValueError, msg=text) as cm:
                park.parse_event(text)
            self.assertIn("ci:<owner/repo#N>", str(cm.exception))

    def test_a_park_on_a_merged_pr_wakes_and_on_an_open_pr_holds(self):
        ev = self.p("pr:acme/app#5-merged")
        open_ = park.World(prs=self.lookup(FakeGh(gh_json("OPEN", ["COMPLETED"]))))
        self.assertEqual(park.state(ev, NOW, open_), "waiting")
        merged = park.World(prs=self.lookup(FakeGh(gh_json("MERGED", ["COMPLETED"])), now=NOW + 90))
        self.assertEqual(park.state(ev, NOW, merged), "over")

    def test_a_closed_unmerged_pr_wakes_too_since_it_will_not_merge(self):
        w = park.World(prs=self.lookup(FakeGh(gh_json("CLOSED"))))
        self.assertEqual(park.state(self.p("pr:acme/app#5-merged"), NOW, w), "over")

    def test_a_park_on_ci_wakes_when_every_check_run_of_the_head_has_concluded(self):
        ev = self.p("ci:acme/app#5")
        running = park.World(prs=self.lookup(FakeGh(gh_json("OPEN", ["COMPLETED", "IN_PROGRESS"]))))
        self.assertEqual(park.state(ev, NOW, running), "waiting")
        queued = park.World(prs=self.lookup(FakeGh(gh_json("OPEN", ["QUEUED"])), now=NOW + 90))
        self.assertEqual(park.state(ev, NOW, queued), "waiting")
        done = park.World(prs=self.lookup(FakeGh(gh_json("OPEN", ["COMPLETED", "COMPLETED"])),
                                          now=NOW + 200))
        self.assertEqual(park.state(ev, NOW, done), "over")

    def test_no_check_run_yet_is_not_finished_ci(self):
        w = park.World(prs=self.lookup(FakeGh(gh_json("OPEN", []))))
        self.assertEqual(park.state(self.p("ci:acme/app#5"), NOW, w), "waiting")

    def test_a_pending_commit_status_is_not_finished_ci(self):
        out = json.dumps({"state": "OPEN", "statusCheckRollup": [
            {"__typename": "StatusContext", "state": "PENDING"}]})
        w = park.World(prs=self.lookup(FakeGh(out)))
        self.assertEqual(park.state(self.p("ci:acme/app#5"), NOW, w), "waiting")

    def test_a_pr_merged_under_a_ci_park_wakes_it(self):
        w = park.World(prs=self.lookup(FakeGh(gh_json("MERGED", ["IN_PROGRESS"]))))
        self.assertEqual(park.state(self.p("ci:acme/app#5"), NOW, w), "over")

    def test_stops_within_a_minute_make_no_new_gh_call_for_the_same_pr(self):
        gh = FakeGh(gh_json("OPEN", ["IN_PROGRESS"]))
        for dt in (0, 10, 59):
            self.assertEqual(self.lookup(gh, NOW + dt)("acme/app", 5)["state"], "OPEN")
        self.assertEqual(len(gh.calls), 1)
        self.lookup(gh, NOW + 61)("acme/app", 5)
        self.assertEqual(len(gh.calls), 2)
        self.lookup(gh, NOW + 61)("acme/app", 6)                # another PR: its own call
        self.assertEqual(len(gh.calls), 3)

    def test_the_cache_belongs_to_one_track(self):
        gh = FakeGh(gh_json("OPEN"))
        self.lookup(gh)("acme/app", 5)
        park.pr_lookup("other", now=NOW, cfg=self.cfg, run=gh)("acme/app", 5)
        self.assertEqual(len(gh.calls), 2)

    def test_a_gh_failure_keeps_the_park_and_logs_it(self):
        gh = FakeGh(OSError("no network"))
        w = park.World(prs=self.lookup(gh))
        self.assertEqual(park.state(self.p("ci:acme/app#5"), NOW, w), "waiting")
        self.assertEqual(park.state(self.p("pr:acme/app#5-merged"), NOW, w), "waiting")
        log = (self.cfg / "pm" / "park-gh.log").read_text()
        self.assertIn("acme/app#5", log)
        self.assertIn("no network", log)

    def test_a_failed_call_is_not_repeated_within_the_minute(self):
        gh = FakeGh(OSError("offline"))
        for dt in (0, 5, 30):
            self.assertIsNone(self.lookup(gh, NOW + dt)("acme/app", 5))
        self.assertEqual(len(gh.calls), 1)

    def test_output_gh_could_not_have_written_is_a_failure_not_a_crash(self):
        for i, bad in enumerate(("", "not json", "[]", json.dumps({"state": 7}), json.dumps({"nostate": 1}))):
            gh = FakeGh(bad)
            self.assertIsNone(self.lookup(gh, now=NOW + 100 * i)("acme/app", 5), bad)
            self.assertEqual(len(gh.calls), 1, bad)         # each one really was parsed

    def test_a_call_that_times_out_is_a_failure_too(self):
        gh = FakeGh(subprocess.TimeoutExpired("gh", 3))
        self.assertIsNone(self.lookup(gh)("acme/app", 5))

    def test_without_a_lookup_a_github_park_holds(self):
        self.assertEqual(park.state(self.p("ci:acme/app#5"), NOW, park.World()), "waiting")

    def test_the_gh_call_names_the_repo_and_asks_only_for_state_and_checks(self):
        gh = FakeGh(gh_json("OPEN"))
        self.lookup(gh)("acme/app", 5)
        self.assertEqual(gh.calls[0], ["pr", "view", "5", "--repo", "acme/app",
                                       "--json", "state,statusCheckRollup"])


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
        self.assertNotIn("Ada", park.read_parks("demo", self.cfg))
        got = park.read_parks("demo", self.cfg)["retired:Ada"]
        self.assertEqual((got.worker, got.event, got.since), ("Ada", "ticket:12", NOW))
        self.assertTrue(got.retired)

    def test_a_second_retire_under_the_same_name_refuses_and_keeps_the_first(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        park.retire("demo", "Ada", self.cfg)
        park.set_park("demo", "Ada", "ticket:13", now=NOW + 1, cfg=self.cfg)
        with self.assertRaises(ValueError):
            park.retire("demo", "Ada", self.cfg)
        parks = park.read_parks("demo", self.cfg)
        self.assertEqual((parks["retired:Ada"].event, parks["Ada"].event), ("ticket:12", "ticket:13"))

    def test_a_new_session_with_a_retired_workers_name_leaves_the_kept_park_alone(self):
        park.set_park("demo", "Ada", "ticket:12", now=NOW, cfg=self.cfg)
        park.retire("demo", "Ada", self.cfg)
        park.set_park("demo", "Ada", "ticket:13", now=NOW + 1, cfg=self.cfg)
        self.assertTrue(park.clear("demo", "Ada", self.cfg))          # a dispatch to the new Ada
        self.assertEqual(park.read_parks("demo", self.cfg)["retired:Ada"].event, "ticket:12")
        self.assertTrue(park.clear("demo", "Ada", self.cfg, retired=True))
        self.assertEqual(park.read_parks("demo", self.cfg), {})

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

    def test_the_list_calls_an_owner_park_waiting_when_the_tracker_is_unreadable(self):
        self.assertEqual(self.run_cli("demo", "Ada", "--until", "owner:q7").returncode, 0)
        (self.cfg / "pm" / "demo.md").unlink()
        out = self.run_cli("demo", "--list").stdout
        self.assertIn("waiting", out)
        self.assertNotIn("over", out)

    def test_the_list_expires_an_owner_park_even_when_the_tracker_is_unreadable(self):
        park.set_park("demo", "Ada", "owner:q7", now=1, cfg=self.cfg)
        (self.cfg / "pm" / "demo.md").unlink()
        self.assertIn("expired", self.run_cli("demo", "--list").stdout)

    def test_a_park_that_cannot_be_written_fails_loudly(self):
        (self.cfg / "pm" / ".pulse").write_text("a file where the directory should be")
        r = self.run_cli("demo", "Ada", "--until", "ticket:12")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("parked", r.stdout)
        self.assertIn("boss-park", r.stderr)

    @unittest.skipIf(os.geteuid() == 0, "root ignores the directory mode, so no write fails here")
    def test_a_clear_that_cannot_be_written_fails_loudly(self):
        self.assertEqual(self.run_cli("demo", "Ada", "--until", "ticket:12").returncode, 0)
        f = self.cfg / "pm" / ".pulse"
        f.chmod(0o500)
        self.addCleanup(f.chmod, 0o700)
        r = self.run_cli("demo", "Ada", "--clear")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("cleared", r.stdout)

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

    def test_a_github_park_is_made_from_the_command_line(self):
        r = self.run_cli("demo", "Ada", "--until", "ci:acme/app#5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ci:acme/app#5", self.run_cli("demo", "--list").stdout)
        self.assertEqual(self.run_cli("demo", "Ada", "--until", "pr:acme/app#5-merged").returncode, 0)

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
