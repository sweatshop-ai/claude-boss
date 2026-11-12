#!/usr/bin/env python3
"""Tests for the list of provisional GOs and the fallback switch of boss_review.py (ticket 06a).

Run: python3 -m pytest skills/boss/test_boss_review_list.py

A provisional GO is written to the track's tracker, under `## Provisional GO`, before its comment is posted;
`main()` runs the fallback exactly when `--track` names a usable tracker. Every test goes through
hermetic.Sandbox as test_boss_review_provisional.py does (its Base is used here): `codex`, `claude`, `gh` and
`boss-alert` are stubs, the tracker is pm/t.md in the temp config dir, each test asserts the stub calls it
expected, and none posts a real comment, raises a real alert or touches the real tracker.
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import fcntl
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import tracker  # noqa: E402
from test_boss_review import AUTHOR, OTHER_SHA, PR, REPO, git  # noqa: E402
from test_boss_review_provisional import Base as ProvBase  # noqa: E402

TRACKER = "# t\n\n## Open blockers\n"
GO = "FINDING: none\nVERDICT: GO\nREASON: fine\n"


class ListBase(ProvBase):
    def text(self):
        return self.tracker.read_bytes().decode("utf-8")

    def entries(self):
        return br.provisional_entries(self.text())

    def line(self, n=1, head=None):
        record = self.record(n)
        return "- [prov owner/repo#%d] head=%s round=%02d base=main at=%s" % (
            PR, head or self.head, n, record["ts"])

    def provisional_go(self, **kw):
        self.claude(GO)
        return self.fallback_review(**kw)

    def assertListFailed(self, result):
        self.assertEqual((result.exit_code, result.status, result.verdict, result.kind),
                         (7, "list-failed", "GO", "provisional"))
        self.assertEqual(self.comments(), [])
        record = self.record(1)
        self.assertEqual((record["status"], record["verdict"]), ("list-failed", "GO"))
        self.assertEqual(self.entries(), [])
        self.assertGhVerbs("view", "diff", "view", "view")

    def main_args(self, *extra):
        return ["--repo", REPO, "--pr", str(PR), "--checkout", str(self.checkout), "--author", AUTHOR, *extra]

    def run_main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = br.main(self.main_args(*extra))
        return code, out.getvalue(), err.getvalue()

    def new_head(self):
        git(self.sb, self.checkout, "commit", "-q", "--allow-empty", "-m", "the second head")
        head = git(self.sb, self.checkout, "rev-parse", "HEAD")
        self.gh.set_pr(headRefOid=head)
        return head


class TheEntry(ListBase):
    def test_it_is_written_before_the_comment_is_posted_and_has_the_contract_form(self):
        before_post = []
        real = br._post

        def spy(job, body):
            before_post.append(self.text())
            return real(job, body)

        with mock.patch.object(br, "_post", spy):
            result = self.provisional_go()
        self.assertEqual((result.exit_code, result.status), (0, "posted"))
        self.assertEqual(len(before_post), 1)
        self.assertIn("\n## Provisional GO\n" + self.line() + "\n", before_post[0])
        self.assertEqual(self.text(), TRACKER + "\n## Provisional GO\n" + self.line() + "\n")
        (entry,) = self.entries()
        self.assertEqual((entry.repo, entry.pr, entry.head, entry.round, entry.base),
                         ("owner/repo", PR, self.head, 1, "main"))
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", entry.at))
        self.assertGhVerbs("view", "diff", "view", "view", "view", "comment")

    def test_it_is_written_in_one_process_and_read_in_another(self):
        self.claude(GO)
        env = dict(os.environ)
        run = subprocess.run([sys.executable, str(HERE / "boss_review.py"), *self.main_args("--track", "t")],
                             env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(run.stdout.startswith("Fallback review 1: GO (posted) "), run.stdout)
        reader = subprocess.run(
            [sys.executable, "-I", "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); import boss_review as b\n"
             "for e in b.provisional_entries(open(sys.argv[2], newline='').read()): print(e.line)",
             str(HERE), str(self.tracker)],
            env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(reader.returncode, 0, reader.stderr)
        self.assertEqual(reader.stdout.splitlines(), [self.line()])

    def test_a_later_provisional_go_on_the_same_pr_replaces_the_line_and_never_adds_a_second(self):
        other = "- [prov owner/other#9] head=%s round=03 base=main at=2026-11-01T10:00:00Z" % ("c" * 40)
        prose = "see [prov owner/repo#5] head=%s round=01 base=main at=2026-11-01T09:00:00Z" % ("d" * 40)
        self.tracker.write_text(TRACKER + prose + "\n\n## Provisional GO\n" + other + "\n- hand note\n",
                                encoding="utf-8")
        first = self.provisional_go()
        second_head = self.new_head()
        self.claude(GO)
        self.expect["claude"] = 2
        second = self.fallback_review()
        self.assertEqual((first.round, second.round, second.status), (1, 2, "posted"))
        text = self.text()
        self.assertEqual(text.count("[prov owner/repo#5]"), 2)          # the prose, and the one entry
        self.assertIn(prose + "\n", text)
        self.assertIn("- hand note\n", text)
        self.assertEqual([e.line for e in self.entries()],
                         [other, self.line(2, second_head)])
        self.assertEqual(len(self.comments()), 2)

    def test_only_a_line_of_the_exact_form_in_the_section_is_an_entry(self):
        good = "- [prov owner/repo#5] head=%s round=01 base=main at=2026-11-01T10:00:00Z" % ("a" * 40)
        text = ("# t\n- [prov owner/repo#6] head=%s round=01 base=main at=x\n\n## Provisional GO\n%s\n"
                "- [prov owner/repo#7] head=zz round=01 base=main at=x\n- [prov owner/repo#8] head=%s round=1\n"
                "* [prov owner/repo#9] head=%s round=01 base=main at=x\n\n## Notes\n%s\n"
                % ("a" * 40, good, "a" * 40, "a" * 40, good))
        self.assertEqual([e.line for e in br.provisional_entries(text)], [good])
        self.assertEqual(br.provisional_entries("# t\n"), [])

    def test_a_hand_edited_line_that_breaks_the_contract_is_left_alone(self):
        sha, at = "a" * 40, "2026-11-01T10:00:00Z"
        bad = [
            "- [prov repo#5] head=%s round=01 base=main at=%s" % (sha, at),                  # no owner
            "- [prov a/b/c#5] head=%s round=01 base=main at=%s" % (sha, at),                 # three parts
            "- [prov owner/repo#5] head=a round=01 base=main at=%s" % at,                    # head too short
            "- [prov owner/repo#5] head=%s round=01 base=main at=%s" % ("a" * 41, at),       # head too long
            "- [prov owner/repo#5] head=%s round=1 base=main at=%s" % (sha, at),             # round of one digit
            "- [prov owner/repo#5] head=%s round=1x base=main at=%s" % (sha, at),            # round not a number
            "- [prov owner/repo#5] head=%s round=01 base=main at=x" % sha,                   # at= no date
            "- [prov owner/repo#5] head=%s round=01 base=main at=2026-11-01" % sha,          # at= no time
        ]
        for line in bad:
            with self.subTest(line=line):
                self.assertEqual(br.provisional_entries("## Provisional GO\n" + line + "\n"), [])
        self.tracker.write_text(TRACKER + "\n## Provisional GO\n" + "\n".join(bad) + "\n", encoding="utf-8")
        before = self.text()
        self.provisional_go()
        self.assertEqual(self.text(), before + self.line() + "\n")          # all of them stay, the entry is added
        self.assertEqual([e.line for e in self.entries()], [self.line()])

    def test_a_round_of_three_digits_is_written_and_read_back(self):
        entry = br.ProvEntry("owner/repo", 5, "a" * 40, 100, "main", "2026-11-01T10:00:00Z")
        self.assertEqual(br.provisional_entries("## Provisional GO\n" + entry.line + "\n"), [entry])
        self.assertIn("round=100 ", entry.line)

    def test_a_head_of_seven_characters_and_a_zone_offset_are_entries(self):
        for line in ("- [prov owner/repo#5] head=abcdef0 round=01 base=main at=2026-11-01T10:00:00Z",
                     "- [prov owner/repo#5] head=%s round=12 base=main at=2026-11-01T10:00:00+01:00" % ("a" * 40)):
            with self.subTest(line=line):
                self.assertEqual([e.line for e in br.provisional_entries("## Provisional GO\n" + line + "\n")],
                                 [line])

    def test_a_crlf_tracker_gets_crlf_lines_a_replaced_line_and_one_line_per_tag(self):
        old = lambda head, n, repo="repo", pr=PR: (   # noqa: E731
            "- [prov owner/%s#%d] head=%s round=%02d base=main at=2026-11-01T10:00:00Z" % (repo, pr, head, n))
        notes_line = old("d" * 40, 7)
        crlf = ("# t\r\n\r\n## Notes\r\n%s\r\n\r\n## Provisional GO\r\n%s\r\n%s\r\n- hand note\r\n%s\r\n"
                % (notes_line, old("a" * 40, 1), old("b" * 40, 3, "other", 9), old("c" * 40, 2)))
        self.tracker.write_bytes(crlf.encode())
        result = self.provisional_go()
        self.assertEqual(result.status, "posted")
        data = self.tracker.read_bytes()
        self.assertIsNone(re.search(rb"(?<!\r)\n", data), "a bare LF in a CRLF tracker")
        text = data.decode()
        self.assertIn("## Notes\r\n%s\r\n" % notes_line, text)          # outside the section: not a match
        self.assertIn("- hand note\r\n", text)
        self.assertEqual([e.line for e in self.entries()], [self.line(), old("b" * 40, 3, "other", 9)])
        self.assertEqual(text.count("owner/repo#5]"), 2)               # the Notes line, and the one entry

    def test_a_crlf_tracker_without_the_section_gets_it_with_crlf(self):
        self.tracker.write_bytes(b"# t\r\n\r\n## Open blockers\r\n")
        self.provisional_go()
        data = self.tracker.read_bytes()
        self.assertIsNone(re.search(rb"(?<!\r)\n", data))
        self.assertEqual(data.decode(), "# t\r\n\r\n## Open blockers\r\n\r\n## Provisional GO\r\n"
                         + self.line() + "\r\n")


class NothingIsListedFor(ListBase):
    def assertUntouched(self):
        self.assertEqual(self.text(), TRACKER)

    def test_a_head_moved_round(self):
        self.gh.configure(view=[{}, {}, {"patch": {"headRefOid": OTHER_SHA}}])
        result = self.provisional_go()
        self.assertEqual((result.exit_code, result.status, result.kind), (6, "head-moved", "provisional"))
        self.assertEqual(self.comments(), [])
        self.assertUntouched()

    def test_a_no_verdict_round(self):
        self.claude(answer=None, rc=1, err="model rejected")
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.status, result.kind), (4, "no-verdict", "provisional"))
        self.assertUntouched()

    def test_a_provisional_no_go(self):
        self.claude("FINDING: bad\nVERDICT: NO-GO\nREASON: no\n")
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.status, result.verdict, result.kind),
                         (3, "posted", "NO-GO", "provisional"))
        self.assertEqual(len(self.comments()), 1)
        self.assertUntouched()

    def test_a_codex_round(self):
        self.codex(answer="VERDICT: GO")
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.status, result.kind), (0, "posted", "codex"))
        self.assertUntouched()


class WhenTheListCannotBeWritten(ListBase):
    def test_update_returning_failed_posts_nothing(self):
        with mock.patch.object(tracker, "update", return_value="failed: boom"):
            result = self.provisional_go()
        self.assertListFailed(result)
        self.assertEqual(self.text(), TRACKER)

    def test_update_returning_done_while_the_line_is_not_in_the_file_posts_nothing(self):
        with mock.patch.object(tracker, "update", return_value="done"):
            result = self.provisional_go()
        self.assertListFailed(result)

    def test_the_trackers_lock_held_past_the_deadline_posts_nothing(self):
        held = open(tracker.lock_path(self.tracker), "a")
        self.addCleanup(held.close)
        fcntl.flock(held, fcntl.LOCK_EX)
        with mock.patch.object(br, "_sync_health"):
            result = self.provisional_go(io_timeout=1)
        self.assertListFailed(result)
        self.assertEqual(self.text(), TRACKER)

    @unittest.skipIf(os.geteuid() == 0, "root writes into a directory whatever its mode")
    def test_a_pm_directory_that_cannot_be_written_into_posts_nothing(self):
        self.pr_dir.mkdir(parents=True, mode=0o700)         # the rounds live below pm/, which is now closed
        pm = self.tracker.parent
        os.chmod(pm, 0o500)
        self.addCleanup(os.chmod, pm, 0o700)
        with mock.patch.object(br, "_sync_health"):
            result = self.provisional_go()
        self.assertListFailed(result)

    def test_a_provisional_go_that_reaches_the_post_with_no_tracker_path_is_list_failed(self):
        real = br._keep_and_post
        with mock.patch.object(br, "_keep_and_post", lambda *a, **kw: real(*a)):
            result = self.provisional_go()
        self.assertListFailed(result)
        self.assertEqual(self.text(), TRACKER)

    def test_a_pr_that_cannot_be_read_after_the_write_keeps_the_entry_and_posts_nothing(self):
        self.gh.configure(view=[{}, {}, {}, {"rc": 1, "err": "HTTP 502"}])       # the read after the list write
        result = self.provisional_go()
        self.assertEqual((result.exit_code, result.status, result.verdict), (7, "post-failed", "GO"))
        self.assertEqual(self.record(1)["status"], "post-failed")
        self.assertEqual(self.comments(), [])
        self.assertEqual([e.line for e in self.entries()], [self.line()])      # kept: 10 rechecks it
        self.assertGhVerbs("view", "diff", "view", "view", "view")

    def test_a_failing_comment_after_a_good_entry_keeps_the_entry(self):
        self.gh.configure(comment=[{"rc": 1, "err": "boom"}])
        result = self.provisional_go()
        self.assertEqual((result.exit_code, result.status, result.verdict), (7, "post-failed", "GO"))
        self.assertEqual(self.record(1)["status"], "post-failed")
        self.assertEqual([e.line for e in self.entries()], [self.line()])


class WhenThePrMovesDuringTheWrite(ListBase):
    """The tracker write may wait up to io_timeout, so the head is read once more after it."""

    VIEWS = [{}, {}, {}, {"patch": {"headRefOid": OTHER_SHA}}]      # the fourth `gh pr view` sees a new head

    def test_the_round_is_head_moved_nothing_is_posted_and_the_entry_is_removed(self):
        self.gh.configure(view=self.VIEWS)
        result = self.provisional_go()
        self.assertEqual((result.exit_code, result.status, result.verdict), (6, "head-moved", "GO"))
        self.assertEqual(self.record(1)["status"], "head-moved")
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.entries(), [])
        self.assertGhVerbs("view", "diff", "view", "view", "view")

    def test_a_cleanup_that_fails_leaves_the_entry_and_the_round_is_still_head_moved(self):
        self.gh.configure(view=self.VIEWS)
        real, calls = tracker.update, []

        def update(path, fn, deadline):
            calls.append(1)
            return real(path, fn, deadline) if len(calls) == 1 else "failed: boom"

        with mock.patch.object(tracker, "update", update), mock.patch.object(br, "_sync_health"):
            result = self.provisional_go()
        self.assertEqual((result.exit_code, result.status), (6, "head-moved"))
        self.assertEqual(len(calls), 2)
        self.assertEqual([e.line for e in self.entries()], [self.line()])
        self.assertEqual(self.comments(), [])

    def test_the_cleanup_removes_exactly_the_line_this_round_wrote(self):
        self.gh.configure(view=self.VIEWS)
        real, calls = tracker.update, []
        newer = br.ProvEntry("owner/repo", PR, "e" * 40, 2, "main", "2026-11-12T12:00:00Z")

        def update(path, fn, deadline):
            calls.append(1)
            if len(calls) == 2:                       # another review lists a newer head before the cleanup
                real(path, lambda text: br._with_entry(text, newer), deadline)
            return real(path, fn, deadline)

        with mock.patch.object(tracker, "update", update), mock.patch.object(br, "_sync_health"):
            result = self.provisional_go()
        self.assertEqual(result.status, "head-moved")
        self.assertEqual([e.line for e in self.entries()], [newer.line])


class NoTrackNoProvisionalReview(ListBase):
    def assertCodexOnly(self, code, err):
        self.assertEqual(code, 4)
        self.assertEqual(self.sb.calls_of("claude"), [])
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.record(1)["kind"], "codex")
        self.assertEqual(self.text() if self.tracker.is_file() else TRACKER, TRACKER)

    def test_the_command_line_without_a_track_asks_codex_only_and_says_why(self):
        self.gh.configure()
        code, out, err = self.run_main()
        self.assertCodexOnly(code, err)
        self.assertIn("needs a usable --track", err)
        self.assertTrue(out.startswith("Codex review 1: no verdict (no-verdict) "), out)

    def test_a_track_that_is_missing_a_symlink_or_a_directory_does_the_same(self):
        for what in ("missing", "symlink", "directory"):
            with self.subTest(track=what):
                self.setUp_clean()
                self.expect = {"claude": 0, "codex": 0}
                self.tracker.unlink()
                if what == "symlink":
                    real = self.sb.side / "real.md"
                    real.write_text(TRACKER, encoding="utf-8")
                    self.tracker.symlink_to(real)
                elif what == "directory":
                    self.tracker.mkdir()
                code, out, err = self.run_main("--track", "t")
                self.assertEqual(code, 4)
                self.assertEqual(self.sb.calls_of("claude"), [])
                self.assertEqual(self.comments(), [])
                self.assertEqual(self.record(1)["kind"], "codex")
                self.assertEqual(err.count("fallback review needs a usable track"), 1, err)
                self.assertEqual(err.count("no blocker can be raised"), 1, err)      # said once, not again by the sync
                self.assertTrue(out.startswith("Codex review 1: no verdict (no-verdict) "), out)
                self.sb.guard()

    def test_review_with_the_fallback_allowed_and_no_track_runs_codex_only(self):
        result = self.review(allow_fallback=True)
        self.assertEqual((result.exit_code, result.kind), (4, "codex"))
        self.assertEqual(self.sb.calls_of("claude"), [])

    def test_a_bad_track_name_is_still_exit_two_and_says_nothing_of_the_fallback(self):
        code, out, err = self.run_main("--track", "../x")
        self.assertEqual(code, 2)
        self.assertNotIn("fallback review needs", err)
        self.assertEqual(self.sb.calls_of("gh"), [])


class TheCommandLine(ListBase):
    def test_a_provisional_round_prints_fallback_review(self):
        self.claude(GO)
        code, out, err = self.run_main("--track", "t")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("Fallback review 1: GO (posted) "), out)
        self.assertEqual(len(self.entries()), 1)

    def test_a_fallback_that_ran_and_gave_no_verdict_prints_fallback_review_too(self):
        self.claude(answer=None, rc=1, err="model rejected")
        code, out, err = self.run_main("--track", "t")
        self.assertEqual(code, 4)
        self.assertTrue(out.startswith("Fallback review 1: no verdict (no-verdict) "), out)

    def test_a_codex_round_prints_codex_review_with_or_without_a_track(self):
        for extra in ((), ("--track", "t")):
            with self.subTest(extra=extra):
                self.setUp_clean()
                self.expect = {"claude": 0, "codex": 0}
                self.make_tracker()
                self.codex(answer="VERDICT: GO")
                code, out, err = self.run_main(*extra)
                self.assertEqual(code, 0, err)
                self.assertTrue(out.startswith("Codex review 1: GO (posted) "), out)
                self.assertEqual(self.sb.calls_of("claude"), [])

    def test_help_says_the_command_also_runs_the_labelled_fallback_where_track_is_usable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            br.main(["--help"])
        text = "".join(out.getvalue().split())          # argparse may wrap a line inside "read-only"
        for wanted in ("with --track T, when Codex does not answer, run the labelled read-only Opus fallback",
                       "list a provisional GO in pm/T.md before it is posted"):
            self.assertIn("".join(wanted.split()), text)


if __name__ == "__main__":
    unittest.main()
