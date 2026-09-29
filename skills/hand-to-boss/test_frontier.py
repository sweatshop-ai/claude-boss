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

    # -- graph validation (review item 2)

    def test_self_block_fails(self):
        self.put("01-a.md", ticket("01", "A", "\n- 01: A"))
        code, out, err = self.run_json()
        self.assertEqual(code, 2)
        self.assertIn("blocks itself", err)

    def test_cycle_fails(self):
        self.put("01-a.md", ticket("01", "A", "\n- 03: C"))
        self.put("02-b.md", ticket("02", "B", "\n- 01: A"))
        self.put("03-c.md", ticket("03", "C", "\n- 02: B"))
        code, out, err = self.run_json()
        self.assertEqual(code, 2)
        self.assertIn("cycle", err)
        self.assertIn("01", err)

    def test_non_utf8_ticket_is_a_clean_error(self):
        (self.dir / "01-a.md").write_bytes(b"# 01: A\n\n**Blocked by:** None\n\xff\xfe\n")
        code, out, err = self.run_json()
        self.assertEqual(code, 2)
        self.assertIn("01-a.md", err)
        self.assertNotIn("Traceback", err)

    # -- only the leading id of a blocker counts (review item 3)

    def test_numbers_in_a_blocker_title_are_not_blockers(self):
        self.put("01-a.md", ticket("01", "A", "None"))
        self.put("10-j.md", ticket("10", "J", "None"))
        self.put("11-k.md", ticket("11", "K", "\n- 01: Top 10 pages, 3 languages"))
        code, out, _ = self.run_json()
        self.assertEqual(code, 0)
        self.assertEqual(self.by_num(out)["11"]["blocked_by"], ["01"])

    # -- status matches on its leading word (review item 4)

    def test_status_done_with_a_date_is_done(self):
        self.put("01-a.md", ticket("01", "A", "None", status="done (2026-09-30)"))
        self.put("02-b.md", ticket("02", "B", "\n- 01: A"))
        self.put("03-c.md", ticket("03", "C", "None", status="**Done** - verified"))
        code, out, _ = self.run_json()
        t = self.by_num(out)
        self.assertEqual(t["01"]["state"], "done")
        self.assertEqual(t["03"]["state"], "done")
        self.assertEqual(out["ready"], ["02"])

    # -- the claim is written once, and a second claim is refused (review item 6)

    def claim(self, num, name):
        return subprocess.run([sys.executable, str(FRONTIER), "claim", str(self.dir), num, name],
                              capture_output=True, text=True)

    def test_claim_writes_the_line_and_takes_it_off_the_frontier(self):
        self.put("01-a.md", ticket("01", "A", "None"))
        r = self.claim("1", "Mei")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.dir / "01-a.md").read_text()
        self.assertRegex(text, r"\*\*Claimed by:\*\* Mei \d{4}-\d\d-\d\d \d\d:\d\d\n\n\*\*Status:\*\* in-progress")
        code, out, _ = self.run_json()
        self.assertEqual(out["ready"], [])
        self.assertEqual(self.by_num(out)["01"]["state"], "claimed")

    def test_second_claim_is_refused_and_leaves_the_file_alone(self):
        self.put("01-a.md", ticket("01", "A", "None"))
        self.assertEqual(self.claim("01", "Mei").returncode, 0)
        before = (self.dir / "01-a.md").read_text()
        r = self.claim("01", "Anselm")
        self.assertEqual(r.returncode, 3)
        self.assertIn("Mei", r.stderr)
        self.assertEqual((self.dir / "01-a.md").read_text(), before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["01-a.md"])

    def test_claim_refuses_a_ticket_that_is_not_ready(self):
        self.put("01-a.md", ticket("01", "A", "None"))
        self.put("02-b.md", ticket("02", "B", "\n- 01: A"))
        r = self.claim("02", "Mei")
        self.assertEqual(r.returncode, 3)
        self.assertIn("not ready", r.stderr)

    # -- one id form everywhere (review item 7)

    def test_ids_are_normalised_once(self):
        self.put("1-a.md", ticket("1", "A", "None", status="done"))
        self.put("2-b.md", ticket("2", "B", "\n- 1: A"))
        code, out, _ = self.run_json()
        self.assertEqual(code, 0)
        t = self.by_num(out)
        self.assertEqual(sorted(t), ["01", "02"])
        self.assertEqual(t["02"]["blocked_by"], ["01"])
        self.assertEqual(out["ready"], ["02"])

    # -- text output lists only open blockers (review item 5)

    def test_text_waiting_lists_only_open_blockers(self):
        self.put("01-a.md", ticket("01", "A", "None", status="done"))
        self.put("02-b.md", ticket("02", "B", "None"))
        self.put("03-c.md", ticket("03", "C", "\n- 01: A\n- 02: B"))
        r = subprocess.run([sys.executable, str(FRONTIER), str(self.dir)],
                           capture_output=True, text=True)
        self.assertIn("03  after 02", r.stdout)
        self.assertNotIn("after 01", r.stdout)


if __name__ == "__main__":
    unittest.main()
