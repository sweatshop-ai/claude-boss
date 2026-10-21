#!/usr/bin/env python3
"""Tests for ci_state.py — is a branch's work waiting on CI, and until when.

Run: python3 skills/boss/test_ci_state.py

`gh` is a fake on PATH that answers from a JSON file, so nothing reaches GitHub.
The caller's read never touches the network: a refresh runs in a detached
process, and these tests wait for it the way a second poll would.
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

HERE = Path(__file__).resolve().parent
CI = HERE / "ci_state.py"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys, time
d = os.environ["FAKE_GH_DIR"]
cfg = json.load(open(os.path.join(d, "gh.json")))
time.sleep(cfg.get("sleep", 0))
if cfg.get("fail"):
    print("HTTP 502", file=sys.stderr)
    sys.exit(1)
path = sys.argv[-1]
for key, val in cfg["answers"].items():
    if key in path:
        print(json.dumps(val))
        sys.exit(0)
print(json.dumps({"workflow_runs": []}))
'''


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def run(status, created, started=None, updated=None, conclusion=None, wf=7):
    return {"status": status, "conclusion": conclusion, "workflow_id": wf,
            "created_at": iso(created), "run_started_at": iso(started or created),
            "updated_at": iso(updated or started or created),
            "html_url": "https://github.com/acme/app/actions/runs/1"}


class CiState(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ci-state-test-"))
        (self.tmp / "gh").write_text(FAKE_GH)
        (self.tmp / "gh").chmod(0o755)
        self.env = dict(os.environ, FAKE_GH_DIR=str(self.tmp),
                        CI_STATE_CACHE=str(self.tmp / "cache"),
                        PATH="%s:%s" % (self.tmp, os.environ["PATH"]))
        self.now = time.time()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gh(self, latest=None, history=(), sleep=0, fail=False):
        answers = {"/workflows/": {"workflow_runs": list(history)},
                   "/actions/runs": {"workflow_runs": [latest] if latest else []}}
        (self.tmp / "gh.json").write_text(json.dumps(
            {"answers": answers, "sleep": sleep, "fail": fail}))

    def get(self, repo="github.com/acme/app", branch="wt/ada-1"):
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, str(CI), "get", repo, branch],
                           capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout), time.monotonic() - t0

    def settle(self, repo="github.com/acme/app", branch="wt/ada-1"):
        """The first read starts a refresh; wait for it, then read again."""
        self.get(repo, branch)
        for _ in range(60):
            out, _ = self.get(repo, branch)
            if out["status"] != "unknown" or out.get("error"):
                return out
            time.sleep(0.1)
        return out

    def history(self, minutes):
        return [run("completed", self.now - 9000, self.now - 9000,
                    self.now - 9000 + m * 60, "success") for m in minutes]

    def test_a_running_build_gives_an_eta_from_recent_successes(self):
        self.gh(run("in_progress", self.now - 1500, self.now - 1200),
                self.history([40, 50, 60]))
        out = self.settle()
        self.assertEqual(out["status"], "in_progress")
        self.assertAlmostEqual(out["running_for_s"], 1200, delta=30)
        self.assertAlmostEqual(out["eta_s"], 50 * 60 - 1200, delta=30)

    def test_a_queued_build_counts_its_wait_and_says_the_eta_leaves_the_queue_out(self):
        self.gh(run("queued", self.now - 600), self.history([45]))
        out = self.settle()
        self.assertEqual(out["status"], "queued")
        self.assertAlmostEqual(out["queued_for_s"], 600, delta=30)
        self.assertAlmostEqual(out["eta_s"], 45 * 60, delta=30)
        self.assertTrue(out["eta_excludes_queue"])

    def test_a_finished_build_reports_its_conclusion(self):
        self.gh(run("completed", self.now - 3000, self.now - 3000, self.now - 100, "failure"))
        out = self.settle()
        self.assertEqual((out["status"], out["conclusion"]), ("completed", "failure"))
        self.assertIsNone(out["eta_s"])

    def test_gh_failing_is_unknown_not_an_exception(self):
        self.gh(fail=True)
        out = self.settle()
        self.assertEqual(out["status"], "unknown")

    def test_a_slow_gh_never_delays_the_caller(self):
        self.gh(run("queued", self.now), sleep=5)
        out, took = self.get()
        self.assertEqual(out["status"], "unknown")
        self.assertLess(took, 2.0)

    def test_owner_slash_name_and_host_form_are_the_same_repo(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        self.settle("github.com/acme/app")
        out, _ = self.get("acme/app")
        self.assertEqual(out["status"], "queued")

    def test_a_refresh_run_by_hand_creates_its_cache_dir(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        r = subprocess.run([sys.executable, str(CI), "refresh", "acme/app", "wt/ada-1"],
                           capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.get()[0]["status"], "queued")

    def test_another_host_is_another_repo(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        self.settle("github.com/acme/app")
        out, _ = self.get("git.example.com/acme/app")
        self.assertEqual(out["status"], "unknown")

    def test_a_failed_history_keeps_the_current_status(self):
        answers = {"/workflows/": None,       # the fake answers nothing parseable
                   "/actions/runs": {"workflow_runs": [run("in_progress", self.now - 300,
                                                           self.now - 200)]}}
        (self.tmp / "gh").write_text(FAKE_GH.replace(
            'for key, val in cfg["answers"].items():',
            'if "/workflows/" in path:\n    sys.exit(1)\nfor key, val in cfg["answers"].items():'))
        (self.tmp / "gh.json").write_text(json.dumps({"answers": answers}))
        out = self.settle()
        self.assertEqual(out["status"], "in_progress")
        self.assertIsNone(out["eta_s"])

    def test_a_failed_refresh_is_not_retried_on_every_poll(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        self.settle()
        old = time.time() - 120             # a minute later: cache and last attempt aged
        for f in (self.tmp / "cache").glob("*.*"):
            os.utime(f, (old, old))
        self.gh(fail=True)
        calls = self.tmp / "calls"
        (self.tmp / "gh").write_text(FAKE_GH.replace(
            "time.sleep(cfg.get(\"sleep\", 0))",
            "open(os.path.join(d, 'calls'), 'a').write('x')\ntime.sleep(cfg.get(\"sleep\", 0))"))
        for _ in range(5):
            self.get()
            time.sleep(0.4)
        self.assertEqual(calls.read_text(), "x")

    def test_waiting_and_requested_runs_are_queued(self):
        for status in ("pending", "requested"):      # "waiting": its own test
            self.tearDown()
            self.setUp()
            self.gh(run(status, self.now - 120), self.history([30]))
            out = self.settle()
            self.assertEqual(out["status"], "queued", status)
            self.assertAlmostEqual(out["queued_for_s"], 120, delta=30)

    def test_a_rerun_counts_its_wait_from_its_own_attempt(self):
        r = run("queued", self.now - 3 * 86400)
        r.update(run_attempt=2, run_started_at=iso(self.now - 120))
        self.gh(r, self.history([30]))
        out = self.settle()
        self.assertAlmostEqual(out["queued_for_s"], 120, delta=30)

    def test_a_waiting_run_does_not_invent_a_wait(self):
        r = run("waiting", self.now - 86400, self.now - 3600)
        self.gh(r, self.history([30]))
        out = self.settle()
        self.assertEqual(out["status"], "queued")
        self.assertIsNone(out["queued_for_s"])

    def test_a_malformed_cache_reads_as_unknown(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        self.settle()
        f = next((self.tmp / "cache").glob("*.json"))
        for bad in ("[]", '{"run": "x"}', '{"run": {"status": 5, "created_at": 7}}', '"x"',
                    '{"run": {"status": ""}}', '{"run": {"status": "bogus"}}'):
            f.write_text(bad)
            out, _ = self.get()
            self.assertEqual(out["status"], "unknown", bad)
        f.write_text('{"run": {"status": "queued"}, "median_s": 1e309}')
        out, _ = self.get()
        self.assertEqual((out["status"], out["eta_s"]), ("queued", None))

    def cache_files(self):
        return list((self.tmp / "cache").glob("*.*"))

    def test_a_cache_too_deep_to_parse_reads_as_unknown(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        self.settle()
        next((self.tmp / "cache").glob("*.json")).write_text("[" * 100000)
        self.assertEqual(self.get()[0]["status"], "unknown")

    def test_a_clock_stepped_back_does_not_freeze_the_answer(self):
        self.gh(run("in_progress", self.now - 300, self.now - 200), self.history([30]))
        self.settle()
        ahead = time.time() + 7200            # cache, lock and attempt written "in the future"
        for f in self.cache_files():
            os.utime(f, (ahead, ahead))
        self.gh(run("completed", self.now - 300, self.now - 200, self.now - 10, "success"))
        for _ in range(60):
            out, _ = self.get()
            if out["status"] == "completed":
                break
            time.sleep(0.1)
        self.assertEqual(out["status"], "completed")

    def test_a_start_ahead_of_the_local_clock_gives_no_negative_time(self):
        self.gh(run("in_progress", self.now + 600, self.now + 600), self.history([5]))
        out = self.settle()
        self.assertEqual(out["running_for_s"], 0)
        self.assertAlmostEqual(out["eta_s"], 300, delta=30)

    def test_a_median_that_is_not_a_positive_duration_gives_no_eta(self):
        self.gh(run("queued", self.now - 60), self.history([30]))
        self.settle()
        f = next((self.tmp / "cache").glob("*.json"))
        for median in ("-50", "true", "0"):
            f.write_text('{"run": {"status": "queued", "created_at": "%s"}, "median_s": %s}'
                         % (iso(self.now - 60), median))
            out, _ = self.get()
            self.assertEqual((out["status"], out["eta_s"]), ("queued", None), median)

    def test_the_vendor_header_names_the_master(self):
        self.assertIn("master copy", CI.read_text(encoding="utf-8")[:2000])


if __name__ == "__main__":
    unittest.main(verbosity=2)
