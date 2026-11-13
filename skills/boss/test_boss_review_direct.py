#!/usr/bin/env python3
"""Tests for `boss_review.py --opus-direct` (ticket 52): the Opus pass run straight away, without asking Codex, for
a PR that changes only tests and narrow docs (review by risk, rule 2).

Run: python3 -m pytest skills/boss/test_boss_review_direct.py

Every test goes through hermetic.Sandbox as test_boss_review_provisional.py does (its Base is used here): `codex`,
`claude` and `gh` are stubs, and `gh api` answers the base's `.boss/deploy.json` and the compare of the PR from
side/gh.json. Codex must never be called, the attempts log must stay empty (Codex's health counts it), and no
tracker is written (a direct pass is not a loan that a Codex recheck pays back).
"""
import base64
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_merge as bm  # noqa: E402
import boss_review as br  # noqa: E402
from test_boss_review import AUTHOR, PR, REPO  # noqa: E402
from test_boss_review_provisional import MODEL, Base as ProvBase  # noqa: E402

GO = "FINDING: none\nVERDICT: GO\nREASON: fine\n"
NO_GO = "FINDING: [a] a test that asserts nothing\nVERDICT: NO-GO\nREASON: it proves nothing\n"
DEPLOY = {"version": 1, "non_deploying": [], "test_paths": ["tests/*", "*/test_*.py"],
          "required_checks": ["tests"]}
TRACKER_BEFORE = "# t\n\n## Open blockers\n"


def deploy_answer(conf=DEPLOY):
    text = json.dumps(conf)
    return {"raw": json.dumps({"content": base64.b64encode(text.encode()).decode()})}


def compare_answer(files, status="ahead", **extra):
    return {"raw": json.dumps(dict({"status": status, "files": [{"filename": f} for f in files],
                                    "commits": [{"parents": [{}]}], "total_commits": 1}, **extra))}


class Direct(ProvBase):
    def serve(self, files=("tests/test_a.py", "README.md", "docs/guide.md"), deploy=None, compare=None):
        """What the gh stub answers to `gh api`: the deploy list and the compare of base...head."""
        self.gh.configure(api={"contents/.boss/deploy.json": deploy or deploy_answer(),
                               "compare/main...%s" % self.head: compare or compare_answer(files)})

    def direct(self, **kw):
        return self.review(opus_direct=True, **kw)

    def api_calls(self):
        return [c for c in self.sb.calls_of("gh") if c.argv[0] == "api"]

    def assertNothingHappened(self, result, code=5):
        """A refusal before anything is claimed: no round, no comment, no model, no log line."""
        self.assertEqual(result, br.ReviewResult(code, None, None, None, None, None))
        self.assertEqual(self.round_names(), [])
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.attempts_log(), [])
        self.expect["claude"] = 0
        self.expect["codex"] = 0

    def stderr_of(self, fn):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = fn()
        return result, err.getvalue()


class TheReview(Direct):
    def test_a_tests_and_docs_pr_gets_a_direct_opus_go_and_codex_is_never_asked(self):
        self.serve()
        self.claude(GO)
        result = self.direct()
        self.assertEqual(result, br.ReviewResult(0, 1, "posted", "GO", self.round_file(1), "provisional"))
        self.assertEqual(self.sb.calls_of("codex"), [])
        (call,) = self.sb.calls_of("claude")
        self.assertIn(self.head, call.argv[-1])
        self.assertIn("--restricted", call.argv)        # the same confined call as the fallback's

    def test_the_round_is_the_provisional_opus_round_rule_2_accepts_with_no_codex_attempt(self):
        self.serve()
        self.claude(GO)
        self.direct()
        record = self.record(1)
        self.assertEqual({k: record[k] for k in ("repo", "pr", "round", "head_sha", "base", "reviewer", "model",
                                                 "kind", "verdict", "status", "author")},
                         {"repo": "owner/repo", "pr": PR, "round": 1, "head_sha": self.head, "base": "main",
                          "reviewer": "opus", "model": MODEL, "kind": "provisional", "verdict": "GO",
                          "status": "posted", "author": AUTHOR})
        self.assertEqual([(a["reviewer"], a["reason"], a["model"]) for a in record["attempts"]],
                         [("opus", "answered", MODEL)])
        self.assertEqual(self.round_file(1, "out").read_text(encoding="utf-8"), GO)

    def test_the_gate_reads_it_as_it_reads_a_fallback_go_on_a_deploying_base_so_rule_2_decides(self):
        self.serve()
        self.claude(GO)
        self.direct()
        rounds = bm.read_rounds(self.pr_dir)
        owner = ("owner/repo", PR)
        deploying = bm.decide(rounds, self.head, "main", frozenset(), owner)
        self.assertEqual((deploying.exit, deploying.reason, deploying.round, deploying.kind),
                         (bm.EXIT_DEPLOYING, "deploying-base", 1, "provisional"))      # the rule-2 entry point
        quiet = bm.decide(rounds, self.head, "main", frozenset({"main"}), owner)
        self.assertEqual((quiet.exit, quiet.reason), (bm.EXIT_MERGED, "provisional-go-non-deploying"))

    def test_codex_health_never_sees_it(self):
        self.serve()
        self.claude(GO)
        self.direct()
        self.assertEqual(self.attempts_log(), [])
        self.assertFalse((self.reviews / "attempts.jsonl").exists())

    def test_no_tracker_line_is_written_so_no_codex_recheck_is_owed(self):
        self.serve()
        self.claude(GO)
        self.direct()
        self.assertEqual(self.tracker.read_text(encoding="utf-8"), TRACKER_BEFORE)

    def test_the_comment_says_plainly_it_is_a_direct_opus_pass_under_review_by_risk_and_not_a_fallback(self):
        self.serve()
        self.claude(GO)
        self.direct()
        (comment,) = self.comments()
        body = comment.argv[-1]
        self.assertEqual(body.splitlines()[0],
                         "Direct Opus review 1 (%s, review by risk, not a fallback; run by %s)" % (MODEL, AUTHOR))
        self.assertIn("Head: %s" % self.head, body)
        self.assertIn("Verdict: provisional GO", body)
        self.assertIn("    FINDING: none", body)
        self.assertIn("Codex was not asked", body)
        self.assertNotIn("Codex unavailable", body)
        self.assertNotIn("Fallback review", body)
        self.assertNotIn("re-reviews this head", body)

    def test_a_docs_only_pr_is_run_too(self):
        self.serve(files=("README.md", "CHANGELOG.md", "docs/a.md"))
        self.claude(GO)
        self.assertEqual(self.direct().exit_code, 0)

    def test_a_rename_is_judged_by_both_names(self):
        self.serve(compare={"raw": json.dumps({"status": "ahead", "files": [
            {"filename": "tests/test_b.py", "previous_filename": "src/b.py"}]})})
        result, err = self.stderr_of(self.direct)
        self.assertNothingHappened(result)
        self.assertIn("src/b.py", err)

    def test_an_opus_no_go_is_posted_as_a_no_go_with_the_same_label(self):
        self.serve()
        self.claude(NO_GO)
        result = self.direct()
        self.assertEqual((result.exit_code, result.status, result.verdict, result.kind), (3, "posted", "NO-GO", "provisional"))
        (comment,) = self.comments()
        self.assertTrue(comment.argv[-1].startswith("Direct Opus review 1 ("))
        self.assertIn("Verdict: NO-GO", comment.argv[-1])
        self.assertEqual(self.attempts_log(), [])
        self.assertEqual(bm.decide(bm.read_rounds(self.pr_dir), self.head, "main", frozenset({"main"}),
                                   ("owner/repo", PR)).reason, "no-go")

    def test_an_opus_that_gives_no_verdict_leaves_a_no_verdict_round_and_nothing_logged(self):
        self.serve()
        self.claude("I would need more context.\n")
        result = self.direct()
        self.assertEqual((result.exit_code, result.status, result.verdict), (4, "no-verdict", None))
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.attempts_log(), [])
        self.assertEqual(self.tracker.read_text(encoding="utf-8"), TRACKER_BEFORE)

    def test_an_opus_that_fails_is_no_verdict_and_not_a_codex_failure(self):
        self.serve()
        self.claude("", rc=1, err="boom")
        result = self.direct()
        self.assertEqual((result.exit_code, result.status), (4, "no-verdict"))
        self.assertEqual(self.attempts_log(), [])
        self.assertEqual(self.sb.calls_of("codex"), [])

    def test_a_pr_that_moved_during_the_review_gets_a_head_moved_round_and_no_comment(self):
        self.serve()
        self.claude(GO)
        moved = "c" * 40
        self.gh.configure(view=[{}, {}, {"patch": {"headRefOid": moved}}], api={
            "contents/.boss/deploy.json": deploy_answer(),
            "compare/main...%s" % self.head: compare_answer(["tests/test_a.py"])})
        result = self.direct()
        self.assertEqual((result.exit_code, result.status), (6, "head-moved"))
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.attempts_log(), [])

    def test_the_classification_reads_the_base_list_and_the_compare_of_this_head(self):
        self.serve()
        self.claude(GO)
        self.direct()
        endpoints = [c.argv[1] for c in self.api_calls()]
        self.assertIn("repos/Owner/Repo/contents/.boss/deploy.json?ref=main", endpoints)
        self.assertIn("repos/Owner/Repo/compare/main...%s" % self.head, endpoints)


class Refusals(Direct):
    """Fail closed: nothing is claimed, no model is run, no comment is posted, the exit is 5."""

    def refused(self, *needles):
        result, err = self.stderr_of(self.direct)
        self.assertNothingHappened(result)
        for needle in needles:
            self.assertIn(needle, err)
        return err

    def test_a_code_file_is_refused_and_named(self):
        self.serve(files=("tests/test_a.py", "skills/boss/boss_review.py", "README.md"))
        self.refused("skills/boss/boss_review.py")

    def test_every_file_not_tests_or_docs_is_named_up_to_five(self):
        self.serve(files=("a.py", "b.py", "tests/test_a.py"))
        self.refused("a.py", "b.py")

    def test_an_instruction_file_is_code_even_under_docs_or_matching_test_paths(self):
        self.serve(files=("docs/SKILL.md", "tests/AGENTS.md", "README.md"))
        self.refused("docs/SKILL.md", "tests/AGENTS.md")

    def test_a_workflow_is_never_docs_or_tests(self):
        self.serve(files=(".github/workflows/ci.yml", "tests/test_a.py"))
        self.refused(".github/workflows/ci.yml")

    def test_a_docs_file_outside_the_narrow_set_is_refused(self):
        self.serve(files=("notes/plan.md",))
        self.refused("notes/plan.md")

    def test_a_compare_that_is_ahead_and_lists_no_file_is_refused(self):
        self.serve(compare=compare_answer([]))
        self.refused("compare-no-files")

    def test_an_identical_compare_has_no_file_to_judge_and_is_refused(self):
        self.serve(compare=compare_answer([], status="identical"))
        self.refused("(no file)")

    def test_a_compare_that_fails_is_refused(self):
        self.serve(compare={"raw": "", "rc": 1, "err": "HTTP 502"})
        self.refused("compare-failed")

    def test_a_compare_with_no_json_is_refused(self):
        self.serve(compare={"raw": "<html>"})
        self.refused("compare-failed")

    def test_a_compare_with_no_file_list_is_refused(self):
        self.serve(compare={"raw": json.dumps({"status": "ahead"})})
        self.refused("compare-failed")

    def test_a_compare_that_may_be_cut_short_is_refused(self):
        self.serve(compare=compare_answer(["tests/test_%d.py" % i for i in range(bm.COMPARE_FILES)]))
        self.refused("compare-truncated")

    def test_a_compare_status_that_is_not_the_prs_own_is_refused(self):
        self.serve(compare=compare_answer(["tests/test_a.py"], status="behind"))
        self.refused("compare-not-ahead")

    def test_a_file_entry_that_cannot_be_read_is_refused(self):
        self.serve(compare={"raw": json.dumps({"status": "ahead", "files": [{"name": "x"}]})})
        self.refused("compare-failed")

    def test_no_deploy_list_is_refused(self):
        self.serve(deploy={"raw": "", "rc": 1, "err": "HTTP 404"})
        self.refused("test_paths")

    def test_an_unreadable_deploy_list_is_refused(self):
        self.serve(deploy={"raw": "not json"})
        self.refused("test_paths")

    def test_a_deploy_list_with_no_test_paths_is_refused(self):
        self.serve(deploy=deploy_answer({"version": 1, "non_deploying": []}))
        self.refused("test_paths")

    def test_an_invalid_test_paths_value_is_refused(self):
        self.serve(deploy=deploy_answer({"version": 1, "non_deploying": [], "test_paths": "tests/*"}))
        self.refused("test_paths")

    def test_a_gh_api_that_has_no_answer_at_all_is_refused(self):
        self.gh.configure(api={})
        self.refused()

    def test_the_refusal_comes_before_the_model_and_before_the_pr_text_is_read_for_a_brief(self):
        self.serve(files=("src/x.py",))
        self.direct()
        self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh") if c.argv[0] == "pr"], ["view"])


class SoundnessOfTheChainsAnswer(unittest.TestCase):
    """`_sound` with `direct`: exactly one attempt, the fallback's; a Codex attempt in the answer is a contradiction."""

    def result(self, *attempts, reviewer="opus", word="GO"):
        output = "VERDICT: %s\n" % word
        return {"reviewer": reviewer, "output": output if reviewer != "none" else "",
                "parsed": {"word": word, "reason": "x"} if reviewer != "none" else None,
                "attempts": [dict({"reviewer": "opus", "reason": "answered", "output": output, "exit_code": 0,
                                   "stderr_tail": "", "model": MODEL}, **a) for a in attempts]}

    def test_one_opus_attempt_is_sound(self):
        self.assertTrue(br._sound(self.result({}), 0, br.fallback_spec(), direct=True))

    def test_a_codex_attempt_ahead_of_it_is_not_in_a_direct_run(self):
        data = self.result({"reviewer": "codex", "reason": "absent", "output": "", "exit_code": None, "model": None}, {})
        self.assertFalse(br._sound(data, 0, br.fallback_spec(), direct=True))

    def test_a_codex_attempt_alone_is_not(self):
        data = self.result({"reviewer": "codex", "model": None}, reviewer="codex")
        self.assertFalse(br._sound(data, 0, br.fallback_spec(), direct=True))

    def test_the_same_result_is_unsound_without_direct_because_a_codex_attempt_comes_first(self):
        self.assertFalse(br._sound(self.result({}), 0, br.fallback_spec()))

    def test_a_direct_run_with_no_answer_is_sound_when_it_says_none(self):
        data = self.result({"reason": "noverdict", "output": "ramble"}, reviewer="none", word="GO")
        self.assertTrue(br._sound(data, 1, br.fallback_spec(), direct=True))

    def test_a_direct_run_needs_a_fallback_to_name_the_attempt(self):
        self.assertFalse(br._sound(self.result({}), 0, None, direct=True))


class TheCommand(Direct):
    def args(self, *extra):
        return ["--repo", REPO, "--pr", str(PR), "--checkout", str(self.checkout), "--author", AUTHOR, *extra]

    def main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = br.main(self.args(*extra))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_the_flag_runs_a_direct_pass_and_prints_a_line_that_says_so(self):
        self.serve()
        self.claude(GO)
        code, out, err = self.main("--opus-direct")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("Direct Opus review 1: GO (posted) "), out)
        self.assertEqual(self.sb.calls_of("codex"), [])

    def test_the_command_refuses_a_code_pr_with_exit_5_and_the_file_on_stderr(self):
        self.serve(files=("skills/boss/boss_merge.py",))
        code, out, err = self.main("--opus-direct")
        self.assertEqual(code, 5)
        self.assertEqual(out, "")
        self.assertIn("skills/boss/boss_merge.py", err)
        self.expect["claude"] = 0

    def test_it_does_not_take_a_track_the_fallback_and_the_health_sync_are_not_in_this_path(self):
        code, out, err = self.main("--opus-direct", "--track", "t")
        self.assertEqual(code, 2)
        self.assertIn("--track", err)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.expect["claude"] = 0

    def test_it_does_not_combine_with_waive_or_check_fallback(self):
        for other in (["--waive", "--track", "t", "--test-cmd", "true"], ["--check-fallback"]):
            with self.subTest(other):
                code, out, err = self.main("--opus-direct", *other)
                self.assertEqual(code, 2)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.expect["claude"] = 0

    def test_it_still_needs_repo_pr_checkout_and_author(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            br.main(["--opus-direct", "--repo", REPO])
        self.assertEqual(raised.exception.code, 2)
        self.expect["claude"] = 0

    def test_the_api_refuses_opus_direct_with_a_track_too(self):
        with self.assertRaises(ValueError):
            self.review(opus_direct=True, track="t")
        self.expect["claude"] = 0

    def test_the_api_refuses_opus_direct_with_allow_fallback(self):
        with self.assertRaises(ValueError):
            self.review(opus_direct=True, allow_fallback=True)
        self.expect["claude"] = 0


if __name__ == "__main__":
    unittest.main()
