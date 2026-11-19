#!/usr/bin/env python3
"""Tests for the review rules of 2026-11-19: NO-GO only for a SERIOUS finding, diff-first reading, and the fix pass
(`--since SHA`, ticket 46) with the merge rule that lets its GO count.

Run: python3 skills/boss/test_boss_review_since.py

The seams: `build_brief`, `review()` in process through the stub harness of test_boss_review.py, and
`boss_merge.decide`.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_merge as bm  # noqa: E402
import boss_review as br  # noqa: E402
import test_boss_review as base  # noqa: E402

HEAD = "a" * 40
SINCE = "c" * 40
OWNER = ("owner/repo", 5)


class BriefRules(unittest.TestCase):
    def test_the_brief_asks_for_tagged_findings_and_a_no_go_only_for_a_serious_one(self):
        brief = br.build_brief(HEAD, "main", "T", "B", "D")
        self.assertIn("each starting with a tag right after `FINDING:`: `[SERIOUS]` or `[MINOR]`", brief)
        self.assertIn("Say NO-GO only when at least one finding is SERIOUS, GO otherwise.", brief)
        self.assertNotIn("when any finding must be fixed", brief)

    def test_the_brief_reviews_from_the_diff_and_never_reads_a_whole_file_over_300_lines(self):
        brief = br.build_brief(HEAD, "main", "T", "B", "D")
        self.assertIn("review from the diff (in the fence above; `git diff origin/main...HEAD` in this checkout)", brief)
        self.assertIn("never read a whole file over 300 lines", brief)

    def test_a_fix_pass_brief_names_the_fix_diff_and_fences_the_findings_it_answers(self):
        brief = br.build_brief(HEAD, "main", "T", "B", "the fix diff", since=SINCE,
                               answered="FINDING: [SERIOUS] f.py:1 off by one")
        self.assertIn("`git diff %s..HEAD`" % SINCE, brief)
        self.assertNotIn("origin/main...HEAD", brief)
        begin, end = brief.index("--- BEGIN PR TEXT"), brief.index("--- END PR TEXT")
        self.assertIn("FINDING: [SERIOUS] f.py:1 off by one", brief[begin:end])
        self.assertIn("the fix diff", brief[begin:end])
        self.assertIn(SINCE, brief[:begin])


class MinorOnly(base.Base):
    def test_a_go_with_only_minor_findings_is_a_go_and_shows_its_tags(self):
        self.codex(answer="FINDING: [MINOR] f.py:1 a clumsy name\nVERDICT: GO")
        result = self.review()
        self.assertEqual((result.exit_code, result.verdict), (br.EXIT_GO, "GO"))
        self.assertEqual(self.record(1)["findings"], 1)
        self.assertAsked(1)
        (comment,) = self.comments()
        self.assertIn("FINDING: [MINOR] f.py:1 a clumsy name", comment.argv[-1])


class FixPass(base.Base):
    """`review(since=SHA)`: SHA is the head of an earlier round, the checkout's head descends from it."""

    def commit(self, name, text, message):
        (self.checkout / name).write_text(text, encoding="utf-8")
        base.git(self.sb, self.checkout, "add", name)
        base.git(self.sb, self.checkout, "commit", "-q", "-m", message)
        return base.git(self.sb, self.checkout, "rev-parse", "HEAD")

    def first_round(self, answer):
        first = self.commit("f.py", "old\n", "round 1 head")
        self.gh.set_pr(headRefOid=first)
        self.codex(answer=answer)
        self.assertEqual(self.review().round, 1)
        return first

    def test_the_fix_pass_reviews_the_fix_diff_with_the_findings_it_answers_and_records_since(self):
        first = self.first_round("FINDING: [SERIOUS] f.py:1 says old\nVERDICT: NO-GO")
        second = self.commit("f.py", "new and fixed\n", "the fix")
        self.gh.set_pr(headRefOid=second)
        self.codex(answer="VERDICT: GO")
        result = self.review(since=first)
        self.assertEqual((result.exit_code, result.round, result.verdict), (0, 2, "GO"))
        brief = self.sb.calls_of("codex")[-1].argv[-1]
        self.assertIn("+new and fixed", brief)
        self.assertNotIn(base.DIFF, brief)
        self.assertIn("FINDING: [SERIOUS] f.py:1 says old", brief)
        self.assertIn("`git diff %s..HEAD`" % first, brief)
        record = self.record(2)
        self.assertEqual((record["since"], record["files"], record["findings"]), (first, ["f.py"], 0))
        self.assertEqual((self.record(1)["files"], self.record(1)["findings"]), (["f.py"], 1))
        (_, comment) = self.comments()
        self.assertIn("Fix diff since: %s" % first, comment.argv[-1])

    def test_a_sha_that_is_no_rounds_head_is_usage_and_nothing_is_asked(self):
        self.first_round("VERDICT: NO-GO")
        start = base.git(self.sb, self.checkout, "rev-parse", "HEAD~1")
        second = self.commit("f.py", "new\n", "the fix")
        self.gh.set_pr(headRefOid=second)
        result = self.review(since=start)
        self.assertEqual((result.exit_code, result.round), (br.EXIT_USAGE, None))
        self.assertAsked(1)

    def test_a_round_head_that_is_not_an_ancestor_of_the_head_is_usage(self):
        first = self.first_round("VERDICT: NO-GO")
        base.git(self.sb, self.checkout, "reset", "-q", "--hard", "HEAD~1")
        other = self.commit("g.py", "elsewhere\n", "not on top of round 1")
        self.gh.set_pr(headRefOid=other)
        result = self.review(since=first)
        self.assertEqual((result.exit_code, result.round), (br.EXIT_USAGE, None))
        self.assertAsked(1)

    def test_the_head_itself_is_not_a_fix_pass(self):
        first = self.first_round("VERDICT: NO-GO")
        result = self.review(since=first)
        self.assertEqual((result.exit_code, result.round), (br.EXIT_USAGE, None))
        self.assertAsked(1)


def rnd(n, head, verdict, *, since=None, files=("f.py",), findings=0, kind="codex", status="posted"):
    rec = {"repo": OWNER[0], "pr": OWNER[1], "round": n, "head_sha": head, "base": "main", "kind": kind,
           "verdict": verdict, "status": status, "files": list(files) if files is not None else None,
           "findings": findings}
    if since:
        rec["since"] = since
    return bm.Round(n, rec)


class FixDiffMerge(unittest.TestCase):
    """A fix-diff GO counts for the head only after a NO-GO or a GO with findings at SHA, on no new file."""

    def decide(self, *rounds):
        return bm.decide(list(rounds), HEAD, "main", frozenset(), OWNER)

    def test_after_a_no_go_a_fix_diff_go_on_the_files_reviewed_merges(self):
        got = self.decide(rnd(1, SINCE, "NO-GO", files=("f.py", "g.py"), findings=1),
                          rnd(2, HEAD, "GO", since=SINCE, files=("f.py",)))
        self.assertEqual((got.exit, got.reason, got.round), (bm.EXIT_MERGED, "codex-go", 2))

    def test_after_a_go_with_findings_a_fix_diff_go_merges(self):
        got = self.decide(rnd(1, SINCE, "GO", findings=2), rnd(2, HEAD, "GO", since=SINCE))
        self.assertEqual((got.exit, got.reason), (bm.EXIT_MERGED, "codex-go"))

    def test_after_a_clean_go_a_fix_diff_go_needs_a_full_round(self):
        got = self.decide(rnd(1, SINCE, "GO", findings=0), rnd(2, HEAD, "GO", since=SINCE))
        self.assertEqual((got.exit, got.reason, got.round), (bm.EXIT_REFUSED, "fix-diff-needs-full-round", 2))

    def test_a_fix_diff_that_touches_a_file_the_round_did_not_review_needs_a_full_round(self):
        got = self.decide(rnd(1, SINCE, "NO-GO", files=("f.py",), findings=1),
                          rnd(2, HEAD, "GO", since=SINCE, files=("f.py", "new.py")))
        self.assertEqual((got.exit, got.reason), (bm.EXIT_REFUSED, "fix-diff-needs-full-round"))

    def test_a_round_at_sha_that_is_missing_or_has_no_file_list_needs_a_full_round(self):
        for rounds in ([rnd(2, HEAD, "GO", since=SINCE)],
                       [rnd(1, SINCE, "NO-GO", files=None, findings=1), rnd(2, HEAD, "GO", since=SINCE)]):
            with self.subTest(rounds=rounds):
                got = self.decide(*rounds)
                self.assertEqual((got.exit, got.reason), (bm.EXIT_REFUSED, "fix-diff-needs-full-round"))

    def test_a_fix_diff_no_go_still_refuses(self):
        got = self.decide(rnd(1, SINCE, "NO-GO", findings=1), rnd(2, HEAD, "NO-GO", since=SINCE, findings=1))
        self.assertEqual((got.exit, got.reason), (bm.EXIT_REFUSED, "no-go"))

    def test_a_full_go_is_unchanged(self):
        got = self.decide(rnd(1, HEAD, "GO", files=None, findings=None))
        self.assertEqual((got.exit, got.reason), (bm.EXIT_MERGED, "codex-go"))


if __name__ == "__main__":
    unittest.main()
