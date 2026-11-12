#!/usr/bin/env python3
"""Tests for prune_provisional of boss_review.py (ticket 06b): the one function that removes an entry from the
list of provisional GOs, and the rules that say when.

Run: python3 -m pytest skills/boss/test_boss_review_prune.py

Every test goes through hermetic.Sandbox as test_boss_review_list.py does (its ListBase is used here): `gh` is a
stub that serves the PR's state and head, the round records are written by hand in the form `_keep_and_post`
writes, the tracker is pm/t.md in the temp config dir, and each test asserts the `gh` calls it expected. The
codex and claude stubs are never called by a prune. Nothing is posted and no real tracker is touched.
"""
import contextlib
import fcntl
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import tracker  # noqa: E402
from test_boss_review import OTHER_SHA, PR, REPO  # noqa: E402
from test_boss_review_list import TRACKER, ListBase  # noqa: E402

A, B = "a" * 40, OTHER_SHA
AT = "2026-11-12T10:00:00Z"
TAG = "[prov owner/repo#%d]" % PR


def line(pr=PR, head=A, round=1, repo="owner/repo"):
    return "- [prov %s#%d] head=%s round=%02d base=main at=%s" % (repo, pr, head, round, AT)


class PruneBase(ListBase):
    def put(self, *lines):
        self.tracker.write_text(TRACKER + "\n## Provisional GO\n" + "".join(l + "\n" for l in lines), encoding="utf-8")

    def rounds(self, *rounds, pr=PR):
        """Round records (number, head, verdict, {status, kind}) written as `_keep_and_post` writes them."""
        d = self.reviews / "owner" / "repo" / ("pr%d" % pr)
        d.mkdir(parents=True, exist_ok=True)
        for number, head, verdict, *more in rounds:
            extra = more[0] if more else {}
            record = {"repo": "owner/repo", "pr": pr, "round": number, "head_sha": head, "base": "main",
                      "reviewer": "codex", "model": None, "kind": "codex", "verdict": verdict,
                      "status": "posted", "author": "worker-a", "ts": AT, "attempts": []}
            record.update(extra)
            (d / ("round%02d.json" % number)).write_text(json.dumps(record), encoding="utf-8")

    def pr_is(self, state, head=A):
        self.gh.set_pr(state=state, headRefOid=head)

    def prune(self, repo=REPO):
        return br.prune_provisional("t", repo)


class RemovalRows(PruneBase):
    """One row per case of the ticket: (what, state, live head, entry line, rounds, removed?)."""

    ROWS = [
        # rule 1
        ("a Codex GO above the entry's round on its head, PR open", "OPEN", A, line(), [(2, A, "GO")], True),
        ("the same GO, PR merged on that head", "MERGED", A, line(), [(2, A, "GO")], True),
        ("the same GO while the live head moved on, PR open", "OPEN", B, line(), [(2, A, "GO")], True),
        ("that GO followed by a later Codex NO-GO on the same head", "OPEN", A, line(),
         [(2, A, "GO"), (3, A, "NO-GO")], False),
        ("a GO that a later Codex NO-GO on the head did not undo: NO-GO then GO", "OPEN", A, line(),
         [(2, A, "NO-GO"), (3, A, "GO")], True),
        ("a Codex NO-GO above the entry's round", "OPEN", A, line(), [(2, A, "NO-GO")], False),
        ("no Codex round at all", "OPEN", A, line(), [], False),
        ("a GO at the entry's own round, not above it", "OPEN", A, line(round=2), [(2, A, "GO")], False),
        ("a GO below the entry's round, live head the same (not rule 2)", "OPEN", A, line(round=3),
         [(2, A, "GO")], False),
        ("a GO below the entry's round, live head moved: rule 1 needs above, rule 2 needs the live head",
         "OPEN", B, line(round=3), [(2, A, "GO")], False),
        ("a provisional GO above the round is no Codex GO", "OPEN", A, line(),
         [(2, A, "GO", {"kind": "provisional"})], False),
        ("a Codex GO that was never posted", "OPEN", A, line(), [(2, A, "GO", {"status": "post-failed"})], False),
        ("a Codex GO that moved head, never posted", "OPEN", A, line(), [(2, A, "GO", {"status": "head-moved"})], False),
        # finding 16: a later head never removes the entry of a merged PR
        ("a Codex GO on a later head of a merged PR", "MERGED", A, line(), [(2, B, "GO")], False),
        # rule 2
        ("an open PR whose live head has a Codex GO", "OPEN", B, line(), [(2, B, "GO")], True),
        ("an open PR whose live head has a GO older than the entry's round (force-push back to a cleared head)",
         "OPEN", B, line(round=2), [(1, B, "GO")], False),
        ("a merged PR whose merged head has a GO older than the entry's round: merged is final", "MERGED", B,
         line(round=2), [(1, B, "GO")], True),
        ("an open PR whose live head has a GO at the entry's own round, not above it", "OPEN", B, line(round=2),
         [(2, B, "GO")], False),
        ("an open PR whose live head has a Codex NO-GO", "OPEN", B, line(), [(2, B, "NO-GO")], False),
        ("an open PR whose live head has a GO and then a NO-GO", "OPEN", B, line(),
         [(2, B, "GO"), (3, B, "NO-GO")], False),
        ("an open PR whose live head has only a provisional GO", "OPEN", B, line(),
         [(2, B, "GO", {"kind": "provisional"})], False),
        ("an open PR with a GO on a third head", "OPEN", B, line(), [(2, "c" * 40, "GO")], False),
        # rule 3
        ("a CLOSED PR with a Codex GO above the entry's round on its head (case C)", "CLOSED", A, line(),
         [(2, A, "GO")], False),
        ("a CLOSED PR with a Codex GO on its live head", "CLOSED", B, line(), [(2, B, "GO")], False),
        ("a state that is not OPEN, MERGED or CLOSED", "DRAFT", A, line(), [(2, A, "GO")], False),
        # rule 4
        ("a MERGED PR whose merged head differs, Codex GO on the merged head", "MERGED", B, line(),
         [(2, B, "GO")], True),
        ("the same with a Codex NO-GO on the merged head", "MERGED", B, line(), [(2, B, "NO-GO")], False),
        ("the same with no round", "MERGED", B, line(), [], False),
        ("the same with GO then NO-GO on the merged head", "MERGED", B, line(),
         [(2, B, "GO"), (3, B, "NO-GO")], False),
        ("the same with a provisional GO on the merged head", "MERGED", B, line(),
         [(2, B, "GO", {"kind": "provisional"})], False),
    ]

    def test_each_row(self):
        for what, state, live, entry, rounds, removed in self.ROWS:
            with self.subTest(what=what):
                self.setUp_clean()
                self.put(entry)
                self.pr_is(state, live)
                self.rounds(*rounds)
                before = len(self.sb.calls_of("gh"))
                got = self.prune()
                self.assertEqual(got, [TAG] if removed else [])
                self.assertEqual(self.entries() == [], removed)
                self.assertEqual(self.text().count("[prov"), 0 if removed else 1)
                gh = self.sb.calls_of("gh")[before:]
                self.assertEqual([c.argv[1] for c in gh], ["view"])
                self.assertEqual(gh[0].argv[gh[0].argv.index("--json") + 1], "state,headRefOid")
                self.assertEqual(self.sb.calls_of("codex") + self.sb.calls_of("claude"), [])

    def test_a_removed_entry_leaves_the_rest_of_the_tracker_as_it_was(self):
        other = line(pr=9, repo="owner/other", round=3)
        self.tracker.write_text(TRACKER + "\n## Provisional GO\n" + line() + "\n" + other + "\n- hand note\n\n## Done\n- x\n",
                                encoding="utf-8")
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.assertEqual(self.prune(), [TAG])
        self.assertEqual(self.text(), TRACKER + "\n## Provisional GO\n" + other + "\n- hand note\n\n## Done\n- x\n")

    def test_a_tracker_with_crlf_line_endings_is_pruned_and_keeps_its_endings(self):
        other = line(pr=9, repo="owner/other", round=3)
        crlf = (TRACKER + "\n## Provisional GO\n" + line() + "\n" + other + "\n- hand note\n").replace("\n", "\r\n")
        self.tracker.write_bytes(crlf.encode("utf-8"))
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.assertEqual(self.prune(), [TAG])
        self.assertEqual(self.tracker.read_bytes().decode("utf-8"),
                         crlf.replace(line() + "\r\n", "", 1))

    def test_two_identical_lines_of_one_entry_both_go_and_each_is_returned(self):
        self.put(line(), line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.assertEqual(self.prune(), [TAG, TAG])
        self.assertEqual(self.entries(), [])
        self.assertEqual(len(self.views()), 2)        # each line is its own entry: read, and judged, on its own

    def test_two_identical_lines_of_one_entry_stay_both_while_the_pr_is_not_cleared(self):
        self.put(line(), line())
        self.pr_is("OPEN")
        self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [line(), line()])


class WhatKeepsTheEntry(PruneBase):
    def test_an_unreadable_pr_state_keeps_the_entry_even_with_a_codex_go_above_its_round(self):
        cases = {"gh fails": {"rc": 1}, "not json": {"raw": "nope"}, "empty": {"raw": ""}, "a list": {"raw": "[]"},
                 "no state": {"drop": ["state"]}, "no head": {"drop": ["headRefOid"]},
                 "a head that is not a sha": {"patch": {"headRefOid": "zz"}}, "a state that is a number": {"patch": {"state": 7}}}
        for what, view in cases.items():
            with self.subTest(what=what):
                self.setUp_clean()
                self.put(line())
                self.pr_is("OPEN")
                self.rounds((2, A, "GO"))
                self.gh.configure(view=[view])
                self.assertEqual(self.prune(), [])
                self.assertEqual([e.line for e in self.entries()], [line()])
                self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh")], ["view"])

    def test_a_gh_that_outlasts_the_io_timeout_keeps_the_entry(self):
        """The timeout is seen to fire on the `gh pr view` itself (a slow machine alone cannot pass this)."""
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.gh.configure(view=[{"sleep": 30}])
        real, seen = br._spawn, []

        def spawn(argv, timeout, *rest, **kw):
            run = real(argv, timeout, *rest, **kw)
            seen.append((argv[:3], run.timed_out))
            return run

        err = io.StringIO()
        with mock.patch.object(br, "_spawn", spawn), contextlib.redirect_stderr(err):
            self.assertEqual(br.prune_provisional("t", REPO, io_timeout=1), [])
        self.assertEqual(seen, [(["gh", "pr", "view"], True)])
        self.assertEqual(err.getvalue(), "")        # an unreadable PR state keeps the entry without a word
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_round_file_that_cannot_be_read_keeps_the_entry_even_when_another_round_is_a_go(self):
        for what, body in {"empty (claimed, not yet recorded)": "", "not json": "{", "a list": "[]",
                           "no status": '{"kind": "codex"}', "a string": '"x"'}.items():
            with self.subTest(what=what):
                self.setUp_clean()
                self.put(line())
                self.pr_is("OPEN")
                self.rounds((2, A, "GO"))
                (self.pr_dir / "round03.json").write_text(body, encoding="utf-8")
                self.assertEqual(self.prune(), [])
                self.assertEqual([e.line for e in self.entries()], [line()])

    def test_an_empty_round_below_a_later_round_is_a_dead_claim_and_does_not_keep_the_entry(self):
        """A round is claimed under the PR's lock, so a later round exists only once the earlier review ended: an
        empty file below it is a write that failed (`round 2 is left empty`), and the later review clears it."""
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((3, A, "GO"))
        (self.pr_dir / "round02.json").write_text("", encoding="utf-8")
        self.assertEqual(self.prune(), [TAG])
        self.assertEqual(self.entries(), [])

    def test_an_empty_round_below_a_later_round_clears_nothing_that_is_not_there(self):
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((3, A, "NO-GO"))
        (self.pr_dir / "round02.json").write_text("", encoding="utf-8")
        self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_round_below_a_later_one_that_is_not_empty_but_unreadable_still_keeps_the_entry(self):
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((3, A, "GO"))
        (self.pr_dir / "round02.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_round_file_nested_too_deep_for_the_json_parser_keeps_the_entry(self):
        """json.loads raises RecursionError, which is no ValueError: it must not stop the prune of the repo."""
        second = line(pr=6)
        self.put(line(), second)
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.rounds((2, A, "GO"), pr=6)
        (self.pr_dir / "round03.json").write_text("[" * 200000, encoding="utf-8")
        self.assertEqual(self.prune(), ["[prov owner/repo#6]"])        # the next PR is pruned all the same
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_round_file_name_too_long_to_exist_cannot_reach_the_parser(self):
        """The ticket feared int() on a name of over 4300 digits. A file name is at most 255 bytes on Linux."""
        digits = "1" * (4300 + 1)
        with self.assertRaises(OSError):
            (self.pr_dir / ("round%s.json" % digits)).write_text("{}", encoding="utf-8")
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        longest = "1" * (255 - len("round.json"))                        # the longest name there can be
        (self.pr_dir / ("round%s.json" % longest)).write_text("{}", encoding="utf-8")
        self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_record_that_is_not_the_one_its_file_name_says_keeps_the_entry(self):
        """round02.json is a Codex GO but says it is round 1, or another PR, or has no round: no record of round 2."""
        for what, patch in {"another round": {"round": 1}, "no round": {"round": None}, "a round as text": {"round": "2"},
                            "another PR": {"pr": 6}, "a round as a float": {"round": 2.0}, "a pr as a float": {"pr": float(PR)}, "another repo": {"repo": "owner/other"}}.items():
            with self.subTest(what=what):
                self.setUp_clean()
                self.put(line())
                self.pr_is("OPEN")
                self.rounds((2, A, "GO", patch))
                self.assertEqual(self.prune(), [])
                self.assertEqual([e.line for e in self.entries()], [line()])
        with self.subTest(what="a round key that is missing"):
            self.setUp_clean()
            self.put(line())
            self.pr_is("OPEN")
            self.rounds((2, A, "GO"))
            record = json.loads(self.round_file(2).read_text(encoding="utf-8"))
            del record["round"]
            self.round_file(2).write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(self.prune(), [])
            self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_round_file_that_is_not_readable_by_mode_keeps_the_entry(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"), (3, A, "GO"))
        (self.pr_dir / "round03.json").chmod(0)
        self.addCleanup((self.pr_dir / "round03.json").chmod, 0o600)
        self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_closed_pr_keeps_its_entry_and_the_reopened_one_is_removed_by_rule_one(self):
        self.put(line())
        self.rounds((2, A, "GO"))
        self.pr_is("CLOSED")
        self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [line()])
        self.pr_is("OPEN")
        self.rounds((3, A, "GO"))
        self.assertEqual(self.prune(), [TAG])
        self.assertEqual(self.entries(), [])
        self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh")], ["view", "view"])


class WhatIsLeftAlone(PruneBase):
    def test_only_the_entries_of_the_repo_asked_for_are_read(self):
        other = line(pr=9, repo="owner/other", round=1)
        self.put(line(), other)
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.assertEqual(self.prune("OWNER/REPO"), [TAG])
        self.assertEqual([e.line for e in self.entries()], [other])
        self.assertEqual(len(self.views()), 1)

    def test_one_entry_that_cannot_be_read_does_not_stop_the_next(self):
        second = line(pr=6)
        self.put(line(), second)
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        self.rounds((2, A, "GO"), pr=6)
        self.gh.configure(view=[{"rc": 1}, {}])
        self.assertEqual(self.prune(), ["[prov owner/repo#6]"])
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_a_tracker_with_no_section_or_no_entry_makes_no_gh_call(self):
        self.assertEqual(self.prune(), [])
        self.put("- hand note", line(repo="owner/other"))
        self.assertEqual(self.prune(), [])
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_track_that_is_not_a_regular_file_of_yours_prunes_nothing(self):
        self.tracker.unlink()
        self.assertEqual(self.prune(), [])
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_track_that_is_not_a_plain_name_and_a_repo_that_is_not_two_names_are_refused(self):
        with self.assertRaises(ValueError):
            br.prune_provisional("../t", REPO)
        with self.assertRaises(ValueError):
            br.prune_provisional("t", "../x")


class WhenTheTrackerChangesUnderIt(PruneBase):
    def test_a_newer_provisional_go_that_replaced_the_line_meanwhile_is_not_removed(self):
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        newer = line(head=B, round=4)
        real = tracker.update

        def update(path, fn, deadline):          # 06a's _list_and_post replaced the line after it was read
            self.put(newer)
            return real(path, fn, deadline)

        with mock.patch.object(tracker, "update", update):
            self.assertEqual(self.prune(), [])
        self.assertEqual([e.line for e in self.entries()], [newer])

    def test_a_line_that_vanished_meanwhile_returns_no_tag(self):
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        real = tracker.update

        def update(path, fn, deadline):
            self.tracker.write_text(TRACKER, encoding="utf-8")
            return real(path, fn, deadline)

        with mock.patch.object(tracker, "update", update):
            self.assertEqual(self.prune(), [])

    def test_the_prune_takes_the_tracker_lock_and_never_the_prs(self):
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        fd = br.open_lock(self.reviews, self.pr_dir, 5)       # a review of this PR holds the PR's lock
        self.addCleanup(os.close, fd)                         # closing the descriptor lets the lock go
        self.assertEqual(self.prune(), [TAG])
        self.assertEqual(self.entries(), [])

    def test_a_held_tracker_lock_leaves_the_entry_and_says_so(self):
        """gh has the full time; only the tracker's own wait is cut to one second."""
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        real = tracker.update

        def update(path, fn, deadline):
            return real(path, fn, time.monotonic() + 1)

        err = io.StringIO()
        with open(tracker.lock_path(self.tracker), "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            with mock.patch.object(tracker, "update", update), contextlib.redirect_stderr(err):
                self.assertEqual(br.prune_provisional("t", REPO, io_timeout=30), [])
        self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh")], ["view"])        # it got as far as the lock
        self.assertRegex(err.getvalue(), r"boss_review: the list of \S+ was not pruned \(")
        self.assertEqual([e.line for e in self.entries()], [line()])

    def test_an_exception_from_the_update_reaches_the_caller_and_the_file_is_as_it_was(self):
        self.put(line())
        self.pr_is("OPEN")
        self.rounds((2, A, "GO"))
        before = self.text()
        real = tracker.update

        def update(path, fn, deadline):
            def broken(text):
                raise RuntimeError("boom")
            return real(path, broken, deadline)

        with mock.patch.object(tracker, "update", update):
            with self.assertRaises(RuntimeError):
                self.prune()
        self.assertEqual(self.text(), before)
        self.assertEqual(self.prune(), [TAG])        # the lock was let go


if __name__ == "__main__":
    unittest.main()
