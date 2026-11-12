#!/usr/bin/env python3
"""Tests for the waiver (ticket 09c): `boss_review.py --waive`, the consent token and the guard that writes it.

Run: python3 skills/boss/test_waiver.py

Hermetic as test_boss_review.py: `codex`, `claude` and `gh` are stubs (hermetic.Sandbox), `git` runs on a
throwaway repo, HOME and CLAUDE_CONFIG_DIR are temporary. The hook is run as the harness runs it, as a process
with JSON on stdin; the payloads are the real PostToolUse payloads of fixtures/askuser, captured from a live
session. The tests command is a shell line given to /bin/sh -c.
"""
import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import codex_blocker  # noqa: E402
import consent  # noqa: E402
import policy  # noqa: E402
import tracker  # noqa: E402
from hermetic import Sandbox  # noqa: E402
from test_boss_review import AUTHOR, OTHER_SHA, PR, REPO, Gh, git  # noqa: E402

GUARD = HERE / "boss-guard.py"
FIXTURES = HERE / "fixtures" / "askuser"
SID = "11111111-2222-3333-4444-555555555555"
TRACK = "t"
CMD = "/bin/true"
NOW = datetime(2026, 11, 12, 10, 30, 15, tzinfo=timezone.utc)
QUESTION = ("CONSENT: merge PRs of %s on tests alone while Codex is down (no review of any kind), "
            "only where nothing deploys? Command: %s")
OPEN = "# t\n\n## Open blockers\n%s\n\n## Decisions in force\n%s\n## Notes\n"


def blocker_text(choices=(), blocker_id="cd261112103015"):
    marker = tracker.render_marker(blocker_id, NOW, NOW + timedelta(minutes=5), ask=codex_blocker.ASK)
    line = "- Codex down: 3 failed Codex attempts in a row - T+0 2026-11-12T10:30+00:00 " + marker
    return OPEN % (line, "".join("- [codex-choice %s] %s - 2026-11-12T10:31:00+00:00\n" % (i, c)
                                 for i, c in choices))


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(extra_tools=("git",))
        self.addCleanup(self.sb.cleanup)
        env = dict(self.sb.env, BOSS_TYPESAFE_ENV=str(self.sb.root / "no-typesafe.env"), CLAUDE_CODE_SESSION_ID=SID)
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(tempfile, "tempdir", str(self.sb.tmp))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.pm = self.sb.cfg / "pm"
        self.pm.mkdir(parents=True, exist_ok=True)
        self.tracker = self.pm / (TRACK + ".md")
        self.set_tracker(choices=[("cd261112103015", "tests-alone")])
        self.checkout = self.sb.work / "checkout"
        self.checkout.mkdir()
        git(self.sb, self.checkout, "init", "-q")
        git(self.sb, self.checkout, "commit", "-q", "--allow-empty", "-m", "the PR head")
        self.head = git(self.sb, self.checkout, "rev-parse", "HEAD")
        self.gh = Gh(self.sb, self.head)
        self.sb.stub("claude", answer="VERDICT: GO")
        self.pr_dir = self.pm / "reviews" / "owner" / "repo" / ("pr%d" % PR)
        self.consent(CMD)

    def tearDown(self):
        self.sb.guard()
        self.assertEqual(self.sb.calls_of("claude"), [], "claude was called")
        self.assertEqual(self.sb.calls_of("codex"), [], "codex was called")

    def set_tracker(self, **kw):
        self.tracker.write_text(blocker_text(**kw), encoding="utf-8")

    def consent(self, cmd, **kw):
        kw.setdefault("track", TRACK)
        kw.setdefault("sid", SID)
        kw.setdefault("now", time.time())
        return consent.issue(kw["sid"], kw["track"], consent.cmd_hash(cmd), "toolu_1", now=kw["now"])

    def waive(self, cmd=CMD, **kw):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = br.waive(REPO, PR, str(self.checkout), AUTHOR, kw.pop("track", TRACK), cmd, **kw)
        self.err = err.getvalue()
        return result

    def comments(self):
        return [c for c in self.sb.calls_of("gh") if c.argv[:2] == ["pr", "comment"]]

    def rounds(self):
        return sorted(self.pr_dir.glob("round*.json")) if self.pr_dir.exists() else []

    def assertNothingRecorded(self):
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.rounds(), [])

    def refused(self, result):
        self.assertEqual(result.exit_code, 5, self.err)
        self.assertNothingRecorded()

    def token_file(self):
        return consent.token_path(SID)


class Recorded(Base):
    def test_all_conditions_met_records_one_waived_round_and_one_comment(self):
        result = self.waive()
        self.assertEqual((result.exit_code, result.round, result.status, result.verdict, result.kind),
                         (0, 1, "posted", "GO", "waived"), self.err)
        record = json.loads(result.record.read_text())
        self.assertEqual(set(record), {"repo", "pr", "round", "head_sha", "base", "reviewer", "model", "kind",
                                       "verdict", "status", "author", "ts", "attempts", "tests"})
        self.assertEqual((record["repo"], record["pr"], record["head_sha"], record["base"], record["author"]),
                         ("owner/repo", PR, self.head, "main", AUTHOR))
        self.assertEqual((record["reviewer"], record["model"], record["kind"], record["verdict"], record["status"],
                          record["attempts"], record["tests"]),
                         ("tests", None, "waived", "GO", "posted", [], {"cmd": CMD, "exit": 0}))
        (comment,) = self.comments()
        body = comment.argv[comment.argv.index("--body") + 1]
        self.assertEqual(body, "Merge on tests alone (Codex unavailable): %s passed on %s" % (CMD, self.head))
        self.assertFalse((self.pm / "reviews" / "attempts.jsonl").exists(), "a waiver logs no Codex attempt")

    def test_the_command_runs_through_sh_in_the_checkout_with_stdin_closed(self):
        marker = self.sb.side / "ran"
        cmd = 'pwd > %s; cat >> %s' % (shlex.quote(str(marker)), shlex.quote(str(marker)))
        self.consent(cmd)
        self.assertEqual(self.waive(cmd).exit_code, 0, self.err)
        self.assertEqual(marker.read_text().strip(), os.path.realpath(self.checkout))

    def test_the_comment_and_the_record_show_the_command_redacted(self):
        secret = "ghp_" + "a" * 36
        cmd = "/bin/true # %s" % secret
        self.consent(cmd)
        result = self.waive(cmd)
        self.assertEqual(result.exit_code, 0, self.err)
        (comment,) = self.comments()
        self.assertNotIn(secret, comment.argv[comment.argv.index("--body") + 1])
        self.assertNotIn(secret, result.record.read_text())

    def test_a_second_waiver_is_round_two(self):
        self.assertEqual(self.waive().round, 1)
        self.assertEqual(self.waive().round, 2)


class Refused(Base):
    def test_no_open_blocker(self):
        self.tracker.write_text("# t\n\n## Open blockers\n\n## Decisions in force\n", encoding="utf-8")
        self.refused(self.waive())

    def test_a_choice_of_wait_or_accept_fallback(self):
        for value in ("wait", "accept-fallback"):
            self.set_tracker(choices=[("cd261112103015", value)])
            self.refused(self.waive())

    def test_no_choice_at_all(self):
        self.set_tracker(choices=[])
        self.refused(self.waive())

    def test_a_tests_alone_line_for_another_id(self):
        self.set_tracker(choices=[("cd261112090000", "tests-alone")])
        self.refused(self.waive())

    def test_a_revoked_choice_is_not_tests_alone(self):
        self.set_tracker(choices=[("cd261112103015", "tests-alone"), ("cd261112103015", "wait")])
        self.refused(self.waive())

    def test_a_malformed_blocker(self):
        text = blocker_text().replace("last=0", "last=bad")
        self.tracker.write_text(text, encoding="utf-8")
        self.refused(self.waive())

    def test_a_failing_command(self):
        self.consent("/bin/false")
        self.refused(self.waive("/bin/false"))
        self.assertIn("tests failed", self.err)

    def test_a_command_that_outlasts_the_timeout(self):
        cmd = "/bin/sleep 30"
        self.consent(cmd)
        start = time.monotonic()
        self.refused(self.waive(cmd, test_timeout=1))
        self.assertLess(time.monotonic() - start, 20)
        self.assertIn("ran past", self.err)

    def test_the_timeout_is_the_policys(self):
        self.assertEqual(policy.WAIVE_TEST_TIMEOUT, 900)
        self.assertEqual(policy.CONSENT_TTL, 600)

    def test_a_dirty_checkout_before_the_tests(self):
        (self.checkout / "scratch.txt").write_text("x")      # untracked files count
        ran = self.sb.side / "ran"
        cmd = "touch %s" % shlex.quote(str(ran))
        self.consent(cmd)
        self.refused(self.waive(cmd))
        self.assertFalse(ran.exists(), "the tests ran on a dirty checkout")

    def test_the_cheap_conditions_come_before_the_command(self):
        self.set_tracker(choices=[])
        ran = self.sb.side / "ran"
        cmd = "touch %s" % shlex.quote(str(ran))
        self.consent(cmd)
        self.refused(self.waive(cmd))
        self.assertFalse(ran.exists())


class TheTokenIsChecked(Base):
    def test_no_token(self):
        self.token_file().unlink()
        self.refused(self.waive())

    def test_another_command(self):
        self.consent("/bin/true && echo other")
        self.refused(self.waive())

    def test_another_track(self):
        self.consent(CMD, track="other")
        self.refused(self.waive())

    def test_another_session(self):
        self.token_file().unlink()
        self.consent(CMD, sid="99999999-2222-3333-4444-555555555555")
        self.refused(self.waive())

    def test_no_session_id_in_the_environment(self):
        with mock.patch.dict(os.environ):
            del os.environ["CLAUDE_CODE_SESSION_ID"]
            self.refused(self.waive())

    def test_a_malformed_token(self):
        for body in ("", "not json", "[]", json.dumps({"schema": 1})):
            self.token_file().write_text(body)
            os.chmod(self.token_file(), 0o600)
            self.refused(self.waive())

    def test_a_token_others_can_read_is_refused(self):
        os.chmod(self.token_file(), 0o644)
        self.refused(self.waive())

    def test_a_symlinked_token_is_refused(self):
        real = self.sb.side / "real.json"
        real.write_text(self.token_file().read_text())
        os.chmod(real, 0o600)
        self.token_file().unlink()
        self.token_file().symlink_to(real)
        self.refused(self.waive())

    def test_an_unreadable_token_directory(self):
        os.chmod(self.token_file().parent, 0)
        self.addCleanup(os.chmod, self.token_file().parent, 0o700)
        if os.access(self.token_file().parent, os.R_OK):
            self.skipTest("running as a user the mode does not bind")
        self.refused(self.waive())

    def test_expiry_at_ttl_minus_one_ttl_and_ttl_plus_one(self):
        issued = 1_000_000.0
        self.consent(CMD, now=issued)
        digest = consent.cmd_hash(CMD)
        for delta, ok in ((policy.CONSENT_TTL - 1, True), (policy.CONSENT_TTL, False), (policy.CONSENT_TTL + 1, False)):
            with self.subTest(delta):
                got, why, _ = consent.check(TRACK, digest, now=issued + delta)
                self.assertEqual(got, ok, why)

    def test_a_token_that_expired_refuses_the_waiver(self):
        self.consent(CMD, now=time.time() - policy.CONSENT_TTL - 5)
        self.refused(self.waive())

    def test_a_token_revoked_during_the_tests(self):
        cmd = "/bin/rm %s" % shlex.quote(str(self.token_file()))
        self.consent(cmd)
        self.refused(self.waive(cmd))
        self.assertIn("during the tests", self.err)

    def test_a_token_replaced_during_the_tests(self):
        # a later "yes" to the same question during the tests: a new token (another tool-use id)
        fresh = self.sb.side / "fresh.json"
        cmd = "/bin/cp %s %s" % (shlex.quote(str(fresh)), shlex.quote(str(self.token_file())))
        self.consent(cmd)
        consent.issue(SID, TRACK, consent.cmd_hash(cmd), "toolu_2", now=time.time() + 1)
        fresh.write_bytes(self.token_file().read_bytes())
        os.chmod(fresh, 0o600)
        self.consent(cmd)                      # back to the token the waiver starts with
        self.refused(self.waive(cmd))
        self.assertIn("replaced", self.err)


class DuringTheTests(Base):
    def edit(self, text):
        """A command that replaces the tracker with `text`."""
        alt = self.sb.side / "alt.md"
        alt.write_text(text, encoding="utf-8")
        cmd = "/bin/cp %s %s" % (shlex.quote(str(alt)), shlex.quote(str(self.tracker)))
        self.consent(cmd)
        return cmd

    def test_a_choice_replaced_by_wait(self):
        cmd = self.edit(blocker_text(choices=[("cd261112103015", "tests-alone"), ("cd261112103015", "wait")]))
        self.refused(self.waive(cmd))

    def test_a_blocker_cleared(self):
        cmd = self.edit("# t\n\n## Open blockers\n\n## Decisions in force\n")
        self.refused(self.waive(cmd))

    def test_a_new_blocker_with_the_same_choice_line_is_another_blocker(self):
        cmd = self.edit(blocker_text(choices=[("cd261112103015", "tests-alone")], blocker_id="cd261112110000"))
        self.refused(self.waive(cmd))

    def test_the_checkout_moved(self):
        cmd = "git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m moved"
        self.consent(cmd)
        result = self.waive(cmd)
        self.assertEqual((result.exit_code, result.status, result.verdict), (6, "head-moved", "GO"), self.err)
        self.assertEqual(self.comments(), [])
        self.assertEqual(json.loads(result.record.read_text())["kind"], "waived")

    def test_the_checkout_turned_dirty(self):
        cmd = "echo x > new-file"
        self.consent(cmd)
        result = self.waive(cmd)
        self.assertEqual((result.exit_code, result.status), (6, "head-moved"), self.err)
        self.assertEqual(self.comments(), [])

    def test_the_pr_head_moved(self):
        self.gh.configure(view=[{}, {"patch": {"headRefOid": OTHER_SHA}}])
        result = self.waive()
        self.assertEqual((result.exit_code, result.status), (6, "head-moved"), self.err)
        self.assertEqual(self.comments(), [])

    def test_the_pr_base_moved(self):
        self.gh.configure(view=[{}, {"patch": {"baseRefName": "other"}}])
        result = self.waive()
        self.assertEqual((result.exit_code, result.status), (6, "head-moved"), self.err)
        self.assertEqual(self.comments(), [])


class Infrastructure(Base):
    def test_a_command_that_cannot_be_started(self):
        real = br._spawn

        def spawn(argv, *a, **kw):
            if argv[:2] == ["/bin/sh", "-c"]:
                return br._Out(None, b"", "no such shell", False)
            return real(argv, *a, **kw)

        with mock.patch.object(br, "_spawn", spawn):
            result = self.waive()
        self.assertEqual(result.exit_code, 7, self.err)
        self.assertNothingRecorded()

    def test_a_post_that_fails(self):
        self.gh.configure(comment=[{"rc": 1, "err": "boom"}])
        result = self.waive()
        self.assertEqual((result.exit_code, result.status), (7, "post-failed"), self.err)
        self.assertEqual(json.loads(result.record.read_text())["status"], "post-failed")

    def test_a_gh_that_fails(self):
        self.gh.configure(view=[{"rc": 1}])
        result = self.waive()
        self.assertEqual(result.exit_code, 7)
        self.assertNothingRecorded()


class Usage(Base):
    def test_gh_answering_with_another_pr_is_exit_2(self):
        self.gh.set_pr(number=PR + 1)
        self.assertEqual(self.waive().exit_code, 2)
        self.assertNothingRecorded()

    def test_a_checkout_whose_head_is_not_the_pr_head(self):
        self.gh.set_pr(headRefOid=OTHER_SHA)
        self.assertEqual(self.waive().exit_code, 2)
        self.assertNothingRecorded()

    def test_an_invalid_track(self):
        for track in ("../x", "", "A b", "a/b"):
            with self.assertRaises(ValueError):
                br.waive(REPO, PR, str(self.checkout), AUTHOR, track, CMD)

    def test_an_empty_command(self):
        for cmd in ("", "  ", "a\0b"):
            with self.assertRaises(ValueError):
                br.waive(REPO, PR, str(self.checkout), AUTHOR, TRACK, cmd)

    def cli(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                code = br.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        self.err = err.getvalue()
        return code

    WAIVE = ("--waive", "--repo", REPO, "--pr", str(PR), "--author", AUTHOR, "--track", TRACK, "--test-cmd", CMD)

    def test_the_command_line_runs_the_waiver(self):
        self.assertEqual(self.cli(*self.WAIVE, "--checkout", str(self.checkout)), 0, self.err)
        self.assertEqual(len(self.comments()), 1)

    def test_flags_waive_refuses(self):
        base = (*self.WAIVE, "--checkout", str(self.checkout))
        self.assertEqual(self.cli(*base, "--check-fallback"), 2)
        self.assertEqual(self.cli(*[a for a in base if a not in ("--test-cmd", CMD)]), 2)
        self.assertEqual(self.cli(*[a for a in base if a not in ("--track", TRACK)]), 2)
        self.assertEqual(self.cli("--repo", REPO, "--pr", str(PR), "--author", AUTHOR, "--checkout", str(self.checkout),
                                  "--test-cmd", CMD), 2)
        self.assertEqual(self.cli(*base[:-2], "--track", "../x", "--checkout", str(self.checkout)), 2)
        self.assertNothingRecorded()

    def test_the_command_line_exit_5_on_a_refusal(self):
        self.token_file().unlink()
        self.assertEqual(self.cli(*self.WAIVE, "--checkout", str(self.checkout)), 5)


class Choose(Base):
    def setUp(self):
        super().setUp()
        self.set_tracker(choices=[])

    def lines(self):
        return [ln for ln in self.tracker.read_text().split("\n") if ln.startswith("- [codex-choice")]

    def test_tests_alone_is_written_with_the_token(self):
        rc, msg = codex_blocker.choose(TRACK, "tests-alone", test_cmd=CMD)
        self.assertEqual(rc, 0, msg)
        self.assertEqual(codex_blocker.choice(TRACK)[2], "tests-alone")

    def test_tests_alone_is_denied_without_the_token_and_writes_nothing(self):
        self.token_file().unlink()
        before = self.tracker.read_text()
        rc, msg = codex_blocker.choose(TRACK, "tests-alone", test_cmd=CMD)
        self.assertEqual(rc, 2, msg)
        self.assertEqual(self.tracker.read_text(), before)

    def test_tests_alone_is_denied_for_another_command_or_none(self):
        before = self.tracker.read_text()
        for cmd in ("/bin/false", None, ""):
            self.assertEqual(codex_blocker.choose(TRACK, "tests-alone", test_cmd=cmd)[0], 2, cmd)
        self.assertEqual(self.tracker.read_text(), before)

    def test_wait_and_accept_fallback_need_no_token(self):
        self.token_file().unlink()
        self.assertEqual(codex_blocker.choose(TRACK, "wait")[0], 0)
        self.assertEqual(codex_blocker.choose(TRACK, "accept-fallback")[0], 0)

    def test_revoking_to_wait_after_tests_alone_is_free(self):
        self.assertEqual(codex_blocker.choose(TRACK, "tests-alone", test_cmd=CMD)[0], 0)
        self.token_file().unlink()
        self.assertEqual(codex_blocker.choose(TRACK, "wait")[0], 0)
        self.assertEqual(codex_blocker.choice(TRACK)[2], "wait")

    def test_the_command_line(self):
        script = HERE / "codex_blocker.py"
        env = dict(os.environ)
        def run(*a):
            return subprocess.run([sys.executable, str(script), *a], capture_output=True, text=True, env=env)
        self.assertEqual(run("--choose", TRACK, "tests-alone", "--test-cmd", CMD).returncode, 0)
        self.token_file().unlink()
        self.set_tracker(choices=[])
        denied = run("--choose", TRACK, "tests-alone", "--test-cmd", CMD)
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertEqual(run("--choose", TRACK, "tests-alone").returncode, 2)
        self.assertEqual(self.lines(), [])


class Question(unittest.TestCase):
    def test_the_question_names_the_track_and_the_command(self):
        got = consent.parse_question(QUESTION % ("codex-down", "python3 -m pytest -q"))
        self.assertEqual(got, ("codex-down", consent.cmd_hash("python3 -m pytest -q")))

    def test_the_question_may_carry_the_hash_of_a_long_command(self):
        digest = consent.cmd_hash("x" * 1000)
        self.assertEqual(consent.parse_question(QUESTION % ("t", "sha256:" + digest)), ("t", digest))

    def test_other_questions_name_nothing(self):
        for text in ("proceed?", "CONSENT: yes?", QUESTION % ("../x", CMD), QUESTION % ("t", ""), None, 5):
            with self.subTest(text):
                self.assertIsNone(consent.parse_question(text))


class Hook(unittest.TestCase):
    """The guard as the harness runs it. PostToolUse payloads are the captured ones."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="waiver-hook-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cfg = Path(self.tmp)
        self.markers = self.cfg / "pm" / ".boss-sessions"
        self.markers.mkdir(parents=True)
        (self.markers / SID).write_text(TRACK + "\n", encoding="utf-8")
        self.cmd = "python3 -m pytest -q"
        self.text = QUESTION % (TRACK, self.cmd)

    def run_hook(self, payload, sid=SID):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), HOME=str(self.cfg))
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        run = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(dict(payload, session_id=sid)),
                             capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)["hookSpecificOutput"] if run.stdout.strip() else {}

    def fixture(self, name, text=None, answer=None, questions=None):
        """A captured payload with the question text, and the answer, put where they belong."""
        payload = json.loads((FIXTURES / ("post-ask-%s.json" % name)).read_text())
        old = payload["tool_input"]["questions"][0]["question"]
        text = text or self.text
        payload["tool_input"]["questions"][0]["question"] = text
        payload["tool_response"]["questions"][0]["question"] = text
        if answer is None:
            answer = payload["tool_response"]["answers"][old]
        for part in (payload["tool_input"], payload["tool_response"]):
            part["answers"] = {text: answer}
        if questions is not None:
            payload["tool_input"]["questions"] = questions
        return payload

    def yes(self, **kw):
        return self.fixture("yes", answer=consent.AFFIRMATIVE, **kw)

    def token(self, sid=SID):
        path = consent.token_path(sid, self.cfg)
        return json.loads(path.read_text()) if path.exists() else None

    def pre_bash(self, command, sid=SID):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}, sid)

    # ---- the captured payloads
    def test_the_captured_payloads_hold_the_answer_where_the_hook_reads_it(self):
        for name, answer in (("yes", "Yes, proceed"), ("no", "No, stop"), ("free-text", "maybe later, ask Anna")):
            payload = json.loads((FIXTURES / ("post-ask-%s.json" % name)).read_text())
            self.assertEqual(payload["hook_event_name"], "PostToolUse")
            (question,) = [q["question"] for q in payload["tool_response"]["questions"]]
            self.assertEqual(payload["tool_response"]["answers"], {question: answer})
        for path in FIXTURES.glob("*.json"):
            text = path.read_text()
            self.assertNotIn("/home/", text, path.name)
            self.assertNotRegex(text, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path.name)

    def test_a_subagent_has_the_parents_session_id_and_an_agent_id(self):
        payload = json.loads((FIXTURES / "post-bash-in-subagent.json").read_text())
        self.assertEqual(payload["session_id"], "SESSION-ID")      # the parent's: it was replaced by one placeholder
        self.assertIn("agent_id", payload)

    # ---- the writer
    def test_yes_writes_the_token(self):
        self.run_hook(self.yes())
        token = self.token()
        self.assertEqual((token["session_id"], token["action"], token["track"], token["command_sha256"]),
                         (SID, "tests-alone", TRACK, consent.cmd_hash(self.cmd)))
        self.assertEqual(token["expires"] - token["issued"], policy.CONSENT_TTL)
        self.assertEqual(token["schema"], 1)
        self.assertEqual(token["tool_use_id"], "toolu_TOOL-USE-ID")
        self.assertEqual(oct(os.stat(consent.token_path(SID, self.cfg)).st_mode & 0o777), "0o600")

    def test_no_writes_no_token(self):
        self.run_hook(self.fixture("no"))
        self.assertIsNone(self.token())

    def test_free_text_writes_no_token(self):
        self.run_hook(self.fixture("free-text"))
        self.assertIsNone(self.token())

    def test_a_yes_to_a_question_that_is_not_the_consent_writes_none(self):
        self.run_hook(self.yes(text="proceed?"))
        self.assertIsNone(self.token())

    def test_another_affirmative_label_writes_none(self):
        self.run_hook(self.fixture("yes", answer="Yes"))
        self.assertIsNone(self.token())

    def test_two_questions_in_one_ask_write_none(self):
        payload = self.yes()
        payload["tool_input"]["questions"].append(dict(payload["tool_input"]["questions"][0], question="and also?"))
        self.run_hook(payload)
        self.assertIsNone(self.token())

    def test_another_track_than_the_boss_writes_none(self):
        self.run_hook(self.yes(text=QUESTION % ("other", self.cmd)))
        self.assertIsNone(self.token())

    def test_a_later_ask_invalidates_the_token(self):
        self.run_hook(self.yes())
        self.assertIsNotNone(self.token())
        self.run_hook(self.fixture("free-text"))
        self.assertIsNone(self.token())

    def test_a_later_no_to_the_same_question_invalidates_it(self):
        self.run_hook(self.yes())
        self.run_hook(self.fixture("no", text=self.text))
        self.assertIsNone(self.token())

    def test_a_subagents_ask_issues_nothing(self):
        self.run_hook(dict(self.yes(), agent_id="a1", agent_type="general-purpose"))
        self.assertIsNone(self.token())

    def test_an_unregistered_session_gets_no_token(self):
        other = "99999999-2222-3333-4444-555555555555"
        self.run_hook(self.yes(), sid=other)
        self.assertIsNone(self.token(other))

    def test_the_hook_is_wired_in_hooks_json(self):
        hooks = json.loads((HERE.parent.parent / "hooks" / "hooks.json").read_text())["hooks"]
        (entry,) = hooks["PostToolUse"]
        self.assertEqual(entry["matcher"], "AskUserQuestion")
        self.assertIn("skills/boss/boss-guard.py", entry["hooks"][0]["command"])

    # ---- the command-side check in the guard
    def test_the_guard_denies_the_commands_without_a_token(self):
        for command in (
                "python3 skills/boss/codex_blocker.py --choose t tests-alone --test-cmd 'pytest -q'",
                "cd /x && python3 /p/skills/boss/boss_review.py --waive --repo o/r --pr 1 --checkout . "
                "--author a --track t --test-cmd 'pytest -q'",
                "python3 boss_review.py --repo o/r --waive --track=t --test-cmd='pytest -q'"):
            with self.subTest(command):
                out = self.pre_bash(command)
                self.assertEqual(out.get("permissionDecision"), "deny", command)

    def test_the_guard_lets_a_command_with_a_valid_token_through(self):
        self.run_hook(self.yes())
        quoted = shlex.quote(self.cmd)
        out = self.pre_bash("python3 skills/boss/boss_review.py --waive --repo o/r --pr 1 --checkout . --author a "
                            "--track t --test-cmd %s" % quoted)
        self.assertNotEqual(out.get("permissionDecision"), "deny", out)

    def test_the_guard_denies_another_command_than_the_consented_one(self):
        self.run_hook(self.yes())
        out = self.pre_bash("python3 skills/boss/codex_blocker.py --choose t tests-alone --test-cmd 'rm -rf /'")
        self.assertEqual(out.get("permissionDecision"), "deny")

    def test_the_guard_does_not_deny_wait_or_other_commands(self):
        for command in ("python3 skills/boss/codex_blocker.py --choose t wait", "python3 skills/boss/codex_blocker.py --choice t",
                        "python3 skills/boss/boss_review.py --repo o/r --pr 1 --checkout . --author a",
                        "git commit -m 'boss_review.py --waive'"):
            self.assertNotEqual(self.pre_bash(command).get("permissionDecision"), "deny", command)

    def test_a_huge_command_costs_the_consent_check_nothing(self):
        """CI found the check splitting 1 MB of quoted text before the guard's own size limit applied."""
        big = "x" * 1_000_000
        for command, denied in (('echo "%s" >> ~/.claude/pm/a.md' % big, False),
                                ('python3 boss_review.py --waive --track t --test-cmd x "%s"' % big, True)):
            started = time.monotonic()
            out = self.pre_bash(command)
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(out.get("permissionDecision") == "deny" and "consent" in out.get("permissionDecisionReason", ""),
                             denied)

    def test_an_unregistered_session_is_not_guarded_and_the_command_still_denies(self):
        other = "99999999-2222-3333-4444-555555555555"
        self.assertEqual(self.pre_bash("python3 boss_review.py --waive --track t --test-cmd x", sid=other), {})


class Wrappers(Base):
    """`bash -c` and `boss-run` hide the words from the guard: the command is what refuses."""

    def test_the_command_denies_whatever_wrapper_ran_it(self):
        self.token_file().unlink()
        line = "%s %s --waive --repo %s --pr %d --checkout %s --author %s --track %s --test-cmd %s" % (
            sys.executable, HERE / "boss_review.py", REPO, PR, self.checkout, AUTHOR, TRACK, shlex.quote(CMD))
        for wrapper in (["bash", "-c", line], ["/bin/sh", "-c", line], ["/bin/sh", "-c", "X=%s; $X" % shlex.quote(line)]):
            run = subprocess.run(wrapper, capture_output=True, text=True, env=dict(os.environ), timeout=60)
            self.assertEqual(run.returncode, 5, (wrapper, run.stderr))
            self.assertIn("no consent token", run.stderr)
        self.assertEqual(self.comments(), [])


if __name__ == "__main__":
    unittest.main()
