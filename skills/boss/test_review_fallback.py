#!/usr/bin/env python3
"""Tests for the confinement of the PR gate's fallback reviewer, hermetically.

Run: python3 skills/boss/test_review_fallback.py

When Codex is not there the gate falls back to `claude` in read-only mode. This file proves the
confinement and nothing else: the exact `claude` call (the argv its stub receives), the spec
(`boss_review.fallback_spec`), the check (`boss_review.py --check-fallback`, a decision over
recorded stream-JSON fixtures) and the bound on what a hung Codex costs. Every test goes through
hermetic.Sandbox: `codex`, `claude` and `gh` are stubs that log their argv, stdin and working
directory, HOME and CLAUDE_CONFIG_DIR are temporary, TypeSafe has no key to find, and a test fails
if one of the three names resolves outside the stub directory. The real `claude` is never called.
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
import boss_review as br  # noqa: E402
import policy  # noqa: E402
import reviewer_chain as rc  # noqa: E402
from hermetic import Sandbox  # noqa: E402

# What the fallback must be, written out here and not read back from the code under test.
MODEL = "claude-opus-5-5"
CALL = ["--tools", "Read,Grep,Glob", "--strict-mcp-config", "--disable-slash-commands",
        "--permission-mode", "dontAsk"]
GO = "VERDICT: GO\n"
MISSING = object()


# ---------------------------------------------------------------- stream-JSON fixtures ----
# The shape of what `claude -p --output-format stream-json --verbose` printed on 2026-10-04
# (claude 2.1.289): hook events, the init event, the turn, the result. Only the init event's
# `tools`, `mcp_servers` and `model` matter to the check; the rest is there so that the parser
# is shown a realistic stream.
def init_event(**fields):
    event = {"type": "system", "subtype": "init", "cwd": "/work", "session_id": "s-1",
             "tools": ["Glob", "Grep", "Read"], "mcp_servers": [], "model": MODEL,
             "permissionMode": "dontAsk", "slash_commands": [], "skills": [], "plugins": [],
             "agents": ["Explore"]}
    event.update(fields)
    return {k: v for k, v in event.items() if v is not MISSING}


HOOK = {"type": "system", "subtype": "hook_started", "hook_event": "SessionStart"}
TURN = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "ok"}


def stream(*events):
    return "".join(json.dumps(e) + "\n" for e in events)


PASS = [HOOK, init_event(), TURN, RESULT]

# Each of these must fail the check: name -> the events.
FAILS = {
    "an extra tool": [HOOK, init_event(tools=["Glob", "Grep", "Read", "Bash"]), TURN, RESULT],
    "an MCP server": [HOOK, init_event(mcp_servers=[{"name": "mail", "status": "connected"}]), TURN, RESULT],
    "a wrong model": [HOOK, init_event(model="claude-sonnet-5-5"), TURN, RESULT],
    "a model with a suffix": [HOOK, init_event(model=MODEL + "[1m]"), TURN, RESULT],
    "a missing tool": [HOOK, init_event(tools=["Glob", "Read"]), TURN, RESULT],
    "a duplicated tool": [HOOK, init_event(tools=["Glob", "Grep", "Read", "Read"]), TURN, RESULT],
    "no mcp_servers key": [HOOK, init_event(mcp_servers=MISSING), TURN, RESULT],
    "no tools key": [HOOK, init_event(tools=MISSING), TURN, RESULT],
    "tools that are not a list": [HOOK, init_event(tools="Glob,Grep,Read"), TURN, RESULT],
    "tools that are not strings": [HOOK, init_event(tools=[1, 2, 3]), TURN, RESULT],
    "mcp_servers that is not a list": [HOOK, init_event(mcp_servers=None), TURN, RESULT],
    "a model that is not a string": [HOOK, init_event(model=None), TURN, RESULT],
    "no init event": [HOOK, TURN, RESULT],
    "two init events": [HOOK, init_event(), init_event(), TURN, RESULT],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        env = dict(self.sb.env, BOSS_TYPESAFE_ENV=str(self.sb.root / "no-typesafe.env"))
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(tempfile, "tempdir", str(self.sb.tmp))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sb.stub("gh")                  # nothing here talks to GitHub: its log must stay empty
        self.checkout = self.sb.work / "checkout"
        self.checkout.mkdir()

    def tearDown(self):
        self.sb.guard()                     # codex, claude and gh still resolve to the stubs, and only those
        self.assertEqual(self.sb.calls_of("gh"), [], "gh was called")

    def claude_calls(self):
        return self.sb.calls_of("claude")


# ------------------------------------------------------------------------ the spec ----
class Spec(Base):
    def test_the_constants_are_the_ones_the_owner_decided(self):
        self.assertEqual(policy.REVIEW_FALLBACK_MODEL, MODEL)
        self.assertEqual(policy.REVIEW_FALLBACK_TOOLS, ("Read", "Grep", "Glob"))
        self.assertEqual(policy.REVIEW_FALLBACK_PERMISSION_MODE, "dontAsk")

    def test_the_spec_is_opus_with_the_confinement_in_extra_args(self):
        spec = br.fallback_spec()
        self.assertEqual((spec.name, spec.model, spec.timeout), ("opus", MODEL, 600))
        self.assertEqual(spec.when, ("absent", "timeout", "error"))      # not noverdict: Codex answered
        self.assertIsNone(spec.allowed_tools)
        self.assertEqual(spec.extra_args, tuple(CALL))

    def test_the_timeout_is_a_parameter_so_a_test_can_pass_one_second(self):
        self.assertEqual(br.fallback_spec(timeout=1).timeout, 1)
        self.assertEqual(br.fallback_spec().timeout, policy.REVIEW_FALLBACK_TIMEOUT)


# ------------------------------------------------------------------ the call itself ----
class TheCall(Base):
    def run_fallback(self):
        self.sb.stub("claude", answer=GO)       # no codex stub: Codex is absent, the fallback runs
        return rc.run_chain("PROMPT TEXT", words=rc.GO_NOGO, strict=True, fallback=br.fallback_spec())

    def test_claude_receives_exactly_the_confined_call(self):
        result = self.run_fallback()
        self.assertEqual((result.reviewer, result.attempts[-1].model), ("opus", MODEL))
        (call,) = self.claude_calls()
        self.assertEqual(call.argv, [*CALL, "-p", "--model", MODEL, "PROMPT TEXT"])
        self.assertEqual(call.stdin, "")

    def test_each_flag_and_value_is_there_and_nothing_that_would_widen_it(self):
        self.run_fallback()
        (call,) = self.claude_calls()
        argv = call.argv
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(argv[argv.index("--model") + 1], policy.REVIEW_FALLBACK_MODEL)
        self.assertEqual(argv.count("--permission-mode"), 1)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        for flag in ("--strict-mcp-config", "--disable-slash-commands", "-p"):
            self.assertEqual(argv.count(flag), 1, flag)
        for flag in ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
                     "--allowedTools", "--allowed-tools", "--bare", "--mcp-config", "--add-dir",
                     "--settings", "--agents", "--plugin-dir", "--"):
            self.assertNotIn(flag, argv)
        self.assertEqual(argv[-1], "PROMPT TEXT")      # the prompt is the one operand, and the last

    def test_the_prompt_is_the_last_argument_and_follows_a_flag_that_takes_one_value(self):
        # `--tools <tools...>` would read a prompt put right after it as one more tool: here `-p`
        # and `--model <model>` stand between the variadic option and the prompt
        self.run_fallback()
        argv = self.claude_calls()[0].argv
        self.assertLess(argv.index("--tools"), argv.index("-p"))
        self.assertEqual(argv[-3:-1], ["--model", MODEL])

    def test_the_command_line_of_the_chain_carries_the_whole_spec(self):
        # 08 starts the chain as a child process: what reaches `claude` through it must be what the
        # library call sends, the confinement flags included
        prompt = self.sb.work / "prompt.txt"
        prompt.write_text("PROMPT TEXT", encoding="utf-8")
        self.sb.stub("claude", answer=GO)
        r = subprocess.run([sys.executable, str(HERE / "reviewer_chain.py"), "--prompt-file", str(prompt),
                            "--words", "GO,NO-GO", "--match", "token", "--strict",
                            *rc.fallback_flags(br.fallback_spec())],
                           capture_output=True, text=True, env=dict(os.environ), cwd=str(self.sb.work),
                           stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["reviewer"], "opus")
        self.assertEqual(self.claude_calls()[0].argv, [*CALL, "-p", "--model", MODEL, "PROMPT TEXT"])


# --------------------------------------------------------------------- the decision ----
class Decision(unittest.TestCase):
    """`init_problems`: the reasons the events fail the check; none is a pass."""

    def test_the_init_event_of_the_confined_call_passes(self):
        self.assertEqual(br.init_problems(PASS), [])

    def test_the_order_of_the_tools_does_not_matter(self):
        self.assertEqual(br.init_problems([init_event(tools=["Read", "Glob", "Grep"])]), [])

    def test_each_departure_fails(self):
        for name, events in FAILS.items():
            with self.subTest(name):
                self.assertTrue(br.init_problems(events), name)

    def test_a_failure_says_what_was_wrong(self):
        wanted = {"an extra tool": "tools", "an MCP server": "mcp_servers", "a wrong model": "model",
                  "no init event": "init", "two init events": "init"}
        for name, word in wanted.items():
            with self.subTest(name):
                self.assertIn(word, " ".join(br.init_problems(FAILS[name])))

    def test_something_that_is_not_an_init_event_is_not_one(self):
        events = [{"type": "system", "subtype": "hook_started"}, {"type": "init"}, {"subtype": "init"}]
        self.assertEqual(len(br.init_problems(events)), 1)


# --------------------------------------------------------------------- the command ----
class Check(Base):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "boss_review.py"), *args],
                              capture_output=True, text=True, env=dict(os.environ), cwd=str(self.sb.work),
                              stdin=subprocess.DEVNULL, timeout=120)

    def check(self, events=PASS, **stub):
        self.sb.stub("claude", answer=events if isinstance(events, str) else stream(*events), **stub)
        return self.cli("--check-fallback", "--checkout", str(self.checkout))

    def test_a_confined_claude_passes_with_one_line_on_stdout(self):
        r = self.check()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout.count("\n"), 1)
        self.assertIn(MODEL, r.stdout)

    def test_each_departure_is_exit_one_with_nothing_on_stdout_and_the_reason_on_stderr(self):
        for name, events in FAILS.items():
            with self.subTest(name):
                r = self.check(events)
                self.assertEqual((r.returncode, r.stdout), (1, ""), r.stderr)
                self.assertIn("boss_review:", r.stderr)

    def test_a_line_that_is_not_a_json_object_fails_even_beside_a_good_init(self):
        for junk in ("this is not json\n", "[1, 2]\n", "{\"type\": \n"):
            with self.subTest(junk=junk):
                r = self.check(stream(*PASS) + junk)
                self.assertEqual((r.returncode, r.stdout), (1, ""), r.stderr)

    def test_a_blank_line_is_not_a_fault(self):
        self.assertEqual(self.check("\n" + stream(*PASS) + "\n\n").returncode, 0)

    def test_a_claude_that_exits_non_zero_after_a_good_init_is_not_a_pass(self):
        r = self.check(rc=3)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("exited 3", r.stderr)

    def test_a_claude_that_is_not_there_is_exit_one(self):
        r = self.cli("--check-fallback", "--checkout", str(self.checkout))      # no claude stub
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("could not be started", r.stderr)

    def test_a_claude_that_hangs_is_stopped_and_fails(self):
        self.sb.stub("claude", hang=True)
        started = time.monotonic()
        problems = br.check_fallback(str(self.checkout), timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(any("ran past 1" in p for p in problems), problems)

    def test_the_diagnostic_call_is_the_real_call_plus_stream_json_and_verbose(self):
        self.check()
        (call,) = self.claude_calls()
        self.assertEqual(call.argv, [*CALL, "--output-format", "stream-json", "--verbose",
                                     "-p", "--model", MODEL, br.CHECK_PROMPT])
        # taking those three tokens out leaves the argv a review sends, prompt aside
        i = call.argv.index("--output-format")
        self.assertEqual(call.argv[:i] + call.argv[i + 3:],
                         rc.claude_argv(br.fallback_spec(), br.CHECK_PROMPT)[1:])
        self.assertEqual(len(br.CHECK_PROMPT.split()), 1)      # a one-word prompt

    def test_the_call_runs_in_the_checkout_it_was_given(self):
        self.check()
        (call,) = self.claude_calls()
        self.assertEqual(call.cwd, str(self.checkout.resolve()))
        self.assertNotEqual(call.cwd, str(self.sb.work.resolve()))      # not the directory the command ran in

    def test_the_command_never_calls_codex_or_gh(self):
        self.sb.stub("codex", answer=GO)
        self.check()
        self.assertEqual(self.sb.calls_of("codex"), [])

    def test_usage_mistakes_are_exit_two_and_nothing_is_run(self):
        here = str(self.checkout)
        for name, args in [
            ("no checkout", ["--check-fallback"]),
            ("a checkout that is not a directory", ["--check-fallback", "--checkout", here + "/nope"]),
            ("a repo", ["--check-fallback", "--checkout", here, "--repo", "Owner/Repo"]),
            ("a pr", ["--check-fallback", "--checkout", here, "--pr", "5"]),
            ("an author", ["--check-fallback", "--checkout", here, "--author", "worker-a"]),
            ("all three", ["--check-fallback", "--checkout", here, "--repo", "O/R", "--pr", "5",
                           "--author", "a"]),
        ]:
            with self.subTest(name):
                self.sb.stub("claude", answer=stream(*PASS))
                r = self.cli(*args)
                self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        self.assertEqual(self.claude_calls(), [])

    def test_the_review_still_needs_its_four_arguments(self):
        for missing in ("--repo", "--pr", "--checkout", "--author"):
            full = {"--repo": "Owner/Repo", "--pr": "5", "--checkout": str(self.checkout), "--author": "worker-a"}
            del full[missing]
            with self.subTest(missing=missing):
                r = self.cli(*[x for pair in full.items() for x in pair])
                self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
                self.assertIn(missing, r.stderr)
        self.assertEqual(self.claude_calls(), [])


# ---------------------------------------------------------------------- the timeout ----
class ElapsedBound(Base):
    def test_a_hung_codex_costs_one_timeout_and_then_the_fallback_answers(self):
        # Codex hangs and ignores SIGTERM, so it is stopped by the KILL that follows TERM_GRACE
        self.sb.stub("codex", hang=True, ignore_term=True)
        self.sb.stub("claude", answer=GO)
        started = time.monotonic()
        result = rc.run_chain("PROMPT TEXT", words=rc.GO_NOGO, strict=True, codex_timeout=1,
                              fallback=br.fallback_spec(timeout=1))
        elapsed = time.monotonic() - started
        self.assertEqual([(a.reviewer, a.reason) for a in result.attempts],
                         [("codex", "timeout"), ("opus", "answered")])
        self.assertEqual(result.reviewer, "opus")
        # the bound: both timeouts, the grace before the KILL, and 5 s for the interpreter, the stubs
        # and the scheduler. Not a measure of speed: it says the wait is bounded by what is stated.
        self.assertGreaterEqual(elapsed, 1)
        self.assertLess(elapsed, 1 + 1 + rc.TERM_GRACE + 5)
        self.assertEqual(len(self.claude_calls()), 1)

    def test_an_absent_codex_costs_nothing(self):
        self.sb.stub("claude", answer=GO)
        started = time.monotonic()
        result = rc.run_chain("PROMPT TEXT", words=rc.GO_NOGO, strict=True, codex_timeout=1,
                              fallback=br.fallback_spec(timeout=1))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual([a.reason for a in result.attempts], ["absent", "answered"])

    def test_the_two_timeouts_are_separate_constants_of_600_seconds(self):
        self.assertEqual((policy.REVIEW_CODEX_TIMEOUT, policy.REVIEW_FALLBACK_TIMEOUT), (600, 600))


if __name__ == "__main__":
    unittest.main()
