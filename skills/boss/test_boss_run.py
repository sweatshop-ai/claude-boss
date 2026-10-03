#!/usr/bin/env python3
"""Tests for bin/boss-run, hermetically.

Run: python3 skills/boss/test_boss_run.py

boss-run asks a reviewer (codex, then Haiku through claude) whether a command
matches its stated intent, and runs the command only on APPROVE. Three kinds of
test live here:

  characterization   Approve ... ReviewerIsolation, MoreCharacterization: stdout,
                     stderr, exit status, the log line and how the reviewers are
                     called, as boss-run behaved before its reviewer logic moved
                     into reviewer_chain.py. They pass on both versions.
  the move           RenderedPrompt (the prompt reaches the reviewer literally, `&`
                     included) and FailClosed (a chain that crashes, prints garbage
                     or dies by a signal means nothing runs).
  the sandbox        SandboxSeal.

Nothing here touches a real codex, claude, gh or tmux: every run goes through
hermetic.Sandbox, which builds the child's environment from scratch and puts
only stubs and a whitelist of coreutils on PATH. Each test gets its own sandbox.
"""
import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hermetic import Sandbox, alive  # noqa: E402

HAIKU = "claude-haiku-4-5-20251001"
WHY = "post the status comment on the PR"
CMD = "touch dry.flag"
RAMBLE = "I would need more context before I can say anything about this."
LOG_KEYS = ["ts", "session", "cwd", "why", "cmd", "reviewer", "verdict", "reason", "exit"]
PUSH_MAIN_RE = "git[[:space:]]+push[^&|;]*(^|[[:space:]:/])(main|master)([[:space:]]|$)"
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

    def dry(self, *cmd, why=WHY, stdin=""):
        return self.sb.boss_run("--why", why, "--dry-run", "--", *(cmd or (CMD,)), stdin=stdin)

    def live(self, *cmd, why=WHY, extra=()):
        return self.sb.boss_run("--why", why, *extra, "--", *cmd)

    def only_log(self):
        lines = self.sb.log_lines()
        self.assertEqual(len(lines), 1, lines)
        return lines[0]

    def assertNotCalled(self, *names):
        for name in names:
            self.assertEqual(self.sb.calls_of(name), [], name)


class Approve(Base):
    def test_dry_run_approve_by_codex_prints_the_verdict_and_logs_one_line(self):
        self.sb.stub("codex", answer=approve("matches the intent"))
        r = self.dry()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "boss-run: APPROVE (reviewer: codex) — matches the intent\n"
                                   "  --dry-run: not executed.\n")
        self.assertEqual(r.stderr, "")
        entry = self.only_log()
        self.assertEqual(list(entry), LOG_KEYS)
        self.assertEqual(
            {k: entry[k] for k in ("session", "cwd", "why", "cmd", "reviewer", "verdict",
                                   "reason", "exit")},
            {"session": "sess-test", "cwd": str(self.sb.work), "why": WHY, "cmd": CMD,
             "reviewer": "codex", "verdict": "APPROVE", "reason": "matches the intent",
             "exit": 0})
        self.assertRegex(entry["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(Z|[+-]\d\d:\d\d)$")
        self.assertFalse((self.sb.work / "dry.flag").exists())

    def test_codex_is_called_once_with_a_read_only_sandbox_and_the_prompt_last(self):
        self.sb.stub("codex", answer=approve())
        self.dry()
        self.assertNotCalled("claude")
        calls = self.sb.calls_of("codex")
        self.assertEqual(len(calls), 1)
        argv = calls[0].argv
        self.assertEqual(argv[:7], CODEX_FIXED)
        self.assertEqual(len(argv), 9, argv)   # the -o path, then the prompt

    def test_the_reviewer_prompt_carries_the_intent_the_directory_and_the_command(self):
        self.sb.stub("codex", answer=approve())
        self.dry()
        prompt = self.sb.calls_of("codex")[0].argv[-1]
        self.assertIn("INTENT: %s\nWORKING DIRECTORY: %s\nCOMMAND: %s"
                      % (WHY, self.sb.work, CMD), prompt)
        self.assertNotIn("{{", prompt)

    def test_an_approved_command_runs_in_the_given_directory(self):
        self.sb.stub("codex", answer=approve())
        proj = self.sb.work / "proj"
        proj.mkdir()
        r = self.live("touch ran.flag", extra=("--cwd", str(proj)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((proj / "ran.flag").exists())
        self.assertFalse((self.sb.work / "ran.flag").exists())
        self.assertTrue(r.stdout.startswith("boss-run: APPROVE (reviewer: codex) — ok\n"))
        self.assertTrue(r.stdout.endswith("boss-run: command exited 0\n"), r.stdout)
        entry = self.only_log()
        self.assertEqual((entry["exit"], entry["cwd"]), (0, str(proj)))

    def test_the_commands_own_exit_status_passes_through(self):
        self.sb.stub("codex", answer=approve())
        r = self.live("exit 7")
        self.assertEqual(r.returncode, 7)
        self.assertTrue(r.stdout.endswith("boss-run: command exited 7\n"), r.stdout)
        entry = self.only_log()
        self.assertEqual((entry["verdict"], entry["exit"]), ("APPROVE", 7))

    def test_several_arguments_are_quoted_so_each_stays_one_word(self):
        self.sb.stub("codex", answer=approve())
        r = self.live("touch", "a b.flag")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.sb.work / "a b.flag").exists())
        self.assertEqual(self.only_log()["cmd"], "touch a\\ b.flag")
        self.assertIn("COMMAND: touch a\\ b.flag", self.sb.calls_of("codex")[0].argv[-1])

    def test_a_single_argument_is_a_shell_string_so_pipes_and_redirects_work(self):
        self.sb.stub("codex", answer=approve())
        r = self.live("echo hi | tr h H > out.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.sb.work / "out.txt").read_text(), "Hi\n")
        self.assertEqual(self.only_log()["cmd"], "echo hi | tr h H > out.txt")


class Reject(Base):
    def test_a_rejected_command_does_not_run_and_exits_3(self):
        self.sb.stub("codex", answer=reject("deletes more than asked"))
        r = self.live("touch must-not-run.flag")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")
        self.assertEqual(
            r.stderr,
            "boss-run: REJECTED by codex — deletes more than asked\n"
            "  command: touch must-not-run.flag\n"
            "  A REJECT is final for this command. Escalate it to the owner with the reason.\n")
        self.assertFalse((self.sb.work / "must-not-run.flag").exists())
        entry = self.only_log()
        self.assertEqual((entry["reviewer"], entry["verdict"], entry["reason"], entry["exit"]),
                         ("codex", "REJECT", "deletes more than asked", 3))
        self.assertNotCalled("claude")


class Fallback(Base):
    def test_without_codex_haiku_through_claude_answers(self):
        self.sb.stub("claude", answer=approve("haiku agrees"))
        r = self.dry()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "boss-run: APPROVE (reviewer: haiku) — haiku agrees\n"
                                   "  --dry-run: not executed.\n")
        entry = self.only_log()
        self.assertEqual((entry["reviewer"], entry["verdict"], entry["reason"]),
                         ("haiku", "APPROVE", "haiku agrees"))
        calls = self.sb.calls_of("claude")
        self.assertEqual(len(calls), 1)
        argv = calls[0].argv
        self.assertEqual(argv[:3], ["-p", "--model", HAIKU])
        self.assertEqual(len(argv), 4, argv)
        self.assertIn("INTENT: %s\n" % WHY, argv[3])

    def test_a_haiku_reject_is_final_too(self):
        self.sb.stub("claude", answer=reject("not what was asked"))
        r = self.live("touch must-not-run.flag")
        self.assertEqual(r.returncode, 3)
        self.assertTrue(r.stderr.startswith("boss-run: REJECTED by haiku — not what was asked\n"))
        self.assertFalse((self.sb.work / "must-not-run.flag").exists())

    def test_codex_that_fails_without_an_answer_falls_to_haiku(self):
        self.sb.stub("codex", rc=1)
        self.sb.stub("claude", answer=approve())
        r = self.dry()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(reviewer: haiku)", r.stdout)
        self.assertEqual(len(self.sb.calls_of("codex")), 1)
        self.assertEqual(len(self.sb.calls_of("claude")), 1)

    def test_codex_that_rambles_without_a_verdict_falls_to_haiku(self):
        self.sb.stub("codex", answer=RAMBLE)
        self.sb.stub("claude", answer=approve())
        r = self.dry()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(reviewer: haiku)", r.stdout)
        self.assertEqual(self.only_log()["reviewer"], "haiku")

    def test_a_codex_answer_means_claude_is_never_called(self):
        self.sb.stub("codex", answer=approve())
        self.sb.stub("claude", answer=reject())
        self.assertEqual(self.dry().returncode, 0)
        self.assertNotCalled("claude")

    def test_a_hung_codex_is_cut_off_with_its_children_and_haiku_answers(self):
        # Needs BOSS_RUN_REVIEW_TIMEOUT; boss-run's fixed 120 s would outlast the
        # 30 s allowed here.
        self.sb.stub("codex", hang=True, child=True)
        self.sb.stub("claude", answer=approve("fine"))
        r = self.sb.boss_run("--why", WHY, "--dry-run", "--", CMD, timeout=30,
                             extra_env={"BOSS_RUN_REVIEW_TIMEOUT": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(reviewer: haiku)", r.stdout)
        self.assertEqual(len(self.sb.calls_of("codex")), 1)
        self.assertEqual(len(self.sb.calls_of("claude")), 1)
        pid = int((self.sb.root / "child.pid").read_text())
        deadline = time.monotonic() + 3
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(pid), "the hung reviewer's child outlived boss-run")


class NoReviewer(Base):
    EXPECTED = ("boss-run: no reviewer answered (codex and claude-haiku-4-5-20251001 "
                "both silent or absent).\n"
                "  Nothing was run. Retry, or hand the command to the owner.\n")

    def check_nothing_ran(self, r):
        self.assertEqual(r.returncode, 4)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, self.EXPECTED)
        self.assertFalse((self.sb.work / "must-not-run.flag").exists())
        entry = self.only_log()
        self.assertEqual((entry["reviewer"], entry["verdict"], entry["reason"], entry["exit"]),
                         ("none", "", "no reviewer answered", 4))

    def test_no_codex_and_no_claude_means_nothing_runs(self):
        self.check_nothing_ran(self.live("touch must-not-run.flag"))
        self.assertNotCalled("codex", "claude")

    def test_two_reviewers_that_ramble_means_nothing_runs(self):
        self.sb.stub("codex", answer=RAMBLE)
        self.sb.stub("claude", answer=RAMBLE)
        self.check_nothing_ran(self.live("touch must-not-run.flag"))
        self.assertEqual(len(self.sb.calls_of("codex")), 1)
        self.assertEqual(len(self.sb.calls_of("claude")), 1)


class HardRules(Base):
    def test_a_push_to_main_is_refused_before_any_reviewer_is_asked(self):
        self.sb.stub("codex", answer=approve())
        self.sb.stub("claude", answer=approve())
        r = self.live("git", "push", "origin", "main")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(r.stdout, "")
        self.assertEqual(
            r.stderr,
            "boss-run: REFUSED by hard rule — push to main\n"
            "  pattern: " + PUSH_MAIN_RE + "\n"
            "  command: git push origin main\n"
            "  No reviewer can override this. Take it to the owner.\n")
        entry = self.only_log()
        self.assertEqual((entry["reviewer"], entry["verdict"], entry["exit"]),
                         ("hard-rule", "REFUSED", 5))
        self.assertEqual(entry["reason"],
                         "hard rule: push to main (matched /" + PUSH_MAIN_RE + "/)")
        self.assertEqual(entry["cmd"], "git push origin main")
        self.assertNotCalled("codex", "claude")

    def test_each_built_in_rule_names_itself(self):
        cases = [
            ("git push origin dev --force", "force push"),
            ("make deploy-prod", "prod deploy"),
            ("systemctl restart nginx", "prod service restart"),
            ("rm -rf ~/Documents/old", "recursive delete of non-regenerable data"),
            ("cat CLAUDE.md", "edit of settings.json / CLAUDE.md"),
            ("psql -c 'DROP TABLE users'", "DROP TABLE / DATABASE"),
            ("git reset --hard HEAD~1", "git reset --hard"),
            ("git clean -fd", "git clean -f"),
        ]
        for command, name in cases:
            with self.subTest(name):
                r = self.dry(command)
                self.assertEqual(r.returncode, 5, r.stdout)
                self.assertTrue(r.stderr.startswith(
                    "boss-run: REFUSED by hard rule — %s\n" % name), r.stderr)
                self.assertTrue(self.sb.log_lines()[-1]["reason"].startswith(
                    "hard rule: %s (matched /" % name))
        self.assertNotCalled("codex", "claude")

    def test_the_owners_own_rules_in_the_config_dir_are_checked_too(self):
        (self.sb.cfg / "boss-hard-rules.tsv").write_text("our host\tsecret-host\n")
        r = self.dry("scp file secret-host:/srv")
        self.assertEqual(r.returncode, 5)
        self.assertIn("REFUSED by hard rule — our host\n", r.stderr)
        self.assertNotCalled("codex", "claude")


class Usage(Base):
    def check(self, r, stderr):
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, stderr)
        self.assertEqual(self.sb.log_lines(), [])
        self.assertNotCalled("codex", "claude")

    def test_no_arguments_prints_the_usage_text(self):
        self.sb.stub("codex", answer=approve())
        r = self.sb.boss_run()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertTrue(r.stderr.startswith(
            'Usage:\n  boss-run --why "<intent>" [--cwd DIR] [--dry-run] -- <command ...>\n'),
            r.stderr)
        self.assertTrue(r.stderr.endswith("5                   refused by a hard rule\n"))
        self.assertNotCalled("codex")

    def test_a_missing_why_is_refused(self):
        self.check(self.sb.boss_run("--", "true"),
                   'boss-run: --why "<intent>" is required: '
                   'the reviewer judges the command against it\n')

    def test_an_empty_why_is_refused(self):
        self.check(self.sb.boss_run("--why", "", "--", "true"),
                   "boss-run: --why needs an intent\n")

    def test_an_unknown_argument_is_refused(self):
        self.check(self.sb.boss_run("--why", WHY, "--bogus", "--", "true"),
                   "boss-run: unknown argument: --bogus (command goes after --)\n")

    def test_no_command_after_the_double_dash_is_refused(self):
        self.check(self.sb.boss_run("--why", WHY, "--"),
                   "boss-run: no command — put it after --\n")

    def test_a_directory_that_does_not_exist_is_refused(self):
        gone = str(self.sb.root / "nope")
        self.check(self.sb.boss_run("--why", WHY, "--cwd", gone, "--", "true"),
                   "boss-run: no such directory: %s\n" % gone)


class VerdictParsing(Base):
    def test_how_a_codex_answer_becomes_a_verdict_and_a_reason(self):
        cases = [
            ("APPROVED counts as APPROVE", "VERDICT: APPROVED\nREASON: fine", "APPROVE", "fine", 0),
            ("REJECTED counts as REJECT", "VERDICT: REJECTED\nREASON: bad", "REJECT", "bad", 3),
            ("lower case verdict", "verdict: approve\nreason: lower", "APPROVE", "lower", 0),
            ("leading whitespace before VERDICT", "   VERDICT: APPROVE\nREASON: indented",
             "APPROVE", "indented", 0),
            ("a malformed VERDICT line is skipped", "VERDICT: maybe\nVERDICT: REJECT\nREASON: later",
             "REJECT", "later", 3),
            ("the first usable VERDICT wins", "VERDICT: APPROVE\nREASON: first\nVERDICT: REJECT",
             "APPROVE", "first", 0),
            ("an indented lower case reason is read", "VERDICT: APPROVE\n   reason: spaced out",
             "APPROVE", "spaced out", 0),
            ("no REASON line", "VERDICT: APPROVE", "APPROVE", "(no reason given)", 0),
            ("an empty REASON line", "VERDICT: APPROVE\nREASON:", "APPROVE", "(no reason given)", 0),
            ("a REASON line before the VERDICT line", "REASON: before\nVERDICT: APPROVE",
             "APPROVE", "before", 0),
            ("a preamble before the answer", "Thinking it over.\nVERDICT: REJECT\nREASON: nope",
             "REJECT", "nope", 3),
        ]
        for label, answer, verdict, reason, code in cases:
            with self.subTest(label):
                self.sb.stub("codex", answer=answer)
                r = self.dry()
                self.assertEqual(r.returncode, code, r.stderr)
                entry = self.sb.log_lines()[-1]
                self.assertEqual((entry["reviewer"], entry["verdict"], entry["reason"], entry["exit"]),
                                 ("codex", verdict, reason, code))


class ReviewerIsolation(Base):
    def test_the_codex_reviewer_gets_a_closed_stdin(self):
        self.sb.stub("codex", answer=approve())
        self.assertEqual(self.dry(stdin="leak-sentinel").returncode, 0)
        self.assertEqual(self.sb.calls_of("codex")[0].stdin, "")

    def test_the_haiku_reviewer_gets_a_closed_stdin(self):
        self.sb.stub("claude", answer=approve())
        self.assertEqual(self.dry(stdin="leak-sentinel").returncode, 0)
        self.assertEqual(self.sb.calls_of("claude")[0].stdin, "")

    def noisy(self, name, **kw):
        tag = name.upper()
        self.sb.stub(name, out="NOISE-%s-OUT" % tag, err="NOISE-%s-ERR" % tag, **kw)

    def assertQuiet(self, r):
        for text in (r.stdout, r.stderr, (self.sb.cfg / "pm" / "boss-run.log").read_text()):
            self.assertNotRegex(text, r"NOISE-")

    def test_reviewer_noise_stays_out_of_an_approve(self):
        self.noisy("codex", answer=approve())
        self.noisy("claude", answer=approve())
        self.assertQuiet(self.dry())
        self.sb.stub("codex", answer=RAMBLE, out="NOISE-CODEX-OUT", err="NOISE-CODEX-ERR")
        r = self.dry()
        self.assertIn("(reviewer: haiku)", r.stdout)
        self.assertQuiet(r)

    def test_reviewer_noise_stays_out_of_a_reject(self):
        self.noisy("codex", answer=reject())
        r = self.live("touch must-not-run.flag")
        self.assertEqual(r.returncode, 3)
        self.assertQuiet(r)

    def test_reviewer_noise_stays_out_of_a_no_answer(self):
        self.noisy("codex", rc=1)
        self.noisy("claude", rc=1)
        r = self.live("touch must-not-run.flag")
        self.assertEqual(r.returncode, 4)
        self.assertQuiet(r)
        self.assertEqual(len(self.sb.calls_of("codex")), 1)
        self.assertEqual(len(self.sb.calls_of("claude")), 1)


class SandboxSeal(Base):
    def test_the_guard_passes_and_the_env_is_built_from_scratch(self):
        self.sb.guard()
        self.assertEqual(set(self.sb.env), {"PATH", "HOME", "CLAUDE_CONFIG_DIR", "TMPDIR",
                                            "CLAUDE_CODE_SESSION_ID", "LC_ALL"})
        self.assertEqual(self.sb.env["PATH"].split(os.pathsep)[0], str(self.sb.stubs))

    def test_inside_an_approved_command_no_real_reviewer_or_tool_resolves(self):
        self.sb.stub("codex", answer=approve())
        self.sb.stub("claude")
        r = self.live("command -v gh codex claude tmux > found.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        found = (self.sb.work / "found.txt").read_text().split()
        self.assertEqual(found, [str(self.sb.stubs / "codex"), str(self.sb.stubs / "claude")])


class MoreCharacterization(Base):
    """Behaviour the ticket lists that the first 33 tests leave to the chain tests.
    These pass against the script as it was before the move, too."""

    ENTRY_TS = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(Z|[+-]\d\d:\d\d)$"

    def assertEntry(self, sb, entry, **expected):
        self.assertEqual(list(entry), LOG_KEYS)
        self.assertRegex(entry["ts"], self.ENTRY_TS)
        self.assertEqual({k: v for k, v in entry.items() if k != "ts"},
                         dict({"session": "sess-test", "cwd": str(sb.work), "why": WHY,
                               "cmd": CMD}, **expected))

    def test_no_space_after_the_colon_and_a_tab_instead_are_accepted(self):
        for answer, verdict, code in [("VERDICT:APPROVE\nREASON: tight", "APPROVE", 0),
                                      ("VERDICT:\tREJECT\nREASON: tab", "REJECT", 3)]:
            with self.subTest(answer):
                self.sb.stub("codex", answer=answer)
                r = self.dry()
                self.assertEqual(r.returncode, code, r.stderr)
                self.assertEqual(self.sb.log_lines()[-1]["verdict"], verdict)

    def test_a_usable_verdict_after_a_non_zero_exit_still_counts_for_either_reviewer(self):
        self.sb.stub("codex", answer=approve("codex said so"), rc=3)
        r = self.dry()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.only_log()["reviewer"], "codex")
        self.assertNotCalled("claude")
        sb2 = Sandbox()
        self.addCleanup(sb2.cleanup)
        sb2.stub("claude", answer=reject("haiku said so"), rc=2)
        r = sb2.boss_run("--why", WHY, "--dry-run", "--", CMD)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(sb2.log_lines()[0]["reviewer"], "haiku")

    def test_codex_progress_on_stdout_is_never_read_as_the_answer(self):
        self.sb.stub("codex", out=approve("progress, not an answer"))   # no answer in the -o file
        self.sb.stub("claude", answer=reject("the real answer"))
        r = self.dry()
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(self.only_log()["reviewer"], "haiku")
        sb2 = Sandbox()
        self.addCleanup(sb2.cleanup)
        sb2.stub("codex", out=approve("progress, not an answer"))
        r = sb2.boss_run("--why", WHY, "--dry-run", "--", CMD)
        self.assertEqual(r.returncode, 4, r.stderr)

    def test_the_nine_log_fields_and_their_values_for_haiku_none_and_a_hard_rule(self):
        self.sb.stub("claude", answer=approve("haiku agrees"))
        self.assertEqual(self.dry().returncode, 0)
        self.assertEntry(self.sb, self.sb.log_lines()[-1], reviewer="haiku", verdict="APPROVE",
                         reason="haiku agrees", exit=0)

        sb2 = Sandbox()
        self.addCleanup(sb2.cleanup)
        self.assertEqual(sb2.boss_run("--why", WHY, "--dry-run", "--", CMD).returncode, 4)
        self.assertEntry(sb2, sb2.log_lines()[-1], reviewer="none", verdict="",
                         reason="no reviewer answered", exit=4)

        sb3 = Sandbox()
        self.addCleanup(sb3.cleanup)
        self.assertEqual(sb3.boss_run("--why", WHY, "--dry-run", "--", "git push origin main").returncode, 5)
        self.assertEntry(sb3, sb3.log_lines()[-1], cmd="git push origin main", reviewer="hard-rule",
                         verdict="REFUSED", reason="hard rule: push to main (matched /%s/)" % PUSH_MAIN_RE,
                         exit=5)


class RenderedPrompt(Base):
    """The reviewer must judge the command as written. Substituting it into the
    template with bash's ${var//pat/rep} turned every `&` into the matched token
    (bash 5.2 patsub_replacement): `a && b` reached the reviewer as `a {{CMD}}{{CMD}} b`."""

    def template(self):
        return (HERE / "references" / "boss-run-review.md").read_text(encoding="utf-8")

    def prompt_for(self, why, *cmd):
        self.sb.stub("codex", answer=approve())
        r = self.dry(*cmd, why=why)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.sb.calls_of("codex")[-1].argv[-1]

    def test_a_command_with_ampersands_and_other_special_characters_reaches_the_reviewer_verbatim(self):
        for cmd in ["echo a & echo b", "true && echo done", "ls 2>&1 | head -1",
                    "echo 'https://example.test/x?a=1&b=2'", "echo \\& \\\\ \\n",
                    "echo $HOME `date` $(id) %s %d ${x//a/&}", "echo '{{WHY}} {{CWD}}'"]:
            with self.subTest(cmd=cmd):
                prompt = self.prompt_for(WHY, cmd)
                self.assertTrue(prompt.endswith("\nCOMMAND: " + cmd), prompt[-200:])

    def test_the_whole_prompt_is_the_template_with_the_three_values_in_literally(self):
        why = "tidy up the A&B && C \\ branch"
        cmd = "git branch -d a&b && echo 2>&1"
        prompt = self.prompt_for(why, cmd)
        expected = (self.template().rstrip("\n").replace("{{WHY}}", why)
                    .replace("{{CWD}}", str(self.sb.work)).replace("{{CMD}}", cmd))
        self.assertEqual(prompt, expected)

    def test_a_placeholder_written_inside_a_value_is_not_expanded_again(self):
        prompt = self.prompt_for("explain {{CMD}} and {{CWD}}", "echo hi")
        self.assertIn("INTENT: explain {{CMD}} and {{CWD}}\n", prompt)
        self.assertEqual(prompt.count("COMMAND: echo hi"), 1)


class FailClosed(Base):
    """boss-run runs the command only on a whole answer from the chain: exit 0, one JSON
    object, a reviewer's name, APPROVE or REJECT. Anything else is "no reviewer answered".
    Here `python3` is a stub, so the chain says whatever the test wants; a real approving
    codex is on PATH to prove the refusal does not come from a missing reviewer."""

    EXPECTED = NoReviewer.EXPECTED
    check_nothing_ran = NoReviewer.check_nothing_ran

    def setUp(self):
        super().setUp()
        self.sb.stub("codex", answer=approve())

    def chain_says(self, reviewer="codex", word="APPROVE", reason="chain reason", rc=0, **over):
        answer = {"reviewer": reviewer, "output": "", "attempts": [],
                  "parsed": {"word": word, "reason": reason}}
        answer.update(over)
        self.sb.stub("python3", out=json.dumps(answer), rc=rc)

    def raw_stub(self, name, body):
        path = self.sb.stubs / name
        path.write_text("#!%s\n%s\n" % (shutil.which("bash"), body), encoding="utf-8")
        path.chmod(0o755)

    def test_an_approving_chain_runs_the_command_and_boss_run_logs_what_the_chain_said(self):
        self.chain_says(reviewer="haiku", reason="by the chain")
        r = self.live("touch ran.flag")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.sb.work / "ran.flag").exists())
        self.assertTrue(r.stdout.startswith("boss-run: APPROVE (reviewer: haiku) — by the chain\n"))
        entry = self.only_log()
        self.assertEqual((entry["reviewer"], entry["verdict"], entry["reason"], entry["exit"]),
                         ("haiku", "APPROVE", "by the chain", 0))

    def test_a_rejecting_chain_exits_3_and_nothing_runs(self):
        self.chain_says(reviewer="codex", word="REJECT", reason="too wide")
        r = self.live("touch must-not-run.flag")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stderr.splitlines()[0], "boss-run: REJECTED by codex — too wide")
        self.assertFalse((self.sb.work / "must-not-run.flag").exists())

    def test_a_crashing_chain_means_nothing_runs(self):
        self.sb.stub("python3", rc=1, err="Traceback (most recent call last): boom")
        self.check_nothing_ran(self.live("touch must-not-run.flag"))

    def test_a_chain_that_dies_by_a_signal_means_nothing_runs(self):
        self.raw_stub("python3", "kill -KILL $$")
        self.check_nothing_ran(self.live("touch must-not-run.flag"))

    def test_garbage_on_stdout_means_nothing_runs(self):
        for garbage in ("not json at all", "", "{", "[]", "null", '"APPROVE"',
                        'VERDICT: APPROVE\nREASON: sneaky'):
            with self.subTest(garbage=garbage):
                self.sb.stub("python3", out=garbage)
                self.check_nothing_ran(self.live("touch must-not-run.flag"))
                (self.sb.cfg / "pm" / "boss-run.log").unlink()

    def test_json_that_does_not_name_a_reviewer_and_a_verdict_means_nothing_runs(self):
        for name, over in [
            ("reviewer none", {"reviewer": "none"}), ("empty reviewer", {"reviewer": ""}),
            ("no reviewer", {"reviewer": None}), ("odd verdict", {"word": "MAYBE"}),
            ("lower-case verdict", {"word": "approve"}), ("go is not approve", {"word": "GO"}),
            ("no parsed", {"parsed": None}), ("parsed without a word", {"parsed": {"reason": "x"}}),
            ("parsed without a reason", {"parsed": {"word": "APPROVE"}}),
            ("reason not text", {"parsed": {"word": "APPROVE", "reason": 7}}),
        ]:
            with self.subTest(name):
                self.chain_says(**over)
                self.check_nothing_ran(self.live("touch must-not-run.flag"))
                (self.sb.cfg / "pm" / "boss-run.log").unlink()

    def test_more_than_one_json_value_on_stdout_is_not_one_answer(self):
        # `jq -e` alone judges only the last value, so a refusal followed by an approval would pass.
        none = '{"reviewer":"none","output":"","parsed":null,"attempts":[]}'
        ok = '{"reviewer":"codex","output":"","parsed":{"word":"APPROVE","reason":"x"},"attempts":[]}'
        for name, text in [("refusal then approval", none + "\n" + ok),
                           ("two approvals", ok + "\n" + ok),
                           ("approval then garbage", ok + "\n{"),
                           ("garbage then approval", "{\n" + ok)]:
            with self.subTest(name):
                self.sb.stub("python3", out=text)
                self.check_nothing_ran(self.live("touch must-not-run.flag"))
                (self.sb.cfg / "pm" / "boss-run.log").unlink()

    def test_a_non_zero_exit_beats_json_that_looks_like_an_approval(self):
        self.chain_says(rc=1)
        self.check_nothing_ran(self.live("touch must-not-run.flag"))

    def test_boss_run_calls_the_chain_with_boss_runs_vocabulary_models_and_timeouts(self):
        self.chain_says()
        self.sb.boss_run("--why", WHY, "--dry-run", "--", CMD,
                         extra_env={"BOSS_RUN_REVIEW_TIMEOUT": "17"})
        (call,) = self.sb.calls_of("python3")
        argv = call.argv
        self.assertEqual(Path(argv[0]).resolve(), HERE / "reviewer_chain.py")
        flags = dict(zip(argv[3::2], argv[4::2]))
        self.assertEqual(argv[1], "--prompt-file")
        self.assertEqual(flags, {"--words": "APPROVE,REJECT", "--match": "prefix", "--effort": "medium",
                                 "--codex-timeout": "17", "--fallback-name": "haiku",
                                 "--fallback-model": HAIKU, "--fallback-timeout": "17"})
        self.assertEqual(call.stdin, "")

    def test_no_temporary_prompt_file_is_left_behind(self):
        for name, setup in [("approve", lambda: self.chain_says()),
                            ("reject", lambda: self.chain_says(word="REJECT")),
                            ("crash", lambda: self.sb.stub("python3", rc=1))]:
            with self.subTest(name):
                setup()
                self.live("true")
                self.assertEqual(list(self.sb.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
