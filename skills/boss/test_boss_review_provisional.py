#!/usr/bin/env python3
"""Tests for the fallback review of boss_review.py (ticket 08): Codex does not answer, the confined
fallback does, and the verdict is posted labelled and recorded as provisional.

Run: python3 skills/boss/test_boss_review_provisional.py

Every test goes through hermetic.Sandbox, as test_boss_review.py does: `codex`, `claude` and `gh` are
stubs that log their argv, stdin and working directory, and a test fails if one of the three resolves
outside the stub directory (R25) or if a stub was called a number of times other than the test expected.
The fallback is reached through `review(..., allow_fallback=True, track="t")`: since ticket 06a it runs only where the
track's tracker exists, because every provisional GO is listed there before it is posted. The sandbox holds that
tracker (pm/t.md) and stubs `boss-alert`, so no test writes a real tracker or raises a real alert.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import policy  # noqa: E402
import reviewer_chain as rc  # noqa: E402
from test_boss_review import AUTHOR, PR, REPO, Base as ReviewBase  # noqa: E402

MODEL = "claude-opus-5-5"
LAST = "Same model family as the workers, so Codex re-reviews this head before any deploy."
RAMBLE = "I would need more context before I can say anything about this."
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2"


class Base(ReviewBase):
    def setUp(self):
        super().setUp()
        self.expect = {"claude": 0, "codex": 0}
        self.alert = self.sb.stub("boss-alert")
        pm = self.sb.cfg / "pm"
        for key, value in (("BOSS_ALERT", str(self.alert)), ("BOSS_LADDER_PM", str(pm)),
                           ("BOSS_LADDER_STATE", str(self.sb.side / "ladder.json"))):
            patcher = mock.patch.dict(os.environ, {key: value})
            patcher.start()
            self.addCleanup(patcher.stop)
        self.make_tracker()

    def make_tracker(self):
        pm = self.sb.cfg / "pm"
        pm.mkdir(parents=True, exist_ok=True)
        self.tracker = pm / "t.md"
        self.tracker.write_text("# t\n\n## Open blockers\n", encoding="utf-8")

    def setUp_clean(self):
        super().setUp_clean()
        self.make_tracker()          # setUp_clean empties the config dir, tracker included

    def tearDown(self):
        self.sb.guard()
        self.assertEqual(os.environ["BOSS_ALERT"], str(self.alert), "BOSS_ALERT must be the stub")
        self.assertEqual(self.sb.calls_of("boss-alert"), [], "no alert is raised by a single review")
        for name, count in self.expect.items():
            self.assertEqual(len(self.sb.calls_of(name)), count, "calls the %s stub logged" % name)
        for call in self.sb.calls_of("gh"):
            self.assertGhCallIsScoped(call.argv)

    def claude(self, answer="VERDICT: GO\n", **kw):
        self.expect["claude"] = 1
        return self.sb.stub("claude", answer=answer, **kw)

    def codex(self, **kw):
        self.expect["codex"] = 1
        return super().codex(**kw)

    def fallback_review(self, **kw):
        return self.review(allow_fallback=True, track="t", **kw)

    def assertGhVerbs(self, *verbs):
        """The exact `gh pr` verbs the review used, in order: view, diff, the recheck, the read under
        the lock, then the comment when one was posted."""
        self.assertEqual([c.argv[1] for c in self.sb.calls_of("gh")], list(verbs))

    def assertClaudeCall(self, fallback_timeout=policy.REVIEW_FALLBACK_TIMEOUT):
        """The one `claude` call is exactly the confined call, in the checkout, on this PR's brief."""
        (call,) = self.sb.calls_of("claude")
        brief = call.argv[-1]
        self.assertIn(self.head, brief)
        self.assertEqual(call.argv, rc.claude_argv(br.fallback_spec(timeout=fallback_timeout), brief)[1:])
        for flag in ("--restricted", "--safe-mode", "--tools"):
            self.assertIn(flag, call.argv)
        self.assertEqual(call.cwd, os.path.realpath(self.checkout))
        return call

    def head_line(self, n, model, reason, verdict, author=AUTHOR):
        return ("Fallback review %d (%s, Codex unavailable: %s; run by %s)\nHead: %s\nVerdict: %s"
                % (n, model, reason, author, self.head, verdict))


class FallbackRuns(Base):
    def test_codex_absent_and_a_fallback_go_is_posted_as_provisional(self):
        self.claude("FINDING: none\nVERDICT: GO\nREASON: fine\n")
        result = self.fallback_review()
        self.assertEqual(result, br.ReviewResult(0, 1, "posted", "GO", self.round_file(1), "provisional"))
        self.assertClaudeCall()
        self.assertGhVerbs("view", "diff", "view", "view", "view", "comment")      # the last view: after the list write
        (comment,) = self.comments()
        self.assertEqual(comment.argv[-1], self.head_line(1, MODEL, "absent", "provisional GO")
                         + "\n\n    FINDING: none\n\n" + LAST)
        record = self.record(1)
        self.assertEqual({k: record[k] for k in ("reviewer", "model", "kind", "verdict", "status")},
                         {"reviewer": "opus", "model": MODEL, "kind": "provisional", "verdict": "GO",
                          "status": "posted"})
        self.assertEqual([(a["reviewer"], a["reason"], a["model"]) for a in record["attempts"]],
                         [("codex", "absent", None), ("opus", "answered", MODEL)])
        self.assertEqual([(l["reviewer"], l["reason"], l["round"]) for l in self.attempts_log()],
                         [("codex", "absent", 1), ("opus", "answered", 1)])
        self.assertEqual(self.round_file(1, "out").read_text(encoding="utf-8"),
                         "FINDING: none\nVERDICT: GO\nREASON: fine\n")

    def test_a_codex_timeout_and_a_fallback_go(self):
        self.codex(hang=True)
        self.claude()
        result = self.fallback_review(codex_timeout=1)
        self.assertEqual((result.exit_code, result.status, result.kind), (0, "posted", "provisional"))
        self.assertClaudeCall()
        self.assertEqual(self.comments()[0].argv[-1], self.head_line(1, MODEL, "timeout", "provisional GO")
                         + "\n\n" + LAST)
        self.assertEqual([a["reason"] for a in self.record(1)["attempts"]], ["timeout", "answered"])

    def test_a_codex_error_and_a_fallback_no_go_keep_the_exit_code_and_the_redacted_stderr(self):
        self.codex(rc=3, err="codex: not signed in\ntoken %s" % TOKEN)
        self.claude("FINDING: boss_review.py:1 loses a round\nVERDICT: NO-GO\n")
        result = self.fallback_review()
        self.assertEqual(result, br.ReviewResult(3, 1, "posted", "NO-GO", self.round_file(1), "provisional"))
        self.assertClaudeCall()
        (comment,) = self.comments()
        self.assertEqual(comment.argv[-1],
                         self.head_line(1, MODEL, "error", "NO-GO")
                         + "\n\n    FINDING: boss_review.py:1 loses a round"
                         + "\n\nCodex exited with code 3. Codex said:\n\n    codex: not signed in\n"
                         + "    token [redacted]\n\n" + LAST)
        self.assertNotIn(TOKEN, comment.argv[-1])
        first = self.record(1)["attempts"][0]
        self.assertEqual((first["reason"], first["exit_code"]), ("error", 3))
        self.assertIn("not signed in", first["stderr_tail"])
        self.assertEqual(self.record(1)["verdict"], "NO-GO")

    def test_both_down_posts_nothing_and_keeps_both_attempts(self):
        self.claude(answer=None, rc=1, err="claude: overloaded")
        result = self.fallback_review()
        self.assertEqual(result, br.ReviewResult(4, 1, "no-verdict", None, self.round_file(1), "provisional"))
        self.assertClaudeCall()
        self.assertGhVerbs("view", "diff", "view", "view")
        self.assertEqual(self.comments(), [])
        record = self.record(1)
        self.assertEqual({k: record[k] for k in ("reviewer", "model", "kind", "verdict")},
                         {"reviewer": "none", "model": None, "kind": "provisional", "verdict": None})
        self.assertEqual([(a["reviewer"], a["reason"]) for a in record["attempts"]],
                         [("codex", "absent"), ("opus", "error")])
        self.assertEqual([(l["reviewer"], l["round"]) for l in self.attempts_log()],
                         [("codex", 1), ("opus", 1)])
        self.assertEqual(self.round_file(1, "out").read_text(encoding="utf-8"),
                         "--- codex absent ---\n--- opus error ---\n")

    def test_a_codex_answer_without_a_verdict_does_not_run_the_fallback(self):
        self.codex(answer=RAMBLE)
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.status, result.kind), (4, "no-verdict", "codex"))
        self.assertEqual(self.sb.calls_of("claude"), [])
        self.assertEqual([a["reviewer"] for a in self.record(1)["attempts"]], ["codex"])
        self.assertEqual(self.comments(), [])

    def test_a_codex_go_is_posted_as_before_with_the_fallback_allowed(self):
        self.codex(answer="VERDICT: GO")
        result = self.fallback_review()
        self.assertEqual(result, br.ReviewResult(0, 1, "posted", "GO", self.round_file(1), "codex"))
        self.assertEqual(self.sb.calls_of("claude"), [])
        self.assertEqual(self.comments()[0].argv[-1], self.body(1, "GO"))
        record = self.record(1)
        self.assertEqual((record["reviewer"], record["model"], record["kind"]), ("codex", None, "codex"))

    def test_a_model_the_claude_stub_rejects_gives_no_verdict_and_names_no_model_outside_the_attempts(self):
        self.claude(answer=None, rc=1, err="There's an issue with the selected model (%s)" % MODEL)
        result = self.fallback_review()
        self.assertEqual((result.exit_code, result.status), (4, "no-verdict"))
        self.assertClaudeCall()
        self.assertEqual(self.comments(), [])
        record = self.record(1)
        attempts = record.pop("attempts")
        self.assertEqual((record["reviewer"], record["model"], record["verdict"]), ("none", None, None))
        self.assertNotIn(MODEL, json.dumps(record))
        self.assertNotIn("opus", json.dumps(record).lower())
        self.assertEqual(attempts[1]["model"], MODEL)          # only the private attempts hold the id
        for line in self.attempts_log():
            self.assertNotIn("model", line)
            self.assertNotIn(MODEL, json.dumps(line))

    def test_the_command_line_without_a_track_cannot_reach_the_fallback(self):
        self.gh.configure()
        self.assertEqual(br.main(["--repo", REPO, "--pr", str(PR), "--checkout", str(self.checkout),
                                  "--author", AUTHOR]), 4)
        self.assertEqual(self.sb.calls_of("claude"), [])        # Codex is absent, and still no fallback
        self.assertEqual(self.record(1)["kind"], "codex")

    def test_a_fallback_answer_with_a_nul_is_refused_with_both_attempts_logged_and_nothing_claimed(self):
        self.claude(answer=b"VERDICT: GO\0")
        result = self.fallback_review()
        self.assertClaudeCall()
        self.assertEqual(result, br.ReviewResult(7, None, None, None, None, None))
        self.assertEqual(self.comments(), [])
        self.assertEqual(list(self.reviews.glob("*/*/pr*/round*")), [])
        self.assertEqual([(l["reviewer"], l["reason"], l["round"]) for l in self.attempts_log()],
                         [("codex", "absent", None), ("opus", "answered", None)])

    def test_a_codex_only_run_keeps_its_record(self):
        self.codex(answer="VERDICT: GO")
        result = self.review()
        record = self.record(1)
        self.assertEqual((record["kind"], record["model"], record["reviewer"]), ("codex", None, "codex"))
        self.assertEqual(result.kind, "codex")


class ChildProcess(Base):
    def spawned(self):
        """The (argv, timeout) of each chain the review started."""
        calls = []
        real = br._spawn

        def spy(argv, timeout, *a, **kw):
            if len(argv) > 1 and argv[1] == str(br.CHAIN):
                calls.append((argv, timeout))
            return real(argv, timeout, *a, **kw)
        return calls, mock.patch.object(br, "_spawn", spy)

    def test_the_deadline_is_both_waits_and_the_slack_with_the_fallback_and_only_codexs_without(self):
        for allow, expected in ((True, 3 + 7 + policy.REVIEW_CHAIN_SLACK), (False, 3 + policy.REVIEW_CHAIN_SLACK)):
            with self.subTest(allow_fallback=allow):
                self.setUp_clean()
                self.sb.stub("claude", answer="VERDICT: GO")
                self.expect = {"claude": 0, "codex": 0}
                self.codex(answer="VERDICT: GO")
                calls, patch = self.spawned()
                with patch:
                    self.review(codex_timeout=3, fallback_timeout=7, allow_fallback=allow, track="t")
                ((argv, timeout),) = calls
                self.assertEqual(timeout, expected)
                self.assertEqual("--no-fallback" in argv, not allow)
                self.assertEqual(self.sb.calls_of("claude"), [])

    def test_the_whole_spec_travels_in_the_chains_command_line(self):
        self.codex(answer="VERDICT: GO")
        calls, patch = self.spawned()
        with patch:
            self.fallback_review(fallback_timeout=9)
        ((argv, _),) = calls
        flags = rc.fallback_flags(br.fallback_spec(timeout=9))
        at = argv.index(flags[0])
        self.assertEqual(argv[at:at + len(flags)], flags)
        self.assertIn("--restricted", argv[argv.index("--fallback-extra-args") + 1])
        self.assertIn("--safe-mode", argv[argv.index("--fallback-extra-args") + 1])
        self.assertEqual(argv[argv.index("--fallback-env-unset") + 1].split(","),
                         list(policy.REVIEW_FALLBACK_ENV_UNSET))

    def test_a_slow_fallback_after_a_codex_that_used_its_wait_is_not_cut_off_by_the_deadline(self):
        # Codex ignores SIGTERM: it is stopped at about 1 + TERM_GRACE (2) = 3 s; the fallback then takes
        # 5 s, so the chain ends near 8 s plus start-up. Without fallback_timeout in the deadline that is
        # codex_timeout + slack = 1 + 6 = 7 s and the chain would be killed first; with it the deadline is
        # 1 + 10 + 6 = 17 s and the answer is posted.
        self.codex(hang=True, ignore_term=True)
        self.claude(delay=5)
        with mock.patch.object(policy, "REVIEW_CHAIN_SLACK", 6):
            result = self.review(codex_timeout=1, fallback_timeout=10, allow_fallback=True, track="t")
        self.assertEqual((result.exit_code, result.status, result.kind), (0, "posted", "provisional"))
        self.assertEqual(len(self.comments()), 1)
        self.assertClaudeCall(fallback_timeout=10)

    def test_the_claude_child_has_none_of_the_removed_variables_and_codex_still_does(self):
        names = policy.REVIEW_FALLBACK_ENV_UNSET
        self.sb.stub_script("codex", 'env > "$R/side/codex.env"\nexit 3')
        self.sb.stub_script("claude", 'env > "$R/side/claude.env"\necho "VERDICT: GO"')
        self.expect = {"claude": 1, "codex": 1}
        with mock.patch.dict(os.environ, {n: "/planted" for n in names}):
            result = self.fallback_review()
        self.assertEqual(result.status, "posted")
        seen = {line.split("=", 1)[0] for line in (self.sb.side / "claude.env").read_text().splitlines()}
        self.assertEqual(seen & set(names), set())
        codex_seen = {line.split("=", 1)[0] for line in (self.sb.side / "codex.env").read_text().splitlines()}
        self.assertIn("CLAUDE_CODE_PLUGIN_DIRS", codex_seen)
        self.assertClaudeCall()


class ChainShape(Base):
    """What the review accepts of the chain's result when the fallback is on."""

    def attempt(self, reviewer="codex", reason="absent", output="", model=None, exit_code=None):
        return {"reviewer": reviewer, "reason": reason, "output": output, "exit_code": exit_code,
                "stderr_tail": "", "model": model}

    def stand_in(self, attempts, reviewer="none", output="", word=None, code=1):
        data = {"reviewer": reviewer, "output": output,
                "parsed": None if word is None else {"word": word, "reason": "x"}, "attempts": attempts}
        path = self.sb.root / "fake_chain.py"
        path.write_text("import sys\nsys.stdout.write(%r)\nsys.exit(%d)\n" % (json.dumps(data), code))
        return mock.patch.object(br, "CHAIN", path)

    GO = "VERDICT: GO"

    def good_pair(self):
        return [self.attempt(), self.attempt("opus", "answered", self.GO, MODEL, 0)]

    def test_a_codex_attempt_then_the_specs_fallback_is_accepted(self):
        with self.stand_in(self.good_pair(), "opus", self.GO, "GO", 0):
            result = self.fallback_review()
        self.assertEqual((result.exit_code, result.kind), (0, "provisional"))

    def test_other_shapes_are_exit_seven_before_any_claim(self):
        answered = self.attempt("opus", "answered", self.GO, MODEL, 0)
        cases = {
            "the order reversed": ([answered, self.attempt()], "opus", self.GO, "GO", 0),
            "a third attempt": ([*self.good_pair(), self.attempt("opus", "error", "", MODEL, 1)],
                                "opus", self.GO, "GO", 0),
            "a fallback after a Codex answer": ([self.attempt("codex", "answered", self.GO, None, 0), answered],
                                                "codex", self.GO, "GO", 0),
            "a fallback after a Codex noverdict": ([self.attempt("codex", "noverdict", "x", None, 0), answered],
                                                   "opus", self.GO, "GO", 0),
            "a fallback model that is not the spec's": ([self.attempt(), dict(answered, model="claude-haiku-5-5")],
                                                        "opus", self.GO, "GO", 0),
            "a fallback with no model": ([self.attempt(), dict(answered, model=None)], "opus", self.GO, "GO", 0),
            "a fallback that is not the spec's": ([self.attempt(), dict(answered, reviewer="fable")],
                                                  "fable", self.GO, "GO", 0),
            "a result that names Codex for the fallback's answer": (self.good_pair(), "codex", self.GO, "GO", 0),
            "an answer the exit code denies": (self.good_pair(), "opus", self.GO, "GO", 1),
            "a result with no reviewer beside an answer": (self.good_pair(), "none", "", None, 0),
        }
        for what, (attempts, reviewer, output, word, code) in cases.items():
            with self.subTest(what=what):
                self.setUp_clean()
                self.expect = {"claude": 0, "codex": 0}
                self.sb.stub("claude", answer="VERDICT: GO")
                self.gh.configure()
                with self.stand_in(attempts, reviewer, output, word, code):
                    result = self.fallback_review()
                self.assertEqual((result.exit_code, result.round), (7, None))
                self.assertEqual(self.comments(), [])
                self.assertFalse(self.reviews.exists())
                self.assertEqual((self.sb.calls_of("claude"), self.sb.calls_of("codex")), ([], []))
                self.assertGhVerbs("view", "diff", "view")
                self.sb.guard()

    def test_a_second_attempt_is_not_accepted_when_the_fallback_is_off(self):
        with self.stand_in(self.good_pair(), "opus", self.GO, "GO", 0):
            result = self.review()
        self.assertEqual((result.exit_code, result.round), (7, None))


class Wording(Base):
    def test_the_codex_path_of_comment_body_is_unchanged(self):
        self.assertEqual(br.comment_body(3, "a", "h" * 40, "GO", "    F"), "Codex review 3 (run by a)\nHead: %s\nVerdict: GO\n\n    F" % ("h" * 40))

    def test_a_fallback_go_and_a_fallback_no_go_each_have_their_text(self):
        label = br.FallbackLabel(MODEL, "timeout")
        self.assertEqual(br.comment_body(2, "a", "h" * 40, "GO", fallback=label),
                         "Fallback review 2 (%s, Codex unavailable: timeout; run by a)\nHead: %s\n"
                         "Verdict: provisional GO\n\n%s" % (MODEL, "h" * 40, LAST))
        self.assertEqual(br.comment_body(2, "a", "h" * 40, "NO-GO", "    F", fallback=label),
                         "Fallback review 2 (%s, Codex unavailable: timeout; run by a)\nHead: %s\n"
                         "Verdict: NO-GO\n\n    F\n\n%s" % (MODEL, "h" * 40, LAST))

    def test_it_is_never_headed_codex_review(self):
        text = br.comment_body(2, "a", "h" * 40, "GO", fallback=br.FallbackLabel(MODEL, "absent"))
        self.assertNotIn("Codex review", text)
        self.assertTrue(text.startswith("Fallback review 2 ("))
        self.assertTrue(text.endswith(LAST))

    def test_an_error_with_no_exit_code_says_codex_did_not_start(self):
        text = br.comment_body(2, "a", "h" * 40, "GO", fallback=br.FallbackLabel(MODEL, "error", None, "    boom"))
        self.assertIn("Codex could not be started. Codex said:\n\n    boom", text)
        self.assertNotIn("None", text)

    def test_an_error_with_no_stderr_says_so(self):
        text = br.comment_body(2, "a", "h" * 40, "GO", fallback=br.FallbackLabel(MODEL, "error", 9, ""))
        self.assertIn("Codex exited with code 9. It said nothing.", text)

    def test_the_stderr_block_is_inert_text(self):
        hostile = ["@user please look", "[x](http://h)", "![i](u)", "<img src=x onerror=1>", "",
                   "```", "ctrl\x01 and ‮ override and   separator", "bearer %s" % TOKEN]
        block = br.stderr_block("\n".join(hostile))
        lines = block.split("\n")
        self.assertEqual(len(lines), 5)                 # the last five non-blank lines
        for line in lines:
            self.assertTrue(line.startswith("    "), line)
        self.assertNotIn(TOKEN, block)
        self.assertNotIn("\x01", block)
        self.assertNotIn("‮", block)
        self.assertNotIn(" ", block)
        self.assertIn("\\u0001", block)
        self.assertIn("[redacted]", block)
        everything = br.stderr_block("@user please look\n[x](http://h)\n![i](u)\n<img>\n```")
        self.assertEqual({l[:4] for l in everything.split("\n")}, {"    "})
        self.assertEqual(br.stderr_block(""), "")
        self.assertEqual(br.stderr_block("\n  \n"), "")

    def test_long_lines_are_cut_or_not_shown(self):
        cut = br.stderr_block("x" * 1000)
        self.assertEqual(len(cut), 4 + policy.REVIEW_FINDING_CHARS)
        self.assertTrue(cut.endswith("…"))
        self.assertIn("not shown", br.stderr_block("y" * (policy.REVIEW_FINDING_READ + 1)))

    def test_the_posted_comment_keeps_codexs_stderr_inside_the_indented_block(self):
        self.codex(rc=3, err="@user\n[x](http://h)\n![i](u)\n<img>\n\n```\nctrl\x01\nghp_%s" % TOKEN[4:])
        self.claude()
        self.fallback_review()
        (comment,) = self.comments()
        body = comment.argv[-1]
        fixed = {self.head_line(1, MODEL, "error", "provisional GO").split("\n")[0],
                 "Head: %s" % self.head, "Verdict: provisional GO", "",
                 "Codex exited with code 3. Codex said:", LAST}
        for line in body.split("\n"):
            self.assertTrue(line in fixed or line.startswith("    "), repr(line))
        self.assertNotIn(TOKEN, body)
        self.assertNotIn("\x01", body)
        self.assertIn("    ![i](u)", body)


if __name__ == "__main__":
    unittest.main()
