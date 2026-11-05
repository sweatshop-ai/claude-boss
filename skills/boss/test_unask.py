#!/usr/bin/env python3
"""boss-unask records the owner's "not this kind of question" and lists it back.

Run: python3 skills/boss/test_unask.py

Every case writes into its own throwaway config directory; the real ~/.claude is never named.
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin" / "boss-unask"
sys.path.insert(0, str(HERE))


class Unask(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp(prefix="unask-test-"))
        self.addCleanup(shutil.rmtree, self.cfg, True)
        self.file = self.cfg / "pm" / "unwanted-questions.jsonl"

    def run_(self, *args, stdin=""):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), CLAUDE_CODE_SESSION_ID="sess-1",
                   HOME=str(self.cfg / "home"))
        return subprocess.run([str(BIN), *args], input=stdin, env=env, capture_output=True, text=True)

    def lines(self):
        return [json.loads(l) for l in self.file.read_text().splitlines()]

    def test_a_report_is_one_line_with_date_session_question_and_words(self):
        r = self.run_("record", "alpha-x", "merge-go-ahead", stdin="Merge PR 5?\n--- owner ---\nDit soort vraag hoef je mij niet te stellen.\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        (rec,) = self.lines()
        self.assertEqual((rec["track"], rec["kind"], rec["session"]), ("alpha-x", "merge-go-ahead", "sess-1"))
        self.assertEqual(rec["question"], "Merge PR 5?")
        self.assertEqual(rec["words"], "Dit soort vraag hoef je mij niet te stellen.")
        self.assertRegex(rec["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_the_file_is_private_and_lives_under_pm(self):
        self.run_("record", "alpha-x", "k", stdin="q\n--- owner ---\nw")
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_a_wider_file_is_narrowed_on_the_next_write(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("")
        self.file.chmod(0o644)
        self.run_("record", "alpha-x", "k", stdin="q\n--- owner ---\nw")
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_quotes_newlines_and_unicode_survive_as_valid_json(self):
        self.run_("record", "alpha-x", "k", stdin='Il "file" è\nlungo?\n--- owner ---\nnon chiedermelo — "mai"\n')
        self.run_("record", "alpha-x", "k", stdin="q2\n--- owner ---\nw2")
        a, b = self.lines()
        self.assertEqual(a["question"], 'Il "file" è lungo?')
        self.assertEqual(a["words"], 'non chiedermelo — "mai"')
        self.assertEqual(b["question"], "q2")

    def test_input_without_both_parts_is_refused_and_nothing_is_written(self):
        for bad in ("only a question", "q\n--- owner ---\n", "\n--- owner ---\nwords"):
            r = self.run_("record", "alpha-x", "k", stdin=bad)
            self.assertEqual(r.returncode, 1, bad)
        self.assertFalse(self.file.exists())

    def test_a_bad_track_or_kind_is_refused(self):
        for track, kind in (("../x", "k"), ("Alpha", "k"), ("alpha-x", "Bad Kind"), ("alpha-x", "../k"), ("alpha-x", "merge\n"), ("alpha-x", "")):
            r = self.run_("record", track, kind, stdin="q\n--- owner ---\nw")
            self.assertEqual(r.returncode, 1, (track, kind))
        self.assertFalse(self.file.exists())

    def test_a_long_question_is_cut_and_the_owners_words_keep_more_room(self):
        self.run_("record", "alpha-x", "k", stdin="q" * 5000 + "\n--- owner ---\n" + "w" * 5000)
        rec = self.lines()[0]
        self.assertEqual((len(rec["question"]), len(rec["words"])), (1000, 4000))

    def test_a_separator_inside_the_owners_words_stays_in_the_words(self):
        self.run_("record", "alpha-x", "k", stdin="q\n--- owner ---\nfirst\n--- owner ---\nsecond")
        self.assertEqual(self.lines()[0]["words"], "first --- owner --- second")

    def test_a_plain_rule_line_inside_the_question_does_not_split_it(self):
        self.run_("record", "alpha-x", "k", stdin="Pick one:\n---\nA or B?\n--- owner ---\nstop asking")
        rec = self.lines()[0]
        self.assertEqual((rec["question"], rec["words"]), ("Pick one: --- A or B?", "stop asking"))

    def test_a_torn_last_line_does_not_swallow_the_next_report(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text('{"date": "2026-11-05T09:00:00Z", "track": "alpha-x", "kind": "k", "que')
        self.run_("record", "alpha-x", "k", stdin="q\n--- owner ---\nw")
        import unask
        (rec,) = unask.read(self.cfg)
        self.assertEqual(rec["question"], "q")

    def test_a_line_with_a_free_text_kind_is_not_read_back(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(json.dumps(dict(date="2026-11-05T09:00:00Z", track="alpha-x", kind="Free Text", question="q", words="w")) + "\n")
        import unask
        self.assertEqual(unask.read(self.cfg), [])

    def test_a_symlinked_file_is_refused(self):
        self.file.parent.mkdir(parents=True)
        target = self.cfg / "elsewhere"
        target.write_text("")
        self.file.symlink_to(target)
        r = self.run_("record", "alpha-x", "k", stdin="q\n--- owner ---\nw")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(target.read_text(), "")

    def test_list_shows_one_track_only_kinds_first_with_counts(self):
        self.run_("record", "alpha-x", "merge-go-ahead", stdin="Merge PR 5?\n--- owner ---\nno")
        self.run_("record", "alpha-x", "merge-go-ahead", stdin="Merge PR 6?\n--- owner ---\nno")
        self.run_("record", "beta-y", "other", stdin="Other?\n--- owner ---\nno")
        r = self.run_("list", "alpha-x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("merge-go-ahead (2)", r.stdout)
        self.assertIn("Merge PR 6?", r.stdout)
        self.assertNotIn("Other?", r.stdout)

    def test_list_with_no_file_prints_nothing_and_succeeds(self):
        r = self.run_("list", "alpha-x")
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
