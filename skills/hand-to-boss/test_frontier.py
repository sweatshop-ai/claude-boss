#!/usr/bin/env python3
"""Tests for frontier.py — which tickets a boss may hand out now.

Run: python3 skills/hand-to-boss/test_frontier.py

Tickets are the local-file format to-tickets writes: one `NN-slug.md` per
ticket, a `**Blocked by:**` field either inline or as a bullet list, a
`**Status:**` line, and optionally a `**Claimed by:**` line.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FRONTIER = Path(__file__).resolve().parent / "frontier.py"


def ticket(num, title, blocked, status="ready-for-agent", claimed=None):
    lines = ["# %s: %s" % (num, title), "", "**What to build:** something.", ""]
    if blocked is not None:
        lines += ["**Blocked by:** " + blocked, ""]
    if claimed:
        lines += ["**Claimed by:** " + claimed, ""]
    lines += ["**Status:** " + status, "", "- [ ] it works", ""]
    return "\n".join(lines)


class FrontierCase(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="frontier-test-"))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def put(self, name, text):
        (self.dir / name).write_text(text)

    def run_json(self):
        r = subprocess.run([sys.executable, str(FRONTIER), "--json", str(self.dir)],
                           capture_output=True, text=True)
        return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr

    def by_num(self, out):
        return {t["num"]: t for t in out["tickets"]}

    def test_no_blockers_is_ready(self):
        self.put("01-a.md", ticket("01", "A", "None (can start immediately)"))
        code, out, _ = self.run_json()
        self.assertEqual(code, 0)
        self.assertEqual(out["ready"], ["01"])

    def test_bullet_blockers_internal_and_external(self):
        self.put("01-a.md", ticket("01", "A", "None (can start immediately)"))
        self.put("02-b.md", ticket("02", "B",
                                   "\n- 01: A\n- External: staging copy exists (ops team)"))
        self.put("03-c.md", ticket("03", "C", "\n- 01: A"))
        code, out, _ = self.run_json()
        self.assertEqual(code, 0)
        t = self.by_num(out)
        self.assertEqual(t["02"]["blocked_by"], ["01"])
        self.assertEqual(t["02"]["external"], ["staging copy exists (ops team)"])
        self.assertEqual(t["02"]["state"], "waiting")
        self.assertEqual(t["03"]["state"], "waiting")
        self.assertEqual(out["ready"], ["01"])

    def test_done_blocker_opens_the_next(self):
        self.put("01-a.md", ticket("01", "A", "None", status="done"))
        self.put("02-b.md", ticket("02", "B", "01, and nothing else"))
        code, out, _ = self.run_json()
        self.assertEqual(out["ready"], ["02"])
        self.assertEqual(self.by_num(out)["01"]["state"], "done")

    def test_external_only_is_not_ready(self):
        self.put("01-a.md", ticket("01", "A", "\n- External: billing linked (finance)"))
        code, out, _ = self.run_json()
        self.assertEqual(out["ready"], [])
        self.assertEqual(out["external"], [{"num": "01", "what": "billing linked (finance)"}])

    def test_claimed_is_not_ready(self):
        self.put("01-a.md", ticket("01", "A", "None", status="in-progress", claimed="Mei 2026-09-29 10:00"))
        code, out, _ = self.run_json()
        self.assertEqual(out["ready"], [])
        self.assertEqual(self.by_num(out)["01"]["state"], "claimed")
        self.assertEqual(self.by_num(out)["01"]["claimed_by"], "Mei 2026-09-29 10:00")

    def test_missing_blocked_by_fails_the_input_check(self):
        self.put("01-a.md", ticket("01", "A", None))
        code, out, err = self.run_json()
        self.assertEqual(code, 2)
        self.assertIn("01-a.md", err)
        self.assertIn("Blocked by", err)

    def test_no_tickets_fails_the_input_check(self):
        code, out, err = self.run_json()
        self.assertEqual(code, 2)
        self.assertIn("no ticket files", err)

    def test_unknown_reference_is_reported(self):
        self.put("01-a.md", ticket("01", "A", "\n- 07: does not exist"))
        code, out, err = self.run_json()
        self.assertEqual(code, 2)
        self.assertIn("07", err)

    def test_numbers_inside_external_text_are_not_blockers(self):
        self.put("01-a.md", ticket("01", "A", "None"))
        self.put("02-b.md", ticket("02", "B", "\n- External: asked on 2026-09-29, ticket 01 of theirs"))
        code, out, _ = self.run_json()
        self.assertEqual(self.by_num(out)["02"]["blocked_by"], [])

    def test_text_output_names_the_frontier(self):
        self.put("01-a.md", ticket("01", "A", "None"))
        self.put("02-b.md", ticket("02", "B", "\n- External: key from the owner"))
        r = subprocess.run([sys.executable, str(FRONTIER), str(self.dir)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Ready now: 01", r.stdout)
        self.assertIn("02: key from the owner", r.stdout)


if __name__ == "__main__":
    unittest.main()
