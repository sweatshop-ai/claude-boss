#!/usr/bin/env python3
"""Tests for codex_health.py. No test calls codex, claude or gh.

Run: python3 -m pytest skills/boss/test_codex_health.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_health  # noqa: E402
from hermetic import Sandbox  # noqa: E402
import policy  # noqa: E402

F, OK, NV = "timeout", "answered", "noverdict"


def line(reason, reviewer="codex", repo="o/r", pr=1, **extra):
    d = {"ts": "2026-11-12T10:00:00+01:00", "repo": repo, "pr": pr, "round": 1, "reviewer": reviewer,
         "reason": reason, "exit_code": 0}
    d.update(extra)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "attempts.jsonl"

    def write(self, *entries, raw=b""):
        data = b"".join((e if isinstance(e, bytes) else json.dumps(e).encode()) + b"\n" for e in entries)
        self.path.write_bytes(data + raw)

    def health(self, *entries, **kw):
        self.write(*entries, **kw)
        return codex_health.health(self.path)


class Policy(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual((policy.CODEX_DOWN_AFTER, policy.CODEX_UP_AFTER), (3, 2))
        self.assertIn("Codex health", policy.__doc__)


class Streaks(Base):
    def test_missing_file_is_up_with_zeros(self):
        h = codex_health.health(self.path)
        self.assertEqual((h["state"], h["failures"], h["answers"], h["skipped"]), ("up", 0, 0, 0))

    def test_three_failures_are_down(self):
        h = self.health(*[line(r) for r in ("absent", "timeout", "error")])
        self.assertEqual((h["state"], h["failures"]), ("down", 3))

    def test_an_answer_amid_failures_breaks_the_streak(self):
        h = self.health(line(F), line(F), line(OK), line(F))
        self.assertEqual((h["state"], h["failures"], h["answers"]), ("up", 1, 0))

    def test_fallback_answers_do_not_turn_a_failure_into_a_success(self):
        entries = []
        for _ in range(3):
            entries += [line(F), line("answered", reviewer="opus")]
        h = self.health(*entries)
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("down", 3, 0))

    def test_down_then_ok_f_ok_is_still_down(self):
        h = self.health(line(F), line(F), line(F), line(OK), line(F), line(OK))
        self.assertEqual((h["state"], h["answers"]), ("down", 1))

    def test_down_then_two_answers_is_up(self):
        h = self.health(line(F), line(F), line(F), line(OK), line(OK))
        self.assertEqual((h["state"], h["answers"], h["failures"]), ("up", 2, 0))

    def test_noverdict_changes_nothing(self):
        h = self.health(line(F), line(NV), line(F), line(NV), line(F))
        self.assertEqual((h["state"], h["failures"]), ("down", 3))
        h = self.health(line(F), line(F), line(F), line(OK), line(NV), line(OK))
        self.assertEqual(h["state"], "up")

    def test_noverdict_does_not_end_an_answer_streak(self):
        h = self.health(line(F), line(F), line(F), line(OK), line(NV))
        self.assertEqual((h["state"], h["answers"]), ("down", 1))

    def test_all_repos_count_together(self):
        h = self.health(line(F, repo="a/x", pr=1), line(F, repo="b/y", pr=2), line(F, repo="a/x", pr=1))
        self.assertEqual((h["state"], h["prs"]), ("down", 2))

    def test_file_order_not_ts_order(self):
        h = self.health(line(F, ts="2026-11-12T12:00:00+01:00"), line(F, ts="2026-11-12T09:00:00+01:00"),
                        line(F, ts="2026-11-12T11:00:00+01:00"))
        self.assertEqual(h["state"], "down")

    def test_last_ts_is_the_newest_failure_in_file_order(self):
        from datetime import datetime, timedelta, timezone
        utc = self.health(line(F, ts="2026-11-12T09:00:00Z"))["last_ts"]
        self.assertEqual(utc, datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc))
        off = self.health(line(F, ts="2026-11-12T10:00:00+01:00"))["last_ts"]
        self.assertEqual((off, off.utcoffset()), (utc, timedelta(hours=1)))
        h = self.health(line(F, ts="2026-11-12T12:00:00+01:00"), line(F, ts="2026-11-12T09:00:00+01:00"))
        self.assertEqual(h["last_ts"].hour, 9)       # the later line in the file wins, not the later ts
        h = self.health(line(F, ts="2026-11-12T12:00:00+01:00"), line(OK, ts="2026-11-12T13:00:00+01:00"))
        self.assertEqual(h["last_ts"].hour, 12)      # an answer is no failure: last_* keep the old one

    def test_last_ts_is_none_without_a_usable_ts(self):
        gone = line(F)
        del gone["ts"]
        for bad in (gone, line(F, ts="yesterday"), line(F, ts=12), line(F, ts="2026-11-12T10:00:00")):
            with self.subTest(bad=bad.get("ts")):
                h = self.health(bad)
                self.assertEqual((h["last_ts"], h["last_reason"]), (None, F))
        self.assertIsNone(self.health(line(OK))["last_ts"])

    def test_blocker_text_fields(self):
        h = self.health(line(OK), line(F, repo="a/x", pr=4), line("error", repo="b/y", pr=9))
        self.assertEqual((h["last_repo"], h["last_pr"], h["last_reason"], h["prs"]), ("b/y", 9, "error", 2))
        h = self.health(line(F, repo="a/x", pr=4), line(OK), line(F, repo="a/x", pr=5))
        self.assertEqual((h["last_pr"], h["prs"]), (5, 1))

    def test_no_failure_has_no_last(self):
        h = self.health(line(OK))
        self.assertEqual((h["last_repo"], h["last_pr"], h["last_reason"], h["prs"]), (None, None, None, 0))


class Round(Base):
    def test_refused_answer_is_an_answer(self):
        h = self.health(line(F), line(OK, round=None, exit_code=7), line(F))
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("up", 1, 0))

    def test_refused_failure_is_a_failure(self):
        h = self.health(line(F), line(F, round=None, exit_code=7), line(F))
        self.assertEqual((h["state"], h["failures"]), ("down", 3))

    def test_round_absent_is_counted(self):
        e = line(F)
        del e["round"]
        h = self.health(e, e, e)
        self.assertEqual((h["state"], h["skipped"]), ("down", 0))


class Skipped(Base):
    def test_torn_last_line(self):
        h = self.health(line(F), line(F), raw=json.dumps(line(F)).encode()[:-1])
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("up", 2, 1))

    def test_complete_json_without_newline_is_torn(self):
        h = self.health(line(F), line(F), raw=json.dumps(line(F)).encode())
        self.assertEqual((h["failures"], h["skipped"]), (2, 1))

    def test_not_json_not_object_and_bad_utf8(self):
        h = self.health(b"nonsense", b"[1, 2]", b"3", b'{"repo": "\xff"}', line(F))
        self.assertEqual((h["failures"], h["skipped"]), (1, 4))

    def test_bad_repo_or_pr_cannot_reach_n(self):
        bad = []
        e = line(F)
        del e["repo"]
        bad.append(e)
        bad += [line(F, repo=""), line(F, repo=7), line(F, pr=0), line(F, pr=-2), line(F, pr=True),
                line(F, pr="3"), line(F, pr=1.0)]
        h = self.health(*bad, line(F), line(F))
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("up", 2, len(bad)))

    def test_missing_or_wrong_reviewer_and_reason(self):
        a, b = line(F), line(F)
        del a["reviewer"]
        del b["reason"]
        h = self.health(a, b, line(F, reviewer=3), line(F, reviewer=None), line(F), line(3))
        self.assertEqual((h["failures"], h["skipped"]), (1, 5))

    def test_codex_reason_outside_the_set(self):
        h = self.health(line("exploded"), line(F), line("ANSWERED"))
        self.assertEqual((h["failures"], h["skipped"]), (1, 2))

    def test_fallback_lines_are_ignored_not_skipped(self):
        h = self.health(line("exploded", reviewer="opus"), line("absent", reviewer="whatever"), line(F))
        self.assertEqual((h["failures"], h["skipped"]), (1, 0))

    def test_fallback_line_with_bad_shape_is_skipped(self):
        h = self.health(line("answered", reviewer="opus", pr=0))
        self.assertEqual(h["skipped"], 1)

    def test_blank_and_whitespace_lines_are_skipped_and_counted(self):
        # a blank line is not a JSON object; append_attempts never writes one, so it is a hand edit
        self.path.write_bytes(b"\n" + json.dumps(line(F)).encode() + b"\n \t\n\n")
        h = codex_health.health(self.path)
        self.assertEqual((h["failures"], h["skipped"]), (1, 3))

    def test_duplicate_keys_are_skipped_not_resolved_to_the_last(self):
        dup = b'{"ts": "t", "repo": "o/r", "pr": 1, "round": 1, "reviewer": "opus", "reason": "answered", ' \
              b'"exit_code": 0, "reviewer": "codex"}'
        h = self.health(dup, line(F))
        self.assertEqual((h["failures"], h["answers"], h["skipped"]), (1, 0, 1))

    def test_duplicate_key_nested_in_an_extra_field_is_skipped_too(self):
        h = self.health(b'{"ts": "t", "repo": "o/r", "pr": 1, "reviewer": "codex", "reason": "timeout", '
                        b'"x": {"a": 1, "a": 2}}')
        self.assertEqual((h["failures"], h["skipped"]), (0, 1))

    def test_a_torn_write_swallows_the_next_attempt(self):
        # a full disk can leave a fragment with no newline; the next append lands on the same line.
        # The merged line is not parseable, so one real attempt goes uncounted (documented in the docstring).
        torn = json.dumps(line(F)).encode()[:-1]
        self.path.write_bytes(json.dumps(line(F)).encode() + b"\n" + torn + json.dumps(line(F)).encode()
                              + b"\n" + json.dumps(line(F)).encode() + b"\n")
        h = codex_health.health(self.path)
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("up", 2, 1))
        self.assertIn("torn", codex_health.__doc__)
        self.assertIn("one attempt late", codex_health.__doc__)


class Concurrent(Base):
    def run_appends(self, n):
        code = ("import sys; sys.path.insert(0, %r); import boss_review; from pathlib import Path; "
                "boss_review.append_attempts(Path(sys.argv[1]), [{'ts': 't', 'repo': 'o/r', 'pr': int(sys.argv[2]), "
                "'round': 1, 'reviewer': 'codex', 'reason': 'timeout', 'exit_code': 124}])" % str(HERE))
        procs = [subprocess.Popen([sys.executable, "-c", code, str(self.path), str(i + 1)]) for i in range(n)]
        for p in procs:
            self.assertEqual(p.wait(timeout=60), 0)
        return codex_health.health(self.path)

    def test_three_processes_reach_down(self):
        h = self.run_appends(3)
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("down", 3, 0))

    def test_two_processes_stay_up(self):
        h = self.run_appends(2)
        self.assertEqual((h["state"], h["failures"], h["skipped"]), ("up", 2, 0))


class Command(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        for name in ("codex", "claude", "gh"):      # present only to log a call, should the module make one
            self.sb.stub(name)
        self.reviews = self.sb.cfg / "pm" / "reviews"

    def run_cli(self):
        r = subprocess.run([sys.executable, str(HERE / "codex_health.py")], env=self.sb.env, capture_output=True,
                           text=True, timeout=60)
        for name in ("codex", "claude", "gh"):      # the stubs would have logged a call: none was made
            self.assertEqual(self.sb.calls_of(name), [], name)
        return r

    def log(self, *entries):
        self.reviews.mkdir(parents=True, exist_ok=True)
        (self.reviews / "attempts.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))

    def test_missing_file_prints_one_json_line(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"state": "up", "failures": 0, "answers": 0, "skipped": 0})
        self.assertEqual(len(r.stdout.splitlines()), 1)

    def test_reads_the_log_under_the_config_dir(self):
        self.log(*[line(F)] * 3)
        r = self.run_cli()
        self.assertEqual(json.loads(r.stdout), {"state": "down", "failures": 3, "answers": 0, "skipped": 0})

    def test_an_unreadable_log_exits_2_on_purpose_with_the_error_on_stderr(self):
        # IsADirectoryError: the log path is a directory. Not a traceback, not exit 0 (which says "up").
        (self.reviews / "attempts.jsonl").mkdir(parents=True)
        r = self.run_cli()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("codex_health:", r.stderr)
        self.assertIn("attempts.jsonl", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_log_below_a_file_exits_2(self):
        # NotADirectoryError: `reviews` is a file
        self.reviews.parent.mkdir(parents=True)
        self.reviews.write_text("x")
        r = self.run_cli()
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-000 file")
    def test_a_log_without_read_permission_exits_2(self):
        self.log(line(F))
        log = self.reviews / "attempts.jsonl"
        log.chmod(0)
        self.addCleanup(log.chmod, 0o600)
        r = self.run_cli()
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_health_itself_still_raises_so_the_blocker_sync_sees_the_failure(self):
        d = Path(self.sb.cfg) / "dir.jsonl"
        d.mkdir()
        with self.assertRaises(IsADirectoryError):
            codex_health.health(d)


if __name__ == "__main__":
    unittest.main()
