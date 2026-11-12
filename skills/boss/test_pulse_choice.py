#!/usr/bin/env python3
"""Tests for the pulse and the owner's choice on the Codex down blocker (ticket 37).

Run: python3 -m pytest skills/boss/test_pulse_choice.py

A blocker the owner has answered (`- [codex-choice <id>] <choice> - <ts>` under Decisions in force, read by
codex_blocker) is shown as decided and never listed as BLOCKED, so the boss is not told to ask it again.
Every test goes through hermetic.Sandbox: `codex`, `claude`, `gh` and `tmux` are stubs, the hook runs as a
process against the sandbox's config dir, and each test reads the stubs' call logs.
"""
import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pulse  # noqa: E402
import tracker  # noqa: E402
from hermetic import Sandbox  # noqa: E402

PULSE = HERE / "boss-pulse.py"
TRACK = "demo"
SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CD = "cd261112103015"
OTHER_CD = "cd261112110000"
T0 = datetime(2026, 11, 12, 10, 30, tzinfo=timezone(timedelta(hours=1)))
OTHER = "- waiting on the owner to pick the org"


def cd_line(id_=CD):
    return ("- Codex down: 3 failed Codex attempts in a row - T+0 %s %s" % (
        T0.strftime("%Y-%m-%d %H:%M"),
        tracker.render_marker(id_, T0, T0 + timedelta(minutes=30), ask="Codex is down")))


def choice_line(id_=CD, value="wait"):
    return "- [codex-choice %s] %s - 2026-11-12T11:00:00+01:00" % (id_, value)


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        for name in ("codex", "claude", "gh", "tmux"):
            self.sb.stub(name)
        for d in ("pm/.boss-sessions", "pm/.pulse", "sessions"):
            (self.sb.cfg / d).mkdir(parents=True)
        (self.sb.cfg / "pm/.boss-sessions" / SID).write_text(TRACK + "\n")
        (self.sb.cfg / "pm" / (TRACK + ".goal.md")).write_text(
            "# Objective\n\n_Status: OPEN_\n\n## Outcome\nShip the thing.\n\n"
            "## Done when\n- [ ] it ships\n\n## Next, in priority order\n- do a thing\n", encoding="utf-8")

    def tracker(self, blockers, decisions=""):
        (self.sb.cfg / "pm" / (TRACK + ".md")).write_text(
            "# Tracker\n\n## Roster\n| none |\n\n## Open blockers\n%s\n\n## Decisions in force\n%s\n"
            "\n## Decisions\n- d\n" % (blockers, decisions), encoding="utf-8")

    def stop(self):
        for old in (self.sb.cfg / "pm/.pulse").iterdir():    # the pulse never speaks twice in a minute
            old.unlink()
        payload = {"session_id": SID, "hook_event_name": "Stop", "stop_hook_active": False}
        res = subprocess.run([sys.executable, str(PULSE)], input=json.dumps(payload), capture_output=True,
                             text=True, env=dict(self.sb.env), timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def tearDown(self):
        for name in ("codex", "claude", "gh"):
            self.sb.expect_unused(name)
        # The hook lists the panes for the roster, and does nothing else with tmux.
        for call in self.sb.calls_of("tmux"):
            self.assertEqual(call.argv[0], "list-panes")


class Hook(Base):
    def test_a_decided_blocker_alone_says_nothing(self):
        self.tracker(cd_line(), choice_line())
        self.assertEqual(self.stop(), "")

    def test_an_open_blocker_is_still_asked(self):
        self.tracker(cd_line())
        out = self.stop()
        self.assertIn("BLOCKED, and you are ending your turn without asking", out)
        self.assertIn("Codex down", out)
        self.assertNotIn("DECIDED", out)

    def test_a_decided_blocker_is_shown_as_decided_and_not_asked(self):
        self.tracker(cd_line() + "\n" + OTHER, choice_line(value="accept-fallback"))
        out = self.stop()
        self.assertIn("DECIDED by the owner, do not ask again: ", out)
        self.assertIn("(owner chose accept-fallback)", out)
        blocked = [ln for ln in out.splitlines() if ln.startswith("BLOCKED")]
        self.assertEqual(len(blocked), 1)
        self.assertIn("pick the org", blocked[0])
        self.assertNotIn("Codex down", blocked[0])
        self.assertNotIn("rung", out.lower().replace("run the due rung", ""))

    def test_a_decided_blocker_with_an_old_t0_presses_no_rung(self):
        self.tracker(cd_line() + "\n" + OTHER, choice_line())
        self.assertNotIn("OVERDUE", self.stop())

    def test_a_choice_for_another_blocker_does_not_count(self):
        self.tracker(cd_line(), choice_line(OTHER_CD))
        out = self.stop()
        self.assertIn("BLOCKED", out)
        self.assertNotIn("DECIDED", out)

    def test_a_malformed_choice_does_not_count(self):
        for bad in ("- [codex-choice %s] maybe - 2026-11-12T11:00:00+01:00" % CD,
                    "- [codex-choice %s] wait" % CD,
                    "[codex-choice %s] wait - 2026-11-12T11:00:00+01:00" % CD):
            with self.subTest(bad=bad):
                self.tracker(cd_line(), bad)
                out = self.stop()
                self.assertIn("BLOCKED", out)
                self.assertNotIn("DECIDED", out)

    def test_a_choice_outside_decisions_in_force_does_not_count(self):
        self.tracker(cd_line() + "\n" + choice_line())
        out = self.stop()
        self.assertIn("BLOCKED", out)
        self.assertNotIn("DECIDED", out)

    def test_the_last_choice_wins_and_is_the_one_shown(self):
        self.tracker(cd_line() + "\n" + OTHER, choice_line(value="wait") + "\n" + choice_line(value="tests-alone"))
        self.assertIn("(owner chose tests-alone)", self.stop())


class Render(unittest.TestCase):
    def test_the_decided_line_is_text_only_and_never_an_ask(self):
        facts = pulse.Facts(track=TRACK, idle=[("Ada", "w:1.0")], decided=["Codex down (owner chose wait)"])
        decision = pulse.decide(facts)
        self.assertNotIn("ask", [a.kind for a in decision.actions])
        out = pulse.render(facts, decision)
        self.assertIn("DECIDED by the owner, do not ask again: Codex down (owner chose wait)", out)
        self.assertNotIn("BLOCKED", out)


if __name__ == "__main__":
    unittest.main()
