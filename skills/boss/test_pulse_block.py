#!/usr/bin/env python3
"""Tests for the pulse's Stop block: an idle worker without a park beside unassigned work.

Run: python3 -m pytest skills/boss/test_pulse_block.py

main() runs in-process on a stand-in roster, with the config directory pointed at a
throwaway directory: nothing here touches the real ~/.claude/pm.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pulse  # noqa: E402
import park  # noqa: E402

PULSE = HERE / "boss-pulse.py"
TRACK = "demo"
SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ADA = [("Ada", "w:1.0")]


class BlockCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-block-test-"))
        for d in ("pm/.boss-sessions", "pm/.pulse", "sessions"):
            (self.tmp / d).mkdir(parents=True)
        (self.tmp / "pm/.boss-sessions" / SID).write_text(TRACK + "\n")
        self.goal("- do a thing")
        (self.tmp / "pm" / (TRACK + ".md")).write_text(
            "# Tracker\n\n## Roster\n| none |\n\n## Open blockers\n\n\n## Decisions\n- d\n")
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def goal(self, next_):
        (self.tmp / "pm" / (TRACK + ".goal.md")).write_text(
            "# Objective\n\n_Status: OPEN_\n\n## Outcome\nShip.\n\n## Done when\n- [ ] it ships\n\n"
            "## Next, in priority order\n%s\n" % next_)

    def stop(self, idle, size=None, active=False, statuses=None, names=None):
        """The hook's stdout (a dict, or None when it said nothing)."""
        spec = importlib.util.spec_from_file_location("bp_%d" % time.monotonic_ns(), str(PULSE))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.team = lambda sid: (idle, size or len(idle), [n for n, _ in idle] if names is None else names)
        mod.concierge_holding = lambda sid: False
        mod.worker_statuses = lambda sid: dict(statuses or {})
        out, stdin = io.StringIO(), sys.stdin
        sys.stdin = io.StringIO(json.dumps(
            {"session_id": SID, "hook_event_name": "Stop", "stop_hook_active": active}))
        try:
            with contextlib.redirect_stdout(out):
                mod.main()
        finally:
            sys.stdin = stdin
        self.release()
        return json.loads(out.getvalue()) if out.getvalue().strip() else None

    def release(self):
        """Step over the one-a-minute gate."""
        p = self.tmp / "pm/.pulse" / (SID + ".json")
        if p.exists():
            st = json.loads(p.read_text())
            st["last"] = 0
            p.write_text(json.dumps(st))

    def gates(self):
        p = self.tmp / "pm/.pulse" / (SID + ".silence.log")
        return [l.split("\t")[2] for l in p.read_text().splitlines()] if p.exists() else []


class Blocks(BlockCase):
    def test_idle_unparked_worker_and_unassigned_ticket_block_the_stop(self):
        out = self.stop(ADA)
        self.assertEqual(out["decision"], "block")
        self.assertIn("IDLE: Ada", out["reason"])
        self.assertIn("do a thing", out["reason"])
        self.assertEqual(self.gates(), ["blocked"])

    def test_a_checked_park_lets_the_stop_through(self):
        park.set_park(TRACK, "Ada", "worker:Bo", cfg=self.tmp)
        out = self.stop(ADA, size=2, statuses={"Bo": "busy"})     # Bo works: Ada's park holds
        self.assertNotIn("decision", out or {})
        self.assertNotIn("Ada", json.dumps(out))
        self.assertEqual(self.gates(), ["fired"])
        # ... and once Bo is idle the park is over: the worker is dispatchable and blocks again.
        self.assertEqual(self.stop(ADA, size=2, statuses={"Bo": "idle"})["decision"], "block")

    def test_the_block_lets_go_after_three_and_logs_it(self):
        gates = []
        for _ in range(5):
            out = self.stop(ADA)
            gates.append(out["decision"] if out else None)
        self.assertEqual(gates, ["block", "block", "block", None, None])
        self.assertEqual(self.gates(), ["blocked"] * 3 + ["block-let-go"] * 2)

    def test_a_different_idle_set_starts_the_count_again(self):
        for _ in range(3):
            self.stop(ADA)
        out = self.stop(ADA + [("Bo", "w:1.1")])
        self.assertEqual(out["decision"], "block")

    def test_a_dispatch_resets_the_count(self):
        for _ in range(3):
            self.stop(ADA)
        self.goal("- do a thing (→ Ada)")
        self.assertIsNone(self.stop([], names=["Ada"]))   # nobody idle any more
        self.goal("- do a thing")
        self.assertEqual(self.stop(ADA)["decision"], "block")

    def test_the_stop_hook_active_guard_still_holds(self):
        self.assertIsNone(self.stop(ADA, active=True))
        self.assertEqual(self.gates(), ["stop-hook-active"])

    def test_idle_with_no_work_and_no_park_is_told_to_retire_without_a_block(self):
        self.goal("")
        out = self.stop(ADA)
        self.assertNotIn("decision", out)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("retire", text)
        self.assertEqual(self.gates(), ["fired"])

    def test_every_silent_stop_writes_one_line(self):
        self.goal("- do a thing (→ Ada)")
        self.stop([], size=1, names=["Ada"])       # nothing to say
        self.stop(ADA, active=True)                # guard
        self.assertEqual(self.gates(), ["nothing-to-say", "stop-hook-active"])


class Decide(unittest.TestCase):
    def test_ready_tickets_block(self):
        d = pulse.decide(pulse.Facts(track="t", source="g", idle=ADA, ready=["01 API"]))
        self.assertTrue(d.block)

    def test_nothing_to_hand_out_does_not_block_and_retires(self):
        d = pulse.decide(pulse.Facts(track="t", idle=ADA, size=1))
        self.assertFalse(d.block)
        self.assertIn("retire", [a.kind for a in d.actions])

    def test_a_broken_graph_never_blocks(self):
        d = pulse.decide(pulse.Facts(track="t", source="g", idle=ADA, broken="cycle",
                                     next_items=["- a"]))
        self.assertFalse(d.block)


if __name__ == "__main__":
    unittest.main()
