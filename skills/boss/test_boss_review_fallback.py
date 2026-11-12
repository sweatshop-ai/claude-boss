#!/usr/bin/env python3
"""Tests for the confinement of the PR gate's fallback reviewer, hermetically.

Run: python3 skills/boss/test_boss_review_fallback.py

When Codex is not there the gate falls back to `claude` in read-only mode. This file covers the
confinement of that fallback and what a hung Codex costs before it runs: the exact `claude` call
(the argv its stub receives), the spec (`boss_review.fallback_spec`), the check
(`boss_review.py --check-fallback`, a decision over recorded stream-JSON fixtures) and the bound
on the wait. Every test goes through
hermetic.Sandbox: `codex`, `claude` and `gh` are stubs that log their argv, stdin and working
directory, HOME and CLAUDE_CONFIG_DIR are temporary, TypeSafe has no key to find, and a test fails
if one of the three names resolves outside the stub directory. The real `claude` is never called.
"""
import dataclasses
import json
import os
import shlex
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
CALL = ["--tools", "Read,Grep,Glob", "--strict-mcp-config", "--disable-slash-commands", "--restricted", "--safe-mode",
        "--permission-mode", "dontAsk"]
GO = "VERDICT: GO\n"
MISSING = object()


# ---------------------------------------------------------------- stream-JSON fixtures ----
# The shape of what `claude -p --output-format stream-json --verbose` printed on 2026-10-04
# (claude 2.1.289) under --restricted: the init event, the turn, the result. Without --restricted the
# stream opens with `hook_started` / `hook_response` events for every SessionStart hook of the owner's
# and of the checkout's settings files, and the init event lists the installed plugins. The check
# reads the init event's `tools`, `mcp_servers`, `model`, `permissionMode`, `slash_commands` and
# `plugins`, and refuses any hook event; the rest is there so that the parser sees a realistic stream.
BUILTIN_PLUGINS = [{"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"},
                   {"name": "cc-plugin-telemetry", "path": "builtin", "source": "cc-plugin-telemetry@builtin"}]


def init_event(**fields):
    event = {"type": "system", "subtype": "init", "cwd": "/work", "session_id": "s-1",
             "tools": ["Glob", "Grep", "Read"], "mcp_servers": [], "model": MODEL,
             "permissionMode": "dontAsk", "slash_commands": [], "skills": [], "plugins": BUILTIN_PLUGINS,
             "agents": ["Explore"]}
    event.update(fields)
    return {k: v for k, v in event.items() if v is not MISSING}


HOOK = {"type": "system", "subtype": "hook_started", "hook_event": "SessionStart"}
HOOK_DONE = {"type": "system", "subtype": "hook_response", "hook_event": "SessionStart", "exit_code": 0}
OUTSIDE_PLUGIN = {"name": "some-plugin", "path": "/plugins/cache/some-plugin/1.0", "source": "some-plugin@market"}
TURN = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "ok"}


def stream(*events):
    return "".join(json.dumps(e) + "\n" for e in events)


PASS = [init_event(), TURN, RESULT]

# Each of these must fail the check: name -> the events.
FAILS = {
    "an extra tool": [init_event(tools=["Glob", "Grep", "Read", "Bash"]), TURN, RESULT],
    "an MCP server": [init_event(mcp_servers=[{"name": "mail", "status": "connected"}]), TURN, RESULT],
    "a wrong model": [init_event(model="claude-sonnet-5-5"), TURN, RESULT],
    "a model with a suffix": [init_event(model=MODEL + "[1m]"), TURN, RESULT],
    "a missing tool": [init_event(tools=["Glob", "Read"]), TURN, RESULT],
    "a duplicated tool": [init_event(tools=["Glob", "Grep", "Read", "Read"]), TURN, RESULT],
    "no mcp_servers key": [init_event(mcp_servers=MISSING), TURN, RESULT],
    "no tools key": [init_event(tools=MISSING), TURN, RESULT],
    "tools that are not a list": [init_event(tools="Glob,Grep,Read"), TURN, RESULT],
    "tools that are not strings": [init_event(tools=[1, 2, 3]), TURN, RESULT],
    "mcp_servers that is not a list": [init_event(mcp_servers=None), TURN, RESULT],
    "a model that is not a string": [init_event(model=None), TURN, RESULT],
    "no init event": [TURN, RESULT],
    "two init events": [init_event(), init_event(), TURN, RESULT],
    # the settings were loaded: the fallback ran hooks, or has plugins, that nobody chose for it
    "a hook that started": [HOOK, init_event(), TURN, RESULT],
    "a hook that answered": [init_event(), HOOK_DONE, TURN, RESULT],
    "a hook after the init event": [init_event(), HOOK, HOOK_DONE, TURN, RESULT],
    "a plugin from outside the CLI": [init_event(plugins=BUILTIN_PLUGINS + [OUTSIDE_PLUGIN]), TURN, RESULT],
    "a plugin that only borrows a built-in's name":
        [init_event(plugins=[dict(BUILTIN_PLUGINS[0], path="/plugins/cc-plugin-agents-md")]), TURN, RESULT],
    "no plugins key": [init_event(plugins=MISSING), TURN, RESULT],
    "plugins that is not a list": [init_event(plugins=None), TURN, RESULT],
    "a plugin that is not an object": [init_event(plugins=["cc-plugin-telemetry"]), TURN, RESULT],
    # the permission mode and the slash commands
    "a permission mode that asks": [init_event(permissionMode="default"), TURN, RESULT],
    "a permission mode that skips": [init_event(permissionMode="bypassPermissions"), TURN, RESULT],
    "a permission mode with other case": [init_event(permissionMode="dontask"), TURN, RESULT],
    "no permissionMode key": [init_event(permissionMode=MISSING), TURN, RESULT],
    "a permission mode that is not a string": [init_event(permissionMode=["dontAsk"]), TURN, RESULT],
    "a slash command": [init_event(slash_commands=["review"]), TURN, RESULT],
    "no slash_commands key": [init_event(slash_commands=MISSING), TURN, RESULT],
    "slash_commands that is not a list": [init_event(slash_commands="none"), TURN, RESULT],
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
        self.expect = {"claude": 0, "codex": 0}      # the calls each of these stubs must have logged by the end
        self.checkout = self.sb.work / "checkout"
        self.checkout.mkdir()

    def tearDown(self):
        self.sb.guard()                     # codex, claude and gh still resolve to the stubs, and only those
        for name, count in self.expect.items():
            self.assertEqual(len(self.sb.calls_of(name)), count, "calls the %s stub logged" % name)
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


    def test_context_md_quotes_the_call_it_describes(self):
        text = (HERE.parent.parent / "CONTEXT.md").read_text(encoding="utf-8")
        paragraph = text.split("**Read-only fallback**", 1)[1].split("\n\n", 1)[0]
        flat = " ".join(paragraph.split())
        for quoted in ("--tools " + ",".join(policy.REVIEW_FALLBACK_TOOLS), "--strict-mcp-config",
                       "--disable-slash-commands", "--restricted", "--safe-mode",
                       "--permission-mode " + policy.REVIEW_FALLBACK_PERMISSION_MODE):
            self.assertIn(quoted, flat)


# ------------------------------------------------------------------ the call itself ----
class TheCall(Base):
    def run_fallback(self):
        self.sb.stub("claude", answer=GO)       # no codex stub: Codex is absent, the fallback runs
        self.expect["claude"] = 1
        return rc.run_chain("PROMPT TEXT", words=rc.GO_NOGO, strict=True, fallback=br.fallback_spec())

    def test_claude_receives_exactly_the_confined_call(self):
        result = self.run_fallback()
        self.assertEqual((result.reviewer, result.attempts[-1].model), ("opus", MODEL))
        (call,) = self.claude_calls()
        self.assertEqual(call.argv, [*CALL, "-p", "--model", MODEL, "PROMPT TEXT"])
        self.assertEqual(call.stdin, "")
        # and the one builder agrees with what the stub received
        self.assertEqual(rc.claude_argv(br.fallback_spec(), "PROMPT TEXT"), ["claude", *call.argv])

    def test_each_flag_and_value_is_there_and_nothing_that_would_widen_it(self):
        self.run_fallback()
        (call,) = self.claude_calls()
        argv = call.argv
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(argv[argv.index("--model") + 1], policy.REVIEW_FALLBACK_MODEL)
        self.assertEqual(argv.count("--permission-mode"), 1)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        for flag in ("--strict-mcp-config", "--disable-slash-commands", "--restricted", "--safe-mode", "-p"):
            self.assertEqual(argv.count(flag), 1, flag)
        for flag in ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
                     "--allowedTools", "--allowed-tools", "--bare", "--mcp-config", "--add-dir",
                     "--settings", "--setting-sources", "--agents", "--plugin-dir", "--"):
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
        self.expect["claude"] = 1
        r = subprocess.run([sys.executable, str(HERE / "reviewer_chain.py"), "--prompt-file", str(prompt),
                            "--words", "GO,NO-GO", "--match", "token", "--strict",
                            *rc.fallback_flags(br.fallback_spec())],
                           capture_output=True, text=True, env=dict(os.environ), cwd=str(self.sb.work),
                           stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["reviewer"], "opus")
        self.assertEqual(self.claude_calls()[0].argv, [*CALL, "-p", "--model", MODEL, "PROMPT TEXT"])
        self.assertEqual(self.claude_calls()[0].argv, rc.claude_argv(br.fallback_spec(), "PROMPT TEXT")[1:])


# --------------------------------------------------------------------- the decision ----
class Decision(Base):
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
                  "no init event": "init", "two init events": "init", "a hook that started": "hook",
                  "a hook that answered": "hook", "a plugin from outside the CLI": "plugins",
                  "a permission mode that asks": "permissionMode", "a slash command": "slash_commands"}
        for name, word in wanted.items():
            with self.subTest(name):
                self.assertIn(word, " ".join(br.init_problems(FAILS[name])))

    def test_something_that_is_not_an_init_event_is_not_one(self):
        events = [{"type": "system", "subtype": "status"}, {"type": "init"}, {"subtype": "init"}]
        self.assertEqual(len(br.init_problems(events)), 1)

    def test_the_built_in_plugins_are_not_a_fault_and_neither_are_none(self):
        self.assertEqual(br.init_problems([init_event(plugins=[])]), [])
        self.assertEqual(br.init_problems([init_event(plugins=BUILTIN_PLUGINS)]), [])

    def test_every_hook_event_counts_and_is_counted(self):
        problems = br.init_problems([HOOK, HOOK_DONE, init_event(), HOOK])
        self.assertEqual(len(problems), 1)
        self.assertIn("3 hook events", problems[0])

    def test_an_event_that_only_looks_like_a_hook_is_not_one(self):
        for event in ({"type": "assistant", "subtype": "hook_started"}, {"type": "system", "subtype": "hooks"},
                      {"type": "system", "subtype": "status", "hook_event": "SessionStart"}):
            with self.subTest(event=event):
                self.assertEqual(br.init_problems([init_event(), event]), [])


# --------------------------------------------------------------------- the command ----
class Check(Base):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "boss_review.py"), *args],
                              capture_output=True, text=True, env=dict(os.environ), cwd=str(self.sb.work),
                              stdin=subprocess.DEVNULL, timeout=120)

    def check(self, events=PASS, **stub):
        self.sb.stub("claude", answer=events if isinstance(events, str) else stream(*events), **stub)
        self.expect["claude"] += 1
        return self.cli("--check-fallback", "--checkout", str(self.checkout))

    def test_a_confined_claude_passes_with_one_line_on_stdout(self):
        r = self.check()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout.count("\n"), 1)
        for said in (MODEL, "dontAsk", "no hooks"):
            self.assertIn(said, r.stdout)

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
        self.expect["claude"] = 1
        started = time.monotonic()
        problems = br.check_fallback(str(self.checkout), timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(any("ran past 1" in p for p in problems), problems)

    def test_the_diagnostic_call_is_the_real_call_plus_stream_json_and_verbose(self):
        self.check()
        (call,) = self.claude_calls()
        self.assertEqual(call.argv, [*CALL, "--output-format", "stream-json", "--verbose",
                                     "--include-hook-events", "-p", "--model", MODEL, br.CHECK_PROMPT])
        # taking those four tokens out leaves the argv a review sends, prompt aside
        i = call.argv.index("--output-format")
        self.assertEqual(call.argv[:i] + call.argv[i + 4:],
                         rc.claude_argv(br.fallback_spec(), br.CHECK_PROMPT)[1:])
        self.assertEqual(len(br.CHECK_PROMPT.split()), 1)      # a one-word prompt

    def settings_reading_claude(self):
        """A `claude` stub that behaves as 2.1.289 does about settings: it reads ./.claude/settings.json
        unless `--restricted` is among its arguments, and a SessionStart hook there starts (a hook_started
        event, and a marker file as proof that the command ran). The init event is the confined one."""
        init = json.dumps(init_event())
        hook = json.dumps(HOOK)
        self.sb.stub_script("claude", """
if [ -f .claude/settings.json ] && ! printf '%%s\\n' "$@" | grep -qx -- --restricted; then
    echo ran > "$R/hook-ran"
    echo %s
fi
echo %s
""" % (shlex.quote(hook), shlex.quote(init)))
        self.expect["claude"] += 1

    def hostile_checkout(self):
        (self.checkout / ".claude").mkdir()
        (self.checkout / ".claude" / "settings.json").write_text(json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "touch pwned"}]}]}}))

    def test_a_checkout_whose_settings_carry_a_hook_is_not_loaded_by_the_real_call(self):
        # the PR's own .claude/settings.json: `claude -p` skips the trust dialog, so only --restricted keeps it out
        self.hostile_checkout()
        self.settings_reading_claude()
        r = self.cli("--check-fallback", "--checkout", str(self.checkout))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertFalse((self.sb.root / "hook-ran").exists(), "the checkout's hook ran")

    def test_the_same_checkout_fails_the_check_when_the_restriction_is_taken_out(self):
        # the control: without --restricted the stub loads the settings and the check names the hook
        self.hostile_checkout()
        self.settings_reading_claude()
        spec = br.fallback_spec()
        loose = dataclasses.replace(spec, extra_args=tuple(a for a in spec.extra_args if a != "--restricted"))
        with mock.patch.object(br, "fallback_spec", return_value=loose):
            problems = br.check_fallback(str(self.checkout))
        self.assertTrue((self.sb.root / "hook-ran").exists())
        self.assertTrue(any("hook event" in p for p in problems), problems)

    def plugin_env_claude(self):
        """A `claude` stub that loads an inline plugin from CLAUDE_CODE_PLUGIN_DIRS, settings files or
        not, as 2.1.311 does (found by the real check: the owner's session names a mod there)."""
        confined, loaded = json.dumps(init_event()), json.dumps(init_event(plugins=BUILTIN_PLUGINS + [OUTSIDE_PLUGIN]))
        self.sb.stub_script("claude", """
if [ -n "$CLAUDE_CODE_PLUGIN_DIRS" ]; then echo %s; else echo %s; fi
""" % (shlex.quote(loaded), shlex.quote(confined)))
        self.expect["claude"] += 1

    def test_a_plugin_directory_in_our_environment_does_not_reach_the_checked_call(self):
        self.plugin_env_claude()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_PLUGIN_DIRS": "/home/owner/.claude/mods/x"}):
            self.assertEqual(br.check_fallback(str(self.checkout)), [])

    def test_the_spec_unsets_the_plugin_variables_and_the_check_fails_when_it_does_not(self):
        self.assertIn("CLAUDE_CODE_PLUGIN_DIRS", br.fallback_spec().env_unset)
        self.plugin_env_claude()
        loose = dataclasses.replace(br.fallback_spec(), env_unset=())
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_PLUGIN_DIRS": "/x"}), \
                mock.patch.object(br, "fallback_spec", return_value=loose):
            problems = br.check_fallback(str(self.checkout))
        self.assertTrue(any("plugins" in p for p in problems), problems)

    def test_every_variable_the_spec_unsets_is_gone_from_the_claude_child(self):
        # one stub call, every name in the policy list set in our environment: none reaches `claude`
        self.sb.stub_script("claude", 'env > "$R/claude.env"; echo "VERDICT: GO"')
        self.expect["claude"] += 1
        names = policy.REVIEW_FALLBACK_ENV_UNSET
        for must in ("CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CODE_PLUGIN_SEED_DIR", "CLAUDE_CODE_MANAGED_SETTINGS_PATH",
                     "CLAUDE_CODE_REMOTE_SETTINGS_PATH", "CLAUDE_ENV_FILE", "BASH_ENV", "LD_PRELOAD"):
            self.assertIn(must, names)
        env = dict(os.environ, KEPT_BY_THE_TEST="yes", **{n: "/in/the/checkout" for n in names})
        with mock.patch.dict(os.environ, env, clear=True):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec(), cwd=str(self.checkout))
        self.assertEqual(result.reviewer, "opus")
        seen = dict(line.split("=", 1) for line in (self.sb.root / "claude.env").read_text().splitlines() if "=" in line)
        self.assertEqual([n for n in names if n in seen], [])
        self.assertEqual(seen.get("KEPT_BY_THE_TEST"), "yes")

    def planted_claude(self, where):
        """An executable `claude` in `where`, inside the checkout, that leaves a mark when it runs."""
        where.mkdir(parents=True, exist_ok=True)
        planted = where / "claude"
        planted.write_text("#!/bin/sh\ntouch %s\n" % (self.sb.root / "planted-ran"))
        planted.chmod(0o755)

    def test_a_claude_planted_in_the_checkout_is_not_the_one_started(self):
        # the PR's own `claude`, reachable by PATH=.:... or a checkout-local bin dir, ahead of the real one
        self.planted_claude(self.checkout)
        self.planted_claude(self.checkout / ".venv" / "bin")
        self.sb.stub("claude", answer=GO)
        self.expect["claude"] = 2
        stubs = os.environ["PATH"]
        path = os.pathsep.join([".", "", "relative/bin", str(self.checkout), str(self.checkout / ".venv" / "bin"), stubs])
        with mock.patch.dict(os.environ, {"PATH": path}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec(), cwd=str(self.checkout))
            problems = br.check_fallback(str(self.checkout))
        self.assertEqual(result.reviewer, "opus")
        self.assertEqual(len(self.claude_calls()), 2)      # the review's call and the check's, both the stub
        self.assertFalse((self.sb.root / "planted-ran").exists(), "the checkout's claude ran")
        self.assertTrue(problems)       # the stub answers GO, not an init event: the check is not what is under test

    def test_when_the_only_claude_is_in_the_checkout_the_fallback_is_absent(self):
        self.planted_claude(self.checkout)
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(self.checkout), os.environ["PATH"]])}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec(), cwd=str(self.checkout))
            problems = br.check_fallback(str(self.checkout))
        self.assertEqual([a.reason for a in result.attempts if a.reviewer == "opus"], ["absent"])
        self.assertTrue(any("could not be started" in p for p in problems), problems)
        self.assertFalse((self.sb.root / "planted-ran").exists())

    def safe_bin_with_link(self, target, *, relative=False, via=None, name="safe-bin"):
        """A directory outside the checkout, on its own, holding a `claude` that is a symlink to `target`."""
        safe = self.sb.root / name
        safe.mkdir(exist_ok=True)
        link = safe / "claude"
        if via is not None:      # a chain: claude -> via -> target
            via.symlink_to(target)
            target = via
        link.symlink_to(os.path.relpath(target, safe) if relative else target)
        return safe

    def run_with_path(self, safe, cwd):
        path = os.pathsep.join([str(safe), os.environ["PATH"]])      # the stubs come after: a fall-through shows
        with mock.patch.dict(os.environ, {"PATH": path}):
            return rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec(), cwd=cwd)

    def assert_refused(self, result):
        self.assertEqual([a.reason for a in result.attempts if a.reviewer == "opus"], ["absent"])
        self.assertFalse((self.sb.root / "planted-ran").exists(), "the checkout's claude ran")
        # the claude stub is on the PATH behind the link and must not have been reached: self.expect says 0

    def test_a_symlink_in_a_safe_directory_that_leads_into_the_checkout_is_refused(self):
        self.planted_claude(self.checkout)
        self.sb.stub("claude", answer=GO)
        safe = self.safe_bin_with_link(self.checkout / "claude")
        self.assert_refused(self.run_with_path(safe, str(self.checkout)))

    def test_a_relative_symlink_and_a_chain_of_links_into_the_checkout_are_refused(self):
        self.planted_claude(self.checkout)
        self.sb.stub("claude", answer=GO)
        safe = self.safe_bin_with_link(self.checkout / "claude", relative=True, via=self.sb.root / "hop")
        self.assert_refused(self.run_with_path(safe, str(self.checkout)))

    def test_a_checkout_that_is_itself_a_symlink_is_compared_by_realpath(self):
        self.planted_claude(self.checkout)
        self.sb.stub("claude", answer=GO)
        alias = self.sb.root / "checkout-alias"
        alias.symlink_to(self.checkout)
        safe = self.safe_bin_with_link(self.checkout / "claude")
        self.assert_refused(self.run_with_path(safe, str(alias)))       # the link leads to the real path
        safe_alias = self.safe_bin_with_link(alias / "claude", name="safe-bin-2")       # and the other way round
        self.assert_refused(self.run_with_path(safe_alias, str(self.checkout)))

    def test_a_symlink_to_a_claude_outside_the_checkout_is_still_started(self):
        self.sb.stub("claude", answer=GO)
        self.expect["claude"] = 1
        safe = self.safe_bin_with_link(self.sb.stubs / "claude")
        result = self.run_with_path(safe, str(self.checkout))
        self.assertEqual(result.reviewer, "opus")
        self.assertFalse((self.sb.root / "planted-ran").exists())

    def chdir(self, where):
        before = os.getcwd()
        os.chdir(where)
        self.addCleanup(os.chdir, before)

    def test_without_a_cwd_the_current_directory_is_the_one_kept_out(self):
        self.planted_claude(self.checkout)
        self.sb.stub("claude", answer=GO)
        self.expect["claude"] = 1
        self.chdir(self.checkout)
        path = os.pathsep.join([str(self.checkout), os.environ["PATH"]])
        with mock.patch.dict(os.environ, {"PATH": path}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec())      # cwd=None
        self.assertEqual(result.reviewer, "opus")
        self.assertFalse((self.sb.root / "planted-ran").exists(), "the current directory's claude ran")

    def test_without_a_cwd_a_claude_only_in_the_current_directory_is_absent(self):
        self.planted_claude(self.checkout)
        self.chdir(self.checkout)
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(self.checkout), os.environ["PATH"]])}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec())
        self.assertEqual([a.reason for a in result.attempts if a.reviewer == "opus"], ["absent"])
        self.assertFalse((self.sb.root / "planted-ran").exists())

    def test_a_relative_symlink_straight_into_the_checkout_is_refused(self):
        # no hop: the link's own text (../work/checkout/claude) names a file inside the checkout
        self.planted_claude(self.checkout)
        self.sb.stub("claude", answer=GO)
        safe = self.safe_bin_with_link(self.checkout / "claude", relative=True)
        self.assertEqual(os.readlink(safe / "claude"), "../work/checkout/claude")
        self.assert_refused(self.run_with_path(safe, str(self.checkout)))

    def test_a_refused_link_is_absent_even_when_a_later_entry_holds_a_good_claude(self):
        # documented: shutil.which picks the first `claude`; the refusal is final, no later entry is tried
        self.planted_claude(self.checkout)
        self.sb.stub("claude", answer=GO)           # on the PATH behind the link: must not be reached
        safe = self.safe_bin_with_link(self.checkout / "claude")
        self.assert_refused(self.run_with_path(safe, str(self.checkout)))

    def test_with_a_deleted_current_directory_and_no_cwd_the_confined_fallback_is_absent(self):
        gone = self.sb.root / "gone"
        gone.mkdir()
        self.sb.stub("claude", answer=GO)
        self.chdir(gone)
        gone.rmdir()
        with self.assertRaises(FileNotFoundError):
            os.getcwd()                              # the premise
        self.assertIsNone(rc.claude_launch(br.fallback_spec(), "p"))
        turn = rc._claude("p", br.fallback_spec(), 5, lambda text: None, None)
        self.assertEqual((turn.attempt.reviewer, turn.attempt.reason), ("opus", "absent"))

    def test_with_a_deleted_current_directory_a_preset_without_a_cwd_is_still_started(self):
        gone = self.sb.root / "gone"
        gone.mkdir()
        self.sb.stub("claude", answer=GO)
        self.chdir(gone)
        gone.rmdir()
        launch = rc.claude_launch(rc.OPUS, "p")      # a preset with no cwd asks for no base
        self.assertIsNotNone(launch)
        self.assertEqual(launch[0][0], str(self.sb.stubs / "claude"))

    def test_a_base_of_the_filesystem_root_keeps_out_every_entry(self):
        # base + os.sep was "//": nothing started with it, so a cwd of "/" excluded nothing
        self.sb.stub("claude", answer=GO)
        self.assertIsNone(rc.claude_launch(br.fallback_spec(), "p", "/"))
        result = rc.run_chain("p", words=rc.GO_NOGO, fallback=br.fallback_spec(), cwd="/")
        self.assertEqual([a.reason for a in result.attempts if a.reviewer == "opus"], ["absent"])

    def test_a_base_that_is_a_prefix_of_a_sibling_name_keeps_out_only_itself(self):
        self.sb.stub("claude", answer=GO)
        self.expect["claude"] = 1
        sibling = self.sb.work / "checkout-other"      # shares the text "checkout" with the base
        sibling.mkdir()
        (sibling / "claude").symlink_to(self.sb.stubs / "claude")
        result = self.run_with_path(sibling, str(self.checkout))
        self.assertEqual(result.reviewer, "opus")

    def test_a_fallback_that_unsets_path_is_refused_at_construction(self):
        for names in (("PATH",), ("BASH_ENV", "PATH")):
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, "PATH"):
                rc.Fallback("opus", "claude-opus-5-5", env_unset=names)

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
        self.expect.update(codex=1, claude=1)
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
        self.expect["claude"] = 1
        started = time.monotonic()
        result = rc.run_chain("PROMPT TEXT", words=rc.GO_NOGO, strict=True, codex_timeout=1,
                              fallback=br.fallback_spec(timeout=1))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual([a.reason for a in result.attempts], ["absent", "answered"])

    def test_the_two_timeouts_are_separate_constants_of_600_seconds(self):
        self.assertEqual((policy.REVIEW_CODEX_TIMEOUT, policy.REVIEW_FALLBACK_TIMEOUT), (600, 600))


# ------------------------------------------------------ the presets resolve claude too ----
class PresetLaunch(Base):
    """OPUS and FABLE unset nothing, and they take the same resolution as the confined fallback."""

    def planted(self, where):
        where.mkdir(parents=True, exist_ok=True)
        planted = where / "claude"
        planted.write_text("#!/bin/sh\ntouch %s\n" % (self.sb.root / "planted-ran"))
        planted.chmod(0o755)

    def run_preset(self, preset, path, cwd=None):
        with mock.patch.dict(os.environ, {"PATH": path}):
            return rc.run_chain("p", words=rc.GO_NOGO, fallback=preset, cwd=cwd or str(self.checkout))

    def test_a_normal_path_still_starts_the_real_claude(self):
        for n, preset in enumerate(rc.PRESETS.values(), 1):
            with self.subTest(preset=preset.name):
                self.sb.stub("claude", answer=GO)
                result = self.run_preset(preset, os.environ["PATH"])
                self.expect["claude"] = n
                self.assertEqual(result.reviewer, preset.name)
                self.assertEqual(len(self.claude_calls()), n)
                self.assertFalse((self.sb.root / "planted-ran").exists())

    def test_a_dot_an_empty_entry_and_a_relative_entry_do_not_run_the_checkouts_claude(self):
        self.planted(self.checkout)
        self.planted(self.checkout / "bin")
        for n, lead in enumerate((".", "", "bin"), 1):
            with self.subTest(lead=lead):
                self.sb.stub("claude", answer=GO)
                result = self.run_preset(rc.OPUS, os.pathsep.join([lead, os.environ["PATH"]]))
                self.expect["claude"] = n
                self.assertEqual(result.reviewer, "opus")
                self.assertEqual(len(self.claude_calls()), n)
                self.assertFalse((self.sb.root / "planted-ran").exists(), "the checkout's claude ran")

    def test_a_checkout_venv_bin_first_in_path_is_skipped(self):
        self.planted(self.checkout / ".venv" / "bin")
        path = os.pathsep.join([str(self.checkout / ".venv" / "bin"), os.environ["PATH"]])
        self.sb.stub("claude", answer=GO)
        self.expect["claude"] = 1
        result = self.run_preset(rc.FABLE, path)
        self.assertEqual(result.reviewer, "fable")
        self.assertEqual(len(self.claude_calls()), 1)
        self.assertFalse((self.sb.root / "planted-ran").exists(), "the checkout's claude ran")

    def test_a_symlink_into_the_checkout_is_refused(self):
        self.planted(self.checkout)
        self.sb.stub("claude", answer=GO)          # behind the link: reaching it would be a fall-through
        safe = self.sb.root / "safe-bin"
        safe.mkdir()
        (safe / "claude").symlink_to(self.checkout / "claude")
        path = os.pathsep.join([str(safe), os.environ["PATH"]])
        with mock.patch.dict(os.environ, {"PATH": path}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=rc.OPUS, cwd=str(self.checkout))
        self.assertEqual([a.reason for a in result.attempts if a.reviewer == "opus"], ["absent"])
        self.assertFalse((self.sb.root / "planted-ran").exists(), "the checkout's claude ran")

    def test_the_preset_is_started_by_its_absolute_path_with_the_rest_of_our_environment(self):
        self.sb.stub_script("claude", 'echo "$0" > "$R/claude.argv0"; env > "$R/claude.env"; echo "VERDICT: GO"')
        self.expect["claude"] = 1
        with mock.patch.dict(os.environ, {"KEPT_BY_THE_TEST": "yes", "PATH": ".:" + os.environ["PATH"]}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=rc.OPUS, cwd=str(self.checkout))
        self.assertEqual(result.reviewer, "opus")
        self.assertTrue((self.sb.root / "claude.argv0").read_text().strip().startswith("/"))
        seen = dict(l.split("=", 1) for l in (self.sb.root / "claude.env").read_text().splitlines() if "=" in l)
        self.assertEqual(seen.get("KEPT_BY_THE_TEST"), "yes")
        self.assertNotIn("", seen["PATH"].split(os.pathsep))
        self.assertNotIn(".", seen["PATH"].split(os.pathsep))

    def test_without_a_cwd_a_preset_under_the_current_directory_is_still_started(self):
        # boss-run passes no --cwd: the caller's directory (say $HOME) may hold a per-user install
        self.sb.stub("claude", answer=GO)
        self.expect["claude"] = 1
        self.planted(self.sb.root)
        self.chdir_to(self.sb.root)
        with mock.patch.dict(os.environ, {"PATH": ".:" + os.environ["PATH"]}):
            launch = rc.claude_launch(rc.OPUS, "p")       # stubs live under self.sb.root, below the cwd
            self.assertIsNotNone(launch)
            self.assertEqual(launch[0][0], str(self.sb.stubs / "claude"))
            self.assertNotIn(".", launch[1]["PATH"].split(os.pathsep))
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=rc.OPUS)
        self.assertEqual(result.reviewer, "opus")
        self.assertEqual(len(self.claude_calls()), 1)
        self.assertFalse((self.sb.root / "planted-ran").exists(), "the current directory's claude ran")

    def chdir_to(self, where):
        before = os.getcwd()
        os.chdir(where)
        self.addCleanup(os.chdir, before)

    def test_an_entry_inside_the_checkout_is_not_on_the_childs_path(self):
        self.sb.stub_script("claude", 'echo "$PATH" > "$R/claude.path"; echo "VERDICT: GO"')
        self.expect["claude"] = 1
        inside = self.checkout / "tools"
        inside.mkdir()
        self.run_preset(rc.OPUS, os.pathsep.join([str(inside), os.environ["PATH"]]))
        seen = (self.sb.root / "claude.path").read_text().strip().split(os.pathsep)
        self.assertNotIn(str(inside), seen)

    def test_when_the_only_claude_is_the_checkouts_the_preset_is_absent(self):
        self.planted(self.checkout)
        path = os.pathsep.join([".", str(self.checkout)])
        with mock.patch.dict(os.environ, {"PATH": path}):
            result = rc.run_chain("p", words=rc.GO_NOGO, fallback=rc.OPUS, cwd=str(self.checkout))
        self.assertEqual([a.reason for a in result.attempts if a.reviewer == "opus"], ["absent"])
        self.assertFalse((self.sb.root / "planted-ran").exists())


if __name__ == "__main__":
    unittest.main()
