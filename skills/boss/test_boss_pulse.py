#!/usr/bin/env python3
"""Tests for boss-pulse.py, the Stop hook that keeps a boss working.

Run: python3 skills/boss/test_boss_pulse.py

The hook runs the way the harness runs it — as a process, JSON on stdin —
against a throwaway CLAUDE_CONFIG_DIR with no tmux and no live peers, so
`idle_workers()` returns empty without shelling out.
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

PULSE = Path(__file__).resolve().parent / "boss-pulse.py"
TRACK = "demo"


class PulseCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-pulse-test-"))
        for d in ("pm/.boss-sessions", "pm/.pulse", "sessions"):
            (self.tmp / d).mkdir(parents=True)
        self.sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        (self.tmp / "pm/.boss-sessions" / self.sid).write_text(TRACK + "\n")
        self.goal(open_=True)
        self.tracker(blockers="")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def goal(self, open_=True):
        (self.tmp / "pm" / (TRACK + ".goal.md")).write_text(
            "# Objective\n\n_Status: %s_\n\n## Outcome\nShip the thing.\n\n"
            "## Done when\n- [ ] it ships\n\n## Next, in priority order\n- do a thing\n"
            % ("OPEN" if open_ else "MET"), encoding="utf-8")

    def tracker(self, blockers=""):
        (self.tmp / "pm" / (TRACK + ".md")).write_text(
            "# Tracker\n\n## Roster\n| none |\n\n## Open blockers\n%s\n\n## Decisions\n- d\n"
            % blockers, encoding="utf-8")

    def register(self, status="busy", waiting_for=None):
        """This boss's own record in Claude Code's session registry."""
        rec = {"pid": os.getpid(), "sessionId": self.sid, "tmux": "9:@1.%901",
               "name": "Boss", "status": status, "cwd": str(self.tmp)}
        if waiting_for is not None:
            rec["waitingFor"] = waiting_for
        (self.tmp / "sessions" / (self.sid + ".json")).write_text(json.dumps(rec))

    def stop(self, sid=None):
        payload = {"session_id": sid or self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": False}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


class StuckBoss(PulseCase):
    """The failure to kill: the boss ends its turn while blocked, saying nothing."""

    def test_an_open_blocker_at_stop_makes_the_boss_ask(self):
        self.tracker(blockers="- waiting on the owner to pick the org")
        out = self.stop()
        self.assertIn("AskUserQuestion", out)
        self.assertIn("pick the org", out)

    def test_no_blocker_no_pulse(self):
        self.assertEqual(self.stop(), "",
                         "a boss with nothing open must stay silent")

    def test_a_boss_already_asking_is_not_pushed(self):
        """It is visibly waiting. Pushing it again would stack on the dialog."""
        self.tracker(blockers="- waiting on the owner to pick the org")
        self.register(status="waiting", waiting_for="input needed")
        self.assertEqual(self.stop(), "")

    def test_a_permission_prompt_also_counts_as_asking(self):
        self.tracker(blockers="- waiting on the owner to pick the org")
        self.register(status="busy", waiting_for="permission prompt")
        self.assertEqual(self.stop(), "")

    def test_three_blockers_still_produce_one_question(self):
        self.tracker(blockers="- pick the org\n- approve the spend\n- confirm the deploy")
        out = self.stop()
        self.assertIn("One question", out)
        self.assertIn("hold the rest", out)

    def test_a_met_objective_ends_the_pulse(self):
        self.tracker(blockers="- pick the org")
        self.goal(open_=False)
        self.assertEqual(self.stop(), "",
                         "a finished objective must not keep nagging")

    def test_a_stop_hook_already_blocking_is_left_alone(self):
        self.tracker(blockers="- pick the org")
        payload = {"session_id": self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": True}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.stdout.strip(), "")

    def test_background_work_still_running_is_not_a_stuck_boss(self):
        self.tracker(blockers="- pick the org")
        payload = {"session_id": self.sid, "hook_event_name": "Stop",
                   "stop_hook_active": False,
                   "background_tasks": [{"status": "running"}]}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp))
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.stdout.strip(), "")


def ticket(num, title, blocked="None (can start immediately)", status="ready-for-agent",
           claimed=None):
    lines = ["# %s: %s" % (num, title), "", "**Blocked by:** " + blocked, ""]
    if claimed:
        lines += ["**Claimed by:** " + claimed, ""]
    return "\n".join(lines + ["**Status:** " + status, ""])


class Frontier(PulseCase):
    """A goal that names a ticket graph: the pulse hands out the whole frontier."""

    def setUp(self):
        super().setUp()
        self.issues = self.tmp / "issues"
        self.issues.mkdir()

    def goal_with_tickets(self, source):
        (self.tmp / "pm" / (TRACK + ".goal.md")).write_text(
            "# Objective\n\n_Status: OPEN_\n\n## Outcome\nShip the thing.\n\n"
            "## Tickets\n%s\n\n## Next, in priority order\n- do a thing\n" % source,
            encoding="utf-8")

    def test_ready_tickets_beyond_the_team_ask_for_a_spawn(self):
        """Nobody idle, nobody busy, two tickets ready: the team is too small."""
        (self.issues / "01-api.md").write_text(ticket("01", "API"))
        (self.issues / "02-ui.md").write_text(ticket("02", "UI"))
        (self.issues / "03-docs.md").write_text(ticket("03", "Docs", blocked="01, 02"))
        self.goal_with_tickets(self.issues)
        out = self.stop()
        self.assertIn("READY NOW: 01 API; 02 UI", out)
        self.assertNotIn("03 Docs", out.split("READY NOW")[1].splitlines()[0])
        self.assertIn("Spawn 2", out)

    def test_nothing_ready_and_nobody_idle_stays_silent(self):
        (self.issues / "01-api.md").write_text(ticket("01", "API", claimed="Ada 2026-10-21 10:00",
                                                       status="in-progress"))
        (self.issues / "02-ui.md").write_text(ticket("02", "UI", blocked="01"))
        self.goal_with_tickets(self.issues)
        self.assertEqual(self.stop(), "")

    def test_a_broken_graph_is_named_and_nothing_is_dispatched(self):
        (self.issues / "01-api.md").write_text(ticket("01", "API", blocked="02"))
        (self.issues / "02-ui.md").write_text(ticket("02", "UI", blocked="01"))
        self.goal_with_tickets(self.issues)
        out = self.stop()
        self.assertIn("TICKET GRAPH BROKEN", out)
        self.assertIn("cycle", out)
        self.assertNotIn("Spawn", out)


    def cache(self, source):
        import hashlib
        return self.tmp / "pm/.pulse" / ("%s.%s.frontier.json" % (
            TRACK, hashlib.sha1(source.encode()).hexdigest()[:10]))

    def pulse_with_team(self, idle, size):
        """Run main() in-process with a stand-in for the tmux roster."""
        import contextlib
        import importlib.util
        import io
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp)
        try:
            spec = importlib.util.spec_from_file_location("pulse_%d" % time.monotonic_ns(), str(PULSE))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.team = lambda sid: (idle, size)
            payload = {"session_id": self.sid, "hook_event_name": "Stop", "stop_hook_active": False}
            out, stdin = io.StringIO(), sys.stdin
            sys.stdin = io.StringIO(json.dumps(payload))
            try:
                with contextlib.redirect_stdout(out):
                    mod.main()
            finally:
                sys.stdin = stdin
        finally:
            if old is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old
        text = out.getvalue().strip()
        return json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else ""

    def test_every_idle_worker_gets_a_ready_ticket(self):
        for n, name in (("01", "API"), ("02", "UI"), ("03", "Docs")):
            (self.issues / ("%s-x.md" % n)).write_text(ticket(n, name))
        self.goal_with_tickets(self.issues)
        out = self.pulse_with_team([("Ada", "w:1.0"), ("Bo", "w:1.1")], size=2)
        self.assertIn("one ticket per idle worker until the READY list runs out", out)
        self.assertIn("Spawn 1 more worker (team 2 of 12)", out)

    def test_a_full_team_is_not_asked_to_grow(self):
        for n in range(1, 4):
            (self.issues / ("%02d-x.md" % n)).write_text(ticket("%02d" % n, "T%d" % n))
        self.goal_with_tickets(self.issues)
        out = self.pulse_with_team([("Ada", "w:1.0")], size=12)
        self.assertIn("Dispatch the READY tickets", out)
        self.assertNotIn("Spawn", out)

    def test_without_tickets_each_idle_worker_gets_a_next_item(self):
        out = self.pulse_with_team([("Ada", "w:1.0"), ("Bo", "w:1.1")], size=2)
        self.assertIn("one each, top first", out)

    def test_a_github_graph_is_read_from_its_cache(self):
        """GitHub is too slow for a 5 s Stop hook: the pulse reads the last
        `frontier.py --json` it saved, and refreshes it in the background."""
        cache = self.cache("gh:acme/app#10")
        cache.write_text(json.dumps({"tickets": [
            {"num": "11", "title": "API", "state": "ready"},
            {"num": "12", "title": "UI", "state": "claimed"}]}))
        self.goal_with_tickets("gh:acme/app#10")
        out = self.stop()
        self.assertIn("READY NOW: 11 API", out)
        self.assertNotIn("12 UI", out)

    def test_the_first_pulse_on_a_github_graph_reads_it(self):
        fake = self.tmp / "bin"
        fake.mkdir()
        (fake / "gh").write_text("#!/bin/sh\necho '[]'\n")
        (fake / "gh").chmod(0o755)
        self.goal_with_tickets("gh:acme/app#10")
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.tmp),
                   PATH="%s:%s" % (fake, os.environ["PATH"]))
        payload = {"session_id": self.sid, "hook_event_name": "Stop", "stop_hook_active": False}
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("no sub-issues", self.cache("gh:acme/app#10").read_text())
        out = json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TICKET GRAPH BROKEN", out, "the first pulse reads GitHub itself")

    def fake_gh(self, script):
        fake = self.tmp / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "gh").write_text(script)
        (fake / "gh").chmod(0o755)
        return fake

    def pulse_with_path(self, fake, idle=(), size=0):
        path = os.environ["PATH"]
        os.environ["PATH"] = "%s:%s" % (fake, path)
        try:
            return self.pulse_with_team(list(idle), size)
        finally:
            os.environ["PATH"] = path

    def stale_cache(self, source, ready):
        cache = self.cache(source)
        cache.write_text(json.dumps({"tickets": [
            {"num": n, "title": t, "state": "ready"} for n, t in ready]}))
        old = time.time() - 3600
        os.utime(cache, (old, old))
        return cache

    def test_a_stale_cache_is_refreshed_before_it_is_used(self):
        """A worker just closed a blocker: the old cache says nothing is ready."""
        self.stale_cache("gh:acme/app#10", [])
        sub = {"number": 12, "title": "UI", "state": "open", "labels": []}
        fake = self.fake_gh("#!/bin/sh\ncase \"$*\" in *sub_issues*) echo '%s';; *) echo '[]';; esac\n"
                            % json.dumps([sub]))
        self.goal_with_tickets("gh:acme/app#10")
        self.assertIn("READY NOW: 12 UI", self.pulse_with_path(fake))

    def test_a_failed_refresh_keeps_the_last_good_frontier(self):
        cache = self.stale_cache("gh:acme/app#10", [("11", "API")])
        fake = self.fake_gh("#!/bin/sh\necho 'HTTP 502' >&2\nexit 1\n")
        self.goal_with_tickets("gh:acme/app#10")
        out = self.pulse_with_path(fake)
        self.assertIn("READY NOW: 11 API", out)
        self.assertNotIn("BROKEN", out)
        time.sleep(1.5)                       # let any background refresh finish
        self.assertIn('"11"', cache.read_text())

    def test_a_cache_belongs_to_one_source(self):
        self.cache("gh:acme/app#10").write_text(json.dumps({"tickets": [
            {"num": "11", "title": "API", "state": "ready"}]}))
        self.goal_with_tickets("gh:acme/other#5")
        fake = self.tmp / "bin"
        fake.mkdir()
        (fake / "gh").write_text("#!/bin/sh\necho '[]'\n")
        (fake / "gh").chmod(0o755)
        path = os.environ["PATH"]
        os.environ["PATH"] = "%s:%s" % (fake, path)
        try:
            out = self.pulse_with_team([], size=0)
        finally:
            os.environ["PATH"] = path
        self.assertNotIn("11 API", out)
        self.assertIn("acme/other#5 has no sub-issues", out)

    def test_more_idle_workers_than_tickets_stops_at_the_frontier(self):
        (self.issues / "01-x.md").write_text(ticket("01", "API"))
        self.goal_with_tickets(self.issues)
        out = self.pulse_with_team([("Ada", "w:1.0"), ("Bo", "w:1.1")], size=2)
        self.assertIn("one ticket per idle worker until the READY list runs out", out)

    def test_every_idle_worker_up_to_the_span_is_named(self):
        idle = [("W%d" % i, "w:1.%d" % i) for i in range(12)]
        out = self.pulse_with_team(idle, size=12)
        self.assertIn("W11 (w:1.11)", out)


class Marker(PulseCase):
    """The track in the marker becomes a file name. Only a plain name is one."""

    def test_a_track_that_climbs_out_of_pm_is_no_track(self):
        # A goal and tracker planted one level above pm/, reachable as ../evil.
        (self.tmp / "evil.goal.md").write_text(
            "# Objective\n\n_Status: OPEN_\n\n## Next, in priority order\n- x\n", encoding="utf-8")
        (self.tmp / "evil.md").write_text(
            "# Tracker\n\n## Open blockers\n- planted blocker\n", encoding="utf-8")
        (self.tmp / "pm/.boss-sessions" / self.sid).write_text("../evil\n")
        self.assertEqual(self.stop(), "")


class OneTrackerRead(PulseCase):
    """One Stop reads the tracker once, and both consumers see that snapshot."""

    def test_the_tracker_is_read_once_per_stop(self):
        import importlib.util
        import io
        from unittest import mock
        self.tracker(blockers="- Ottilie blocked on OWNER")
        spec = importlib.util.spec_from_file_location("pulse_%d" % time.monotonic_ns(), str(PULSE))
        mod = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp)}):
            spec.loader.exec_module(mod)
            reads = []
            real = mod.boss_store.read_tracker

            def counting(*a, **kw):
                reads.append(a)
                return real(*a, **kw)

            payload = json.dumps({"session_id": self.sid, "hook_event_name": "Stop",
                                  "stop_hook_active": False})
            out = io.StringIO()
            with mock.patch.object(mod.boss_store, "read_tracker", counting), \
                    mock.patch.object(sys, "stdin", io.StringIO(payload)), \
                    mock.patch.object(sys, "stdout", out):
                self.assertEqual(mod.main(), 0)
        self.assertIn("Ottilie blocked on OWNER", out.getvalue())   # the blocker reached the text
        self.assertEqual(len(reads), 1)


class DueRungs(unittest.TestCase):
    """due_rungs() directly: which rung is due, and what counts as already said."""

    def setUp(self):
        import importlib.util
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-pulse-rungs-"))
        (self.tmp / "pm").mkdir()
        # The hook resolves its paths when a function runs, so the variable
        # stays set until tearDown.
        self._old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp)
        spec = importlib.util.spec_from_file_location("pulse_%d" % time.monotonic_ns(), str(PULSE))
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def due(self, minutes_ago, fired):
        t0 = time.localtime(time.time() - minutes_ago * 60)
        line = "- Ottilie blocked on OWNER — T+0 %s" % time.strftime("%Y-%m-%d %H:%M", t0)
        (self.tmp / "pm" / (TRACK + ".md")).write_text(
            "# Tracker\n\n## Open blockers\n%s\n\n## Decisions\n" % line, encoding="utf-8")
        return self.mod.due_rungs(TRACK, fired)

    def test_rung_follows_policy(self):
        (key, rung, _, _), = self.due(100, {})
        self.assertEqual(rung, 60)
        self.assertEqual(self.due(130, {})[0][1], 120)

    def test_a_later_rung_already_fired_holds(self):
        # A state file from the old schedule (5…90…240) holds 90 at T+100,
        # where the policy now says 60: no step back down, no repeat.
        (key, _, _, _), = self.due(100, {})
        self.assertEqual(self.due(100, {key: 90}), [])
        self.assertEqual(self.due(100, {key: 60}), [])
        self.assertEqual(self.due(130, {key: 90})[0][1], 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
