#!/usr/bin/env python3
"""Tests for reviewer_chain.py: the chain that picks a reviewer, hermetically.

Run: python3 skills/boss/test_reviewer_chain.py

The chain asks Codex, then (optionally) a fallback model through `claude`, and
reports which one answered. Every test goes through hermetic.Sandbox, so `codex`
and `claude` are stubs that log their argv and stdin, and nothing real is called.
Two seams are tested: `run_chain` in-process, and the command line.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reviewer_chain as rc  # noqa: E402
from hermetic import Sandbox, alive  # noqa: E402

HAIKU_ID = "claude-haiku-4-5-20251001"
CODEX_FIXED = ["exec", "-s", "read-only", "--skip-git-repo-check",
               "-c", 'model_reasoning_effort="medium"', "-o"]


def approve(reason="ok"):
    return "VERDICT: APPROVE\nREASON: %s" % reason


def reject(reason="too wide"):
    return "VERDICT: REJECT\nREASON: %s" % reason


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        for patcher in (mock.patch.dict(os.environ, self.sb.env, clear=True),
                        mock.patch.object(tempfile, "tempdir", str(self.sb.tmp))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def chain(self, prompt="the prompt", **kw):
        kw.setdefault("words", rc.APPROVE_REJECT)
        return rc.run_chain(prompt, **kw)

    def assertNotCalled(self, *names):
        for name in names:
            self.assertEqual(self.sb.calls_of(name), [], name)


class CodexAnswers(Base):
    def test_codex_answer_is_the_result_and_codex_is_called_as_boss_run_called_it(self):
        self.sb.stub("codex", answer=approve("matches the intent"))
        result = self.chain("PROMPT TEXT")
        self.assertEqual(result.reviewer, "codex")
        self.assertEqual(result.parsed, rc.Verdict("APPROVE", "matches the intent"))
        self.assertEqual(result.output, approve("matches the intent"))
        (attempt,) = result.attempts
        self.assertEqual((attempt.reviewer, attempt.reason, attempt.exit_code, attempt.model),
                         ("codex", "answered", 0, None))
        (call,) = self.sb.calls_of("codex")
        self.assertEqual(call.argv[:7], CODEX_FIXED)
        self.assertEqual(len(call.argv), 9, call.argv)
        self.assertEqual(call.argv[8], "PROMPT TEXT")
        self.assertEqual(call.stdin, "")


class Fallbacks(Base):
    def test_codex_absent_then_the_fallback_answers_and_claude_is_called_as_before(self):
        self.sb.stub("claude", answer=reject("too wide"))
        result = self.chain("PROMPT TEXT", fallback=rc.HAIKU)
        self.assertEqual(result.reviewer, "haiku")
        self.assertEqual(result.parsed, rc.Verdict("REJECT", "too wide"))
        self.assertEqual(result.output, reject("too wide"))
        codex, haiku = result.attempts
        self.assertEqual((codex.reviewer, codex.reason, codex.exit_code, codex.model),
                         ("codex", "absent", None, None))
        self.assertEqual((haiku.reviewer, haiku.reason, haiku.exit_code, haiku.model),
                         ("haiku", "answered", 0, HAIKU_ID))
        (call,) = self.sb.calls_of("claude")
        self.assertEqual(call.argv, ["-p", "--model", HAIKU_ID, "PROMPT TEXT"])
        self.assertEqual(call.stdin, "")

    def test_both_absent_is_none_with_both_attempts_kept(self):
        result = self.chain(fallback=rc.HAIKU)
        self.assertEqual((result.reviewer, result.output, result.parsed), ("none", "", None))
        self.assertEqual([(a.reviewer, a.reason) for a in result.attempts],
                         [("codex", "absent"), ("haiku", "absent")])

    def test_without_a_fallback_the_chain_is_codex_only(self):
        self.sb.stub("claude", answer=approve())
        result = self.chain()
        self.assertEqual(result.reviewer, "none")
        self.assertEqual([(a.reviewer, a.reason) for a in result.attempts], [("codex", "absent")])
        self.assertNotCalled("claude")


RAMBLE = "I would need more context before I can say anything about this."


class Reasons(Base):
    def test_a_non_zero_exit_without_a_verdict_is_error_and_the_fallback_runs(self):
        self.sb.stub("codex", rc=3, err="codex: model overloaded")
        self.sb.stub("claude", answer=approve())
        result = self.chain(fallback=rc.HAIKU)
        codex = result.attempts[0]
        self.assertEqual((codex.reason, codex.exit_code, codex.output), ("error", 3, ""))
        self.assertEqual(codex.stderr_tail, "codex: model overloaded\n")
        self.assertEqual(result.reviewer, "haiku")

    def test_the_stderr_tail_is_kept_whole_at_2048_characters_and_cut_at_2049(self):
        for body_len, expect_dropped in ((2047, False), (2048, True)):
            with self.subTest(total=body_len + 1):
                sb = Sandbox()
                self.addCleanup(sb.cleanup)
                body = "S" + "x" * (body_len - 1)
                sb.stub("codex", rc=1, err=body)
                with mock.patch.dict(os.environ, sb.env, clear=True):
                    tail = self.chain().attempts[0].stderr_tail
                self.assertEqual(len(tail), 2048)
                self.assertEqual(tail, (body[1:] if expect_dropped else body) + "\n")

    def test_exit_zero_and_no_usable_verdict_is_noverdict_and_the_raw_answer_is_kept(self):
        self.sb.stub("codex", answer=RAMBLE)
        self.sb.stub("claude", answer=approve())
        result = self.chain(fallback=rc.HAIKU)
        codex = result.attempts[0]
        self.assertEqual((codex.reason, codex.exit_code, codex.output), ("noverdict", 0, RAMBLE))
        self.assertEqual(result.reviewer, "haiku")

    def test_an_empty_answer_with_exit_zero_is_noverdict(self):
        self.sb.stub("codex")
        (codex,) = self.chain().attempts
        self.assertEqual((codex.reason, codex.exit_code, codex.output), ("noverdict", 0, ""))

    def test_a_fallback_whose_when_leaves_out_noverdict_is_not_called_after_one(self):
        self.sb.stub("codex", answer=RAMBLE)
        self.sb.stub("claude", answer=approve())
        fb = rc.Fallback("haiku", HAIKU_ID, when=("absent", "timeout", "error"))
        result = self.chain(fallback=fb)
        self.assertEqual(result.reviewer, "none")
        self.assertEqual([(a.reviewer, a.reason) for a in result.attempts],
                         [("codex", "noverdict")])
        self.assertNotCalled("claude")

    def test_a_verdict_after_a_non_zero_exit_is_still_answered_and_keeps_the_exit_code(self):
        self.sb.stub("codex", answer=approve(), rc=7)
        result = self.chain()
        (codex,) = result.attempts
        self.assertEqual((codex.reason, codex.exit_code), ("answered", 7))
        self.assertEqual(result.reviewer, "codex")

    def test_a_verdict_only_in_codex_stdout_is_not_an_answer(self):
        self.sb.stub("codex", out=approve())
        (codex,) = self.chain().attempts
        self.assertEqual((codex.reason, codex.output), ("noverdict", ""))

    def test_both_down_with_errors_is_none_and_each_attempt_says_why(self):
        self.sb.stub("codex", rc=2, err="boom")
        self.sb.stub("claude", answer=RAMBLE)
        result = self.chain(fallback=rc.HAIKU)
        self.assertEqual((result.reviewer, result.output, result.parsed), ("none", "", None))
        self.assertEqual([(a.reviewer, a.reason) for a in result.attempts],
                         [("codex", "error"), ("haiku", "noverdict")])


class Timeouts(Base):
    def child_pid(self):
        return int((self.sb.root / "child.pid").read_text())

    def test_a_hung_codex_is_timeout_with_no_exit_code_and_the_fallback_runs(self):
        self.sb.stub("codex", hang=True)
        self.sb.stub("claude", answer=approve())
        started = time.monotonic()
        result = self.chain(codex_timeout=1, fallback=rc.HAIKU)
        self.assertLess(time.monotonic() - started, 20)
        codex = result.attempts[0]
        self.assertEqual((codex.reason, codex.exit_code, codex.output), ("timeout", None, ""))
        self.assertEqual(result.reviewer, "haiku")

    def test_a_timeout_kills_the_reviewer_and_everything_it_started(self):
        self.sb.stub("codex", hang=True, child=True)
        self.chain(codex_timeout=1)
        pid = self.child_pid()
        self.assertFalse(alive(pid), "the reviewer's child survived the timeout")

    def test_a_reviewer_that_ignores_term_is_killed_after_the_grace_period(self):
        self.sb.stub("codex", hang=True, child=True, ignore_term=True)
        with mock.patch.object(rc, "TERM_GRACE", 0.5):
            self.chain(codex_timeout=1)
        self.assertFalse(alive(self.child_pid()), "SIGKILL never followed SIGTERM")

    def test_a_verdict_written_before_the_timeout_is_answered_with_exit_code_none(self):
        self.sb.stub("codex", answer=approve("early"), hang_after=True)
        result = self.chain(codex_timeout=1)
        (codex,) = result.attempts
        self.assertEqual((codex.reason, codex.exit_code), ("answered", None))
        self.assertEqual((result.reviewer, result.parsed), ("codex", rc.Verdict("APPROVE", "early")))

    def test_a_fallback_that_answered_before_hanging_is_answered_with_exit_code_none(self):
        self.sb.stub("claude", answer=reject("early"), hang_after=True)
        fb = rc.Fallback("haiku", HAIKU_ID, timeout=1)
        result = self.chain(fallback=fb)
        haiku = result.attempts[-1]
        self.assertEqual((haiku.reason, haiku.exit_code), ("answered", None))
        self.assertEqual(result.reviewer, "haiku")

    def test_a_descendant_that_escaped_the_group_and_holds_the_pipe_does_not_hang_the_chain(self):
        self.sb.stub("codex", answer=approve("done"), detached=True)
        started = time.monotonic()
        result = self.chain(codex_timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result.reviewer, "codex")

    def test_each_reviewer_has_its_own_timeout(self):
        self.sb.stub("codex", answer=approve(), delay=3)
        self.sb.stub("claude", answer=approve(), delay=3)
        fb = rc.Fallback("haiku", HAIKU_ID, timeout=6)
        result = self.chain(codex_timeout=1, fallback=fb)
        self.assertEqual([(a.reviewer, a.reason) for a in result.attempts],
                         [("codex", "timeout"), ("haiku", "answered")])


class Matching(Base):
    """The verdict vocabulary and its rule, read through a Codex answer."""

    def parsed(self, answer, words=rc.APPROVE_REJECT, **kw):
        self.sb.stub("codex", answer=answer)
        parsed = self.chain(words=words, **kw).parsed
        return None if parsed is None else parsed.word

    def check(self, cases, words=rc.APPROVE_REJECT, **kw):
        for answer, expected in cases:
            with self.subTest(answer=answer):
                self.assertEqual(self.parsed(answer, words, **kw), expected)

    def test_approve_reject_matches_the_word_as_a_prefix_as_boss_run_always_did(self):
        self.check([
            ("VERDICT: APPROVED", "APPROVE"), ("VERDICT: REJECTED", "REJECT"),
            ("verdict: approve", "APPROVE"), ("   \tVERDICT: REJECT", "REJECT"),
            ("VERDICT:APPROVE", "APPROVE"), ("VERDICT:    reject", "REJECT"),
            ("My VERDICT: APPROVE", None), ("> VERDICT: APPROVE", None),
            ("VERDICT: maybe", None), ("VERDICT:\nAPPROVE", None), ("APPROVE", None),
        ])

    def test_go_no_go_matches_whole_tokens_longest_word_first(self):
        self.check([
            ("VERDICT: GO", "GO"), ("VERDICT: NO-GO", "NO-GO"), ("verdict: no-go", "NO-GO"),
            ("  VERDICT:go", "GO"), ("VERDICT: GO.", "GO"), ("VERDICT: NO-GO, sadly", "NO-GO"),
            ("VERDICT: GOOD", None), ("VERDICT: GO-AHEAD", None), ("VERDICT: NOGO", None),
            ("VERDICT: NO-GOING", None), ("VERDICT: NO GO", None),
        ], words=rc.GO_NOGO)

    def test_a_plain_tuple_of_words_is_matched_as_whole_tokens(self):
        self.check([("VERDICT: NO-GO", "NO-GO"), ("VERDICT: GOOD", None)], words=("GO", "NO-GO"))

    def test_an_unknown_match_rule_is_refused(self):
        with self.assertRaises(ValueError):
            rc.Words(("GO",), match="fuzzy")

    def test_a_vocabulary_that_would_match_any_verdict_line_is_refused_before_anyone_is_asked(self):
        self.sb.stub("codex", answer="VERDICT: whatever")
        for words in ((), ("",), ("GO", " "), rc.Words(())):
            with self.subTest(words=tuple(words)), self.assertRaises(ValueError):
                self.chain(words=words)
        self.assertNotCalled("codex")

    def test_the_first_usable_line_wins_and_a_malformed_one_before_it_is_skipped(self):
        self.check([
            ("VERDICT: maybe\nVERDICT: REJECT", "REJECT"),
            ("VERDICT: APPROVE\nVERDICT: REJECT", "APPROVE"),
        ])

    def test_strict_turns_two_different_verdicts_into_noverdict_but_not_the_same_twice(self):
        self.check([
            ("VERDICT: APPROVE\nVERDICT: REJECT", None),
            ("VERDICT: maybe\nVERDICT: REJECT\nVERDICT: approve", None),
            ("VERDICT: APPROVE\nVERDICT: APPROVED", "APPROVE"),
            ("VERDICT: REJECT", "REJECT"),
        ], strict=True)

    def test_a_strict_conflict_is_a_noverdict_attempt_that_keeps_its_output(self):
        answer = "VERDICT: APPROVE\nVERDICT: REJECT"
        self.sb.stub("codex", answer=answer)
        (codex,) = self.chain(strict=True).attempts
        self.assertEqual((codex.reason, codex.output), ("noverdict", answer))

    def reason_of(self, answer):
        self.sb.stub("codex", answer=answer)
        return self.chain().parsed.reason

    def test_the_reason_is_the_first_reason_line_anywhere_in_the_output(self):
        for answer, expected in [
            ("VERDICT: APPROVE\nREASON: fine", "fine"),
            ("REASON: before\nVERDICT: REJECT", "before"),
            ("VERDICT: APPROVE\n  reason:   spaced out", "spaced out"),
            ("VERDICT: APPROVE\nREASON: one\nREASON: two", "one"),
            ("VERDICT: APPROVE", "(no reason given)"),
            ("VERDICT: APPROVE\nREASON:", "(no reason given)"),
            ("VERDICT: APPROVE\nREASON:   ", "(no reason given)"),
            ("VERDICT: APPROVE\nnot a REASON: x", "(no reason given)"),
        ]:
            with self.subTest(answer=answer):
                self.assertEqual(self.reason_of(answer), expected)

    def test_no_go_never_parses_as_go_whatever_order_the_words_come_in(self):
        for words in (("GO", "NO-GO"), ("NO-GO", "GO"), rc.GO_NOGO):
            with self.subTest(words=tuple(words)):
                self.assertEqual(self.parsed("VERDICT: NO-GO", words), "NO-GO")


class FallbackSpec(Base):
    def test_allowed_tools_reach_claude_ahead_of_print_so_the_prompt_is_not_swallowed(self):
        # `--allowedTools <tools...>` is variadic: a prompt placed after it would be read as a tool.
        self.sb.stub("claude", answer=approve())
        fb = rc.Fallback("haiku", HAIKU_ID, allowed_tools=("Read", "Grep"))
        self.chain("PROMPT TEXT", fallback=fb)
        (call,) = self.sb.calls_of("claude")
        self.assertEqual(call.argv, ["--allowedTools", "Read,Grep", "-p", "--model", HAIKU_ID,
                                     "PROMPT TEXT"])

    def test_an_empty_tool_list_is_refused_because_it_would_read_as_no_restriction(self):
        with self.assertRaises(ValueError):
            rc.Fallback("haiku", HAIKU_ID, allowed_tools=())

    def test_a_when_naming_a_reason_codex_cannot_have_is_refused(self):
        for bad in (("answered",), ("absent", "timeouts")):
            with self.subTest(when=bad), self.assertRaises(ValueError):
                rc.Fallback("haiku", HAIKU_ID, when=bad)

    def test_the_fallback_name_and_exact_model_id_come_from_the_spec(self):
        self.sb.stub("claude", answer=approve("by sonnet"))
        fb = rc.Fallback("sonnet", "claude-sonnet-5-5", timeout=30)
        result = self.chain(fallback=fb)
        self.assertEqual(result.reviewer, "sonnet")
        self.assertEqual(result.attempts[-1].model, "claude-sonnet-5-5")
        self.assertEqual(self.sb.calls_of("claude")[0].argv[:3], ["-p", "--model", "claude-sonnet-5-5"])


class Leftovers(Base):
    def assertNoTempFile(self):
        self.assertEqual(list(self.sb.tmp.iterdir()), [])

    def test_no_file_is_left_after_an_answer(self):
        self.sb.stub("codex", answer=approve())
        self.chain()
        self.assertNoTempFile()

    def test_no_file_is_left_after_an_error(self):
        self.sb.stub("codex", rc=1, err="boom")
        self.chain()
        self.assertNoTempFile()

    def test_no_file_is_left_after_a_timeout(self):
        self.sb.stub("codex", hang=True)
        self.chain(codex_timeout=1)
        self.assertNoTempFile()

    def test_the_file_codex_writes_to_is_in_the_temp_directory_while_it_runs(self):
        self.sb.stub("codex", answer=approve())
        self.chain()
        dest = self.sb.calls_of("codex")[0].argv[7]
        self.assertEqual(Path(dest).parent, self.sb.tmp)
        self.assertFalse(Path(dest).exists())


class Unrunnable(Base):
    def test_a_reviewer_that_cannot_be_started_is_an_error_with_no_exit_code(self):
        broken = self.sb.stubs / "codex"
        broken.write_text("#!/nonexistent/interpreter\n")
        broken.chmod(0o755)
        self.sb.stub("claude", answer=approve())
        result = self.chain(fallback=rc.HAIKU)
        codex = result.attempts[0]
        self.assertEqual((codex.reason, codex.exit_code), ("error", None))
        self.assertIn("No such file or directory", codex.stderr_tail)   # the OSError, as Python words it
        self.assertEqual(result.reviewer, "haiku")


class Cli(Base):
    """`python3 reviewer_chain.py ...`, as boss-run calls it."""

    def cli(self, *args, prompt="the prompt", prompt_file=True):
        argv = [sys.executable, str(HERE / "reviewer_chain.py")]
        if prompt_file:
            path = self.sb.work / "prompt.txt"
            path.write_text(prompt, encoding="utf-8")
            argv += ["--prompt-file", str(path)]
        return subprocess.run([*argv, *args], capture_output=True, text=True, env=self.sb.env,
                              cwd=str(self.sb.work), stdin=subprocess.DEVNULL, timeout=60)

    def test_an_answer_is_one_json_object_on_stdout_and_exit_zero(self):
        self.sb.stub("codex", answer=approve("fine"), err="progress noise")
        r = self.cli("--words", "APPROVE,REJECT", "--match", "prefix")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertEqual(r.stdout.count("\n"), 1)
        data = json.loads(r.stdout)
        self.assertEqual(data["reviewer"], "codex")
        self.assertEqual(data["output"], approve("fine"))
        self.assertEqual(data["parsed"], {"word": "APPROVE", "reason": "fine"})
        self.assertEqual(len(data["attempts"]), 1)
        self.assertEqual(data["attempts"][0]["reason"], "answered")
        self.assertEqual(data["attempts"][0]["stderr_tail"], "progress noise\n")
        self.assertEqual(set(data["attempts"][0]),
                         {"reviewer", "reason", "output", "exit_code", "stderr_tail", "model"})

    def test_no_answer_is_exit_one_and_the_json_is_still_written(self):
        r = self.cli("--words", "GO,NO-GO")
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        self.assertEqual((data["reviewer"], data["output"], data["parsed"]), ("none", "", None))
        self.assertEqual([(a["reviewer"], a["reason"]) for a in data["attempts"]],
                         [("codex", "absent")])

    def test_usage_mistakes_are_exit_two_with_nothing_on_stdout(self):
        good = ["--words", "GO,NO-GO"]
        for name, args, kw in [
            ("no prompt file", good, {"prompt_file": False}),
            ("no words", [], {}),
            ("prompt file missing", good + ["--prompt-file", "/nonexistent/prompt.txt"], {"prompt_file": False}),
            ("fallback name without model", good + ["--fallback-name", "haiku"], {}),
            ("fallback model without name", good + ["--fallback-model", HAIKU_ID], {}),
            ("no-fallback with a fallback", good + ["--no-fallback", "--fallback-name", "h",
                                                    "--fallback-model", "m"], {}),
            ("bad match rule", good + ["--match", "fuzzy"], {}),
            ("timeout not a number", good + ["--codex-timeout", "soon"], {}),
            ("empty tool list", good + ["--fallback-name", "h", "--fallback-model", "m",
                                        "--fallback-tools", ""], {}),
            ("empty words", ["--words", ""], {}),
            ("when names an impossible reason", good + ["--fallback-name", "h", "--fallback-model", "m",
                                                        "--fallback-when", "answered"], {}),
        ]:
            with self.subTest(name):
                r = self.cli(*args, **kw)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
        self.assertNotCalled("codex", "claude")

    def test_the_prompt_file_is_passed_to_the_reviewer_byte_for_byte(self):
        self.sb.stub("codex", answer=approve())
        prompt = "line one & two && 2>&1\n{{CMD}} \\ $HOME `x`\n"
        self.cli("--words", "APPROVE,REJECT", prompt=prompt)
        self.assertEqual(self.sb.calls_of("codex")[0].argv[-1], prompt)

    def test_effort_and_the_codex_timeout_are_carried(self):
        self.sb.stub("codex", hang=True)
        started = time.monotonic()
        r = self.cli("--words", "GO,NO-GO", "--effort", "high", "--codex-timeout", "1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.sb.calls_of("codex")[0].argv[5], 'model_reasoning_effort="high"')
        self.assertEqual(json.loads(r.stdout)["attempts"][0]["reason"], "timeout")

    def test_the_fallback_flags_become_a_fallback_spec(self):
        self.sb.stub("codex", answer=RAMBLE)
        self.sb.stub("claude", answer=approve("by the fallback"))
        r = self.cli("--words", "APPROVE,REJECT", "--match", "prefix",
                     "--fallback-name", "sonnet", "--fallback-model", "claude-sonnet-5-5",
                     "--fallback-timeout", "30", "--fallback-tools", "Read,Grep")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["reviewer"], "sonnet")
        self.assertEqual(data["attempts"][1]["model"], "claude-sonnet-5-5")
        self.assertEqual(self.sb.calls_of("claude")[0].argv,
                         ["--allowedTools", "Read,Grep", "-p", "--model", "claude-sonnet-5-5", "the prompt"])

    def test_fallback_when_keeps_the_fallback_out_after_a_noverdict(self):
        self.sb.stub("codex", answer=RAMBLE)
        self.sb.stub("claude", answer=approve())
        r = self.cli("--words", "GO,NO-GO", "--fallback-name", "haiku", "--fallback-model", HAIKU_ID,
                     "--fallback-when", "absent,timeout,error")
        self.assertEqual(r.returncode, 1)
        self.assertNotCalled("claude")

    def test_no_fallback_is_codex_only_and_the_match_rule_defaults_to_whole_tokens(self):
        self.sb.stub("codex", answer="VERDICT: GOOD")
        self.sb.stub("claude", answer=approve())
        r = self.cli("--words", "GO,NO-GO", "--no-fallback")
        self.assertEqual(r.returncode, 1)
        self.assertNotCalled("claude")

    def test_strict_reaches_the_chain(self):
        self.sb.stub("codex", answer="VERDICT: GO\nVERDICT: NO-GO")
        r = self.cli("--words", "GO,NO-GO", "--strict")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["attempts"][0]["reason"], "noverdict")


if __name__ == "__main__":
    unittest.main()
