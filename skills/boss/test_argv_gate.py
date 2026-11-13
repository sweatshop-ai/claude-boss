#!/usr/bin/env python3
"""Tests for argv_gate.py: the allowlist boss-run puts in front of the reviewer (ticket 53b).

Run: python3 skills/boss/test_argv_gate.py

boss-run runs only what it can see completely: an argument list, never a shell string.
argv_gate turns a single-argument command into that list when it is fully literal, and
refuses it otherwise; then refuses the lists that name a program which runs another command.

The first class below holds the twelve ways Codex hid a merge from PR 148's lexer
(rounds 1 to 3). None is read any more: each is refused by construction.
"""
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import argv_gate  # noqa: E402
from argv_gate import Refused, plan  # noqa: E402

GATE = HERE / "argv_gate.py"


class Env(unittest.TestCase):
    """A fake `gh`, a throwaway HOME for git, and a PATH made only of them and real tools."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="argv-gate-")).resolve()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()
        for name in ("cp", "mkdir", "ls", "cat", "echo", "touch", "git", "curl", "wget", "jq",
                     "systemctl", "grep", "rg", "tar", "rsync", "head", "tail", "date",
                     "python3", "bash", "sh", "env", "find", "sed", "awk", "xargs", "ssh"):
            real = argv_gate.shutil.which(name)
            if real:
                (self.bin / name).symlink_to(real)
        self.set_gh(aliases=(), extensions=())
        self.env = {"PATH": str(self.bin), "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1",
                    "LC_ALL": "C.UTF-8"}
        subprocess.run(["git", "init", "-q", str(self.work)], check=True, env=self.env)

    def set_gh(self, aliases=(), extensions=(), fail=None):
        """A `gh` that reports the aliases and extensions it is told, or fails with `fail`."""
        lines = ["#!/bin/sh"]
        if fail:
            lines.append("echo 'boom' >&2; exit %d" % fail)
        else:
            body = {"alias": "".join("%s: %s\n" % a for a in aliases),
                    "extension": "".join("gh %s\towner/gh-%s\tv1\n" % (e, e) for e in extensions)}
            lines.append('case "$1" in')
            for key, text in body.items():
                lines.append("  %s) printf '%%s' %s; exit 0 ;;" % (key, _sh(text)))
            lines.append("  *) echo 'the fake gh ran' >&2; exit 0 ;;\nesac")
        path = self.bin / "gh"
        path.write_text("\n".join(lines) + "\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_plan(self, *args, single=None):
        """plan() on a command: one argument is a shell string, several are an argument list."""
        return plan(list(args), single=(len(args) == 1) if single is None else single,
                    cwd=str(self.work), env=self.env)

    def refused(self, *args, single=None):
        with self.assertRaises(Refused) as cm:
            self.run_plan(*args, single=single)
        return cm.exception

    def argv(self, *args, single=None):
        return self.run_plan(*args, single=single).argv


def _sh(text):
    return "'" + text.replace("'", "'\\''") + "'"


class CodexBypasses(Env):
    """The twelve findings of PR 148, rounds 1 to 3. Each must be refused, none read."""

    ROUND1 = [
        ("env -S", """env -S '"gh" pr merge 5'"""),
        ("flock -c", """flock /tmp/x -c '"gh" pr merge 5'"""),
        ("script -c", """script -qc '"gh" pr merge 5' /dev/null"""),
        ("watch", """watch -n1 '"gh" pr merge 5'"""),
        ("time -p", """time -p sh -c '"gh" pr merge 5'"""),
        ("coproc", """coproc JOB sh -c '"gh" pr merge 5'"""),
        ("BASH_ENV", "BASH_ENV=/tmp/unseen bash -c true"),
        ("--rcfile", "bash --rcfile /tmp/unseen -ic true"),
    ]
    ROUND2 = [
        ("curl PUT merge", """"curl" -X "PUT" https://api.github.com/repos/o/r/pulls/5/merge"""),
        ("env --split-string", 'env --split-string="$X"'),
    ]
    ROUND3 = [
        ("${x@P}", "x=\"$(printf '\\\\$(gh pr merge 5)')\"; echo ${x@P}"),
        ("find -exec chain", """GH=g'h'; export GH; find . -maxdepth 0 -exec sh -c true \\; -exec "$GH" pr m'er'ge 5 \\;"""),
        ("alias write then use", """gh alias set m 'pr merge'; gh m 5"""),
    ]

    def test_every_finding_is_refused_before_a_reviewer_sees_it(self):
        for label, cmd in self.ROUND1 + self.ROUND2 + self.ROUND3:
            with self.subTest(label):
                self.refused(cmd)

    def test_the_same_programs_as_an_argument_list_are_refused_too(self):
        for label, argv in (
            ("env -S", ["env", "-S", '"gh" pr merge 5']),
            ("flock", ["flock", "/tmp/x", "-c", "gh pr merge 5"]),
            ("script", ["script", "-qc", "gh pr merge 5", "/dev/null"]),
            ("watch", ["watch", "gh", "pr", "merge", "5"]),
            ("time", ["time", "-p", "sh", "-c", "gh pr merge 5"]),
            ("bash", ["bash", "-c", "gh pr merge 5"]),
            ("find -exec", ["find", ".", "-exec", "gh", "pr", "merge", "5", ";"]),
            ("curl PUT", ["curl", "-X", "PUT", "https://api.github.com/repos/o/r/pulls/5/merge"]),
        ):
            with self.subTest(label):
                self.refused(*argv)

    def test_a_gh_alias_the_gh_itself_reports_is_refused_whatever_it_expands_to(self):
        for label, expansion in (("plain", "pr merge"), ("yaml escape", "pr \\u006derge"),
                                 ("commented", "pr merge"), ("shell", "!gh pr merge")):
            with self.subTest(label):
                self.set_gh(aliases=[("m", expansion)])
                e = self.refused("gh", "m", "5")
                self.assertIn("alias", e.name)

    def test_a_gh_extension_is_refused(self):
        self.set_gh(extensions=["copilot"])
        self.assertIn("extension", self.refused("gh", "copilot").name)

    def test_gh_that_cannot_report_its_aliases_refuses(self):
        self.set_gh(fail=4)
        e = self.refused("gh", "pr", "view", "5")
        self.assertIn("alias", e.name)

    def test_gh_pr_merge_in_every_literal_spelling_reaches_the_hard_rule_as_one_text(self):
        # The hard rule PR merge outside boss_merge (a regex in boss-run, ticket 41) reads this text;
        # test_boss_run pins that it refuses each. Quotes are gone by now: nothing hides in them.
        for cmd, flat in (('"gh" pr merge 5', "gh pr merge 5"), ("gh pr 'merge' 5", "gh pr merge 5"),
                          ("g'h' pr m'er'ge 5", "gh pr merge 5"), ("gh pr --repo o/r merge 5", "gh pr --repo o/r merge 5"),
                          ("gh pr -Ro/r merge 5", "gh pr -Ro/r merge 5"), ("%s/gh pr merge 5 --auto" % self.bin, "%s/gh pr merge 5 --auto" % self.bin)):
            with self.subTest(cmd):
                self.assertEqual(self.run_plan(cmd).flat, flat)


class LiteralSingleArgument(Env):
    def test_plain_words_and_quotes_split_into_an_argument_list(self):
        for cmd, argv in (
            ("touch a.flag", ["touch", "a.flag"]),
            ("echo 'a  b' \"c d\"", ["echo", "a  b", "c d"]),
            ("echo 'it'\"'\"'s'", ["echo", "it's"]),
            ("echo a'b'\"c\"", ["echo", "abc"]),
            ("  echo   x\ty ", ["echo", "x", "y"]),
            ("echo ''", ["echo", ""]),
            ("echo 'a;b|c&d<e>f$g`h*i?j[k'", ["echo", "a;b|c&d<e>f$g`h*i?j[k"]),
            ('echo "a;b|c&d<e>f*g?h[i{j}k(l)m#n~o"', ["echo", "a;b|c&d<e>f*g?h[i{j}k(l)m#n~o"]),
            ("echo 'two\nlines'", ["echo", "two\nlines"]),
            ("echo a#b", ["echo", "a#b"]),
            ("echo a=b", ["echo", "a=b"]),
            ("echo -n x", ["echo", "-n", "x"]),
        ):
            with self.subTest(cmd):
                self.assertEqual(self.argv(cmd), argv)

    def test_every_expansion_and_operator_is_refused_with_its_name(self):
        for cmd in (
            "echo $HOME", "echo ${HOME}", "echo $(date)", "echo `date`", 'echo "$HOME"', 'echo "`date`"',
            'echo "$(date)"', "echo $'a'", 'echo $"a"', "echo $((1+1))",
            "echo a; echo b", "echo a && echo b", "echo a || echo b", "echo a | cat", "echo a & ",
            "echo a > f", "echo a >> f", "echo a < f", "echo <(date)", "echo >(cat)", "echo a 2>&1",
            "cat <<EOF\nx\nEOF", "cat <<< x", "echo a\necho b", "echo a\r", "echo a\vb",
            "echo *", "echo ?", "echo [a]", "echo a*", "echo ~", "echo ~root", "echo {a,b}", "echo {1..3}",
            "echo (a)", "( echo a )", "{ echo a; }", "# a comment", "echo a #b", "echo \\a", 'echo "a\\"b"',
            "echo 'unterminated", 'echo "unterminated', "", "   ", "echo a\x00b",
            "FOO=bar echo a", "!echo a", "echo !a ; x",
        ):
            with self.subTest(cmd):
                e = self.refused(cmd)
                self.assertEqual(e.exit, 5)

    def test_what_a_shell_would_have_expanded_is_never_expanded_here(self):
        # quoted, it is the word it looks like; the reviewer reads those exact bytes
        self.assertEqual(self.argv("echo '$HOME' '$(date)' '`x`'"), ["echo", "$HOME", "$(date)", "`x`"])

    def test_several_arguments_are_taken_exactly_as_they_are(self):
        self.assertEqual(self.argv("echo", "$HOME", "a b", "*", "x;y"), ["echo", "$HOME", "a b", "*", "x;y"])

    def test_a_relative_program_path_is_refused(self):
        for argv in (["./run.sh"], ["scripts/run.sh", "x"], ["../x"]):
            with self.subTest(argv):
                self.assertIn("path", self.refused(*argv).name)

    def test_an_empty_argument_list_is_refused(self):
        self.refused(*[], single=False)


class ProgramsThatRunAnotherCommand(Env):
    NAMES = ("bash sh zsh dash ksh fish csh tcsh env eval exec command builtin xargs find time nice "
             "nohup timeout sudo su doas watch script parallel make python python3 python3.12 perl perl5 "
             "ruby node nodejs deno php lua luajit awk gawk mawk sed osascript ssh scp sftp mosh "
             "setsid flock ionice taskset stdbuf chroot unshare nsenter runuser pkexec systemd-run "
             "tmux screen at batch crontab busybox expect socat nc ncat netcat telnet strace gdb "
             "vi vim nvim nano emacs ed ex less more man claude codex gemini npx npm pnpm yarn bun uv uvx "
             "pipx pip cargo go java tclsh bc rlwrap entr").split()

    def test_each_is_refused_by_name_with_exit_5(self):
        for name in self.NAMES:
            with self.subTest(name):
                e = self.refused(name, "x")
                self.assertEqual(e.exit, 5)
                self.assertIn("runs another command", e.name)

    def test_by_absolute_path_and_by_symlink_too(self):
        real = argv_gate.shutil.which("bash")
        self.assertIn("runs another command", self.refused(real, "-c", "true").name)
        link = self.tmp / "harmless"
        link.symlink_to(real)
        self.assertIn("runs another command", self.refused(str(link), "-c", "true").name)

    def test_a_name_is_not_a_prefix_match(self):
        for ok in ("makeit", "cpython-notes", "echo", "nicely"):
            with self.subTest(ok):
                self.assertEqual(self.argv(ok, "x"), [ok, "x"])


class Git(Env):
    def test_plain_git_arguments_pass(self):
        for argv in (["git", "status", "--short"], ["git", "-C", str(self.work), "log", "--oneline", "-3"],
                     ["git", "commit", "-m", "x"], ["git", "push", "origin", "fix/53b"],
                     ["git", "diff", "origin/main...HEAD"], ["git", "worktree", "add", "../x", "-b", "y"],
                     ["git", "--no-pager", "log"], ["git", "config", "user.email", "a@b"],
                     ["git", "cherry-pick", "-x", "abc"], ["git", "push", "-u", "origin", "fix/x"]):
            with self.subTest(argv):
                self.assertEqual(self.argv(*argv), argv)

    def test_overrides_that_run_programs_are_refused(self):
        for argv in (["git", "-c", "alias.x=!gh pr merge 5", "x"], ["git", "-c", "core.pager=sh", "log"],
                     ["git", "-ccore.pager=sh", "log"], ["git", "--config-env=core.pager=X", "log"],
                     ["git", "--exec-path=/tmp/x", "log"], ["git", "--paginate", "log"],
                     ["git", "config", "core.fsmonitor", "gh pr merge 5"],
                     ["git", "config", "--global", "alias.m", "!gh pr merge"],
                     ["git", "config", "pager.log", "sh"], ["git", "config", "-e"],
                     ["git", "config", "--edit"], ["git", "config", "include.path", "/tmp/x"],
                     ["git", "config", "core.hooksPath", "/tmp/h"], ["git", "config", "credential.helper", "!sh"],
                     ["git", "--unknown-option", "log"]):
            with self.subTest(argv):
                self.refused(*argv)

    def test_subcommands_and_options_that_run_programs_are_refused(self):
        for argv in (["git", "rebase", "--exec", "gh pr merge 5", "main"], ["git", "rebase", "-x", "true"],
                     ["git", "rebase", "--exec=true"], ["git", "bisect", "run", "sh"],
                     ["git", "submodule", "foreach", "gh pr merge 5"], ["git", "difftool"], ["git", "mergetool"],
                     ["git", "filter-branch"], ["git", "help", "log"], ["git", "instaweb"],
                     ["git", "fetch", "--upload-pack=sh", "origin"], ["git", "push", "--receive-pack=sh", "o"],
                     ["git", "clone", "ext::sh -c true", "x"], ["git", "ls-remote", "ext::sh", "x"],
                     ["git", "clone", "-u", "sh", "o"]):
            with self.subTest(argv):
                self.refused(*argv)

    def test_a_git_alias_in_the_config_is_refused_in_any_case(self):
        subprocess.run(["git", "config", "alias.mm", "!gh pr merge 5"], cwd=self.work, env=self.env, check=True)
        for sub in ("mm", "MM"):
            with self.subTest(sub):
                self.assertIn("alias", self.refused("git", sub).name)
        self.assertIn("alias", self.refused("git", "-C", str(self.work), "mm").name)

    def test_the_alias_probe_reads_the_repository_the_command_will_use(self):
        other = self.tmp / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True, env=self.env)
        subprocess.run(["git", "config", "alias.mm", "!gh pr merge 5"], cwd=other, env=self.env, check=True)
        for argv in (["git", "--git-dir=%s/.git" % other, "mm"], ["git", "--git-dir", "%s/.git" % other, "mm"],
                     ["git", "--work-tree=%s" % other, "--git-dir=%s/.git" % other, "mm"]):
            with self.subTest(argv):
                self.assertIn("alias", self.refused(*argv).name)

    def test_a_git_that_cannot_report_its_aliases_refuses(self):
        e = self.refused("git", "-C", str(self.tmp / "no-such-dir"), "status")
        self.assertIn("alias", e.name)

    def test_git_global_options_do_not_hide_the_push_rule(self):
        self.assertEqual(self.run_plan("git", "-C", str(self.work), "push", "origin", "main").flat,
                         "git push origin main")


class Gh(Env):
    def test_normal_boss_usage_passes(self):
        for argv in (["gh", "pr", "comment", "5", "--body-file", "/tmp/x.md"],
                     ["gh", "pr", "create", "--title", "t", "--body-file", "b.md"],
                     ["gh", "pr", "view", "5", "--json", "state"], ["gh", "pr", "close", "5", "--comment", "x"],
                     ["gh", "api", "repos/o/r/pulls/5"], ["gh", "api", "repos/o/r/commits/abc/check-runs", "-q", ".total_count"],
                     ["gh", "api", "repos/o/r/issues/5/comments", "-f", "body=hi"],
                     ["gh", "api", "-X", "PATCH", "repos/o/r/pulls/5", "-f", "state=closed"],
                     ["gh", "--version"], ["gh", "run", "list"]):
            with self.subTest(argv):
                self.assertEqual(self.argv(*argv), argv)

    def test_gh_extension_is_refused_except_to_look(self):
        for sub in ("install", "exec", "upgrade", "remove", "create"):
            with self.subTest(sub):
                self.assertIn("extension", self.refused("gh", "extension", sub, "x").name)
        self.assertEqual(self.argv("gh", "extension", "list"), ["gh", "extension", "list"])

    def test_gh_codespace_and_an_option_before_the_subcommand_are_refused(self):
        for argv in (["gh", "codespace", "ssh", "--", "gh pr merge 5"], ["gh", "cs", "ssh"],
                     ["gh", "-R", "o/r", "pr", "view"], ["gh"]):
            with self.subTest(argv):
                self.refused(*argv)

    def test_a_graphql_body_that_cannot_be_read_is_refused(self):
        for argv in (["gh", "api", "graphql", "-F", "query=@q.graphql"], ["gh", "api", "graphql", "--input", "q.json"],
                     ["gh", "api", "graphql", "-f", "query=@q.graphql"]):
            with self.subTest(argv):
                self.refused(*argv)

    def test_a_graphql_query_read_from_the_arguments_passes(self):
        argv = ["gh", "api", "graphql", "-f", "query={ viewer { login } }"]
        self.assertEqual(self.argv(*argv), argv)

    def test_a_merge_endpoint_is_refused_in_every_spelling_gh_api_can_send(self):
        for argv in (["gh", "api", "repos/o/r/pulls/5/merge", "--method", "PUT"],
                     ["gh", "api", "repos/o/r/pulls/5/merge", "-X", "put"],
                     ["gh", "api", "repos/o/r/pulls/5/merge"],
                     ["gh", "api", "repos/o/r/pulls/5/./merge", "-X", "PUT"],
                     ["gh", "api", "repos/o/r/pulls/5//merge", "-X", "PUT"],
                     ["gh", "api", "repos/o/r/merges", "-f", "base=main", "-f", "head=x"],
                     ["gh", "api", "repos/o/r/pulls/5/%6derge", "-X", "PUT"],
                     ["gh", "api", "graphql", "-f", "query=mutation{mergePullRequest(input:{})}"],
                     ["gh", "api", "graphql", "-f", "query=mutation{enablePullRequestAutoMerge(input:{})}"]):
            with self.subTest(argv):
                self.refused(*argv)


class ProgramsThatHideTheirRequest(Env):
    """Codex, PR 150 round 1: curl reads .curlrc, -K files, `-Kfile`, `--config=file` and expands
    {a,b}; wget -i reads URLs from a file; GNU tar takes `-I=cmd`. Their options hide what they do in
    more ways than a list closes, so they are refused by name, whatever the arguments."""

    def test_each_is_refused_whatever_the_arguments(self):
        for argv in (["curl", "https://api.github.com/repos/o/r/pulls/5/mer{g,g}e", "-X", "PUT"],
                     ["curl", "-Kc.cfg"], ["curl", "--config=c.cfg"], ["curl", "-s", "https://x/y"],
                     ["curl", "--variable", "a=merge", "--expand-url", "https://x/pulls/5/{{a}}"],
                     ["wget", "--method=PUT", "-i", "urls.txt"], ["wget", "-q", "https://x/y"],
                     ["tar", "-I=sh /tmp/payload", "-xf", "x"], ["tar", "-Ish", "x"], ["tar", "tf", "x.tar"],
                     ["rsync", "-e", "sh", "a", "b"], ["rsync", "-a", "a/", "b/"], ["zip", "-T", "x"],
                     ["http", "PUT", "https://x/pulls/5/merge"], ["xh", "https://x"]):
            with self.subTest(argv):
                e = self.refused(*argv)
                self.assertIn("does not show", e.name)


class OtherUsage(Env):
    def test_normal_boss_usage_passes(self):
        for argv in (["cp", "a.md", "b.md"], ["mkdir", "-p", "x/y"], ["systemctl", "--user", "status", "foo.service"],
                     ["ls", "-la"], ["cat", "x"], ["jq", ".a", "x.json"], ["touch", "x"], ["grep", "-rn", "x", "."],
                     ["rg", "-n", "x"], ["date", "-Is"], ["head", "-5", "x"]):
            with self.subTest(argv):
                self.assertEqual(self.argv(*argv), argv)

    def test_options_that_run_programs_are_refused(self):
        for argv in (["rg", "--pre", "sh", "x"], ["rg", "--pre=sh", "x"], ["rg", "--hostname-bin", "sh", "x"],
                     ):
            with self.subTest(argv):
                self.refused(*argv)


class Plan(Env):
    def test_the_display_is_the_argument_list_quoted_so_it_can_be_read_back(self):
        p = self.run_plan("echo", "a b", "it's", "$HOME", "")
        self.assertEqual(p.display, "echo 'a b' 'it'\"'\"'s' '$HOME' ''")

    def test_the_rule_text_is_the_literal_argument_list_joined_with_single_spaces(self):
        self.assertEqual(self.run_plan("git  'push'   origin 'ma'in").flat, "git push origin main")


class CommandLine(Env):
    """The helper as boss-run calls it: JSON on stdout, exit 0 or 1."""

    def call(self, *args):
        env = dict(self.env)
        return subprocess.run([sys.executable, "-I", str(GATE), "--cwd", str(self.work), *args],
                              capture_output=True, text=True, env=env)

    def test_an_accepted_single_argument_prints_the_argument_list(self):
        r = self.call("--single", "--", "touch 'a b'")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "argv": ["touch", "a b"], "flat": "touch a b",
                                                "display": "touch 'a b'"})

    def test_a_refusal_prints_the_rule_and_exits_1(self):
        r = self.call("--single", "--", "echo $HOME")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("literal", out["rule"])
        self.assertTrue(out["detail"])

    def test_a_list_is_taken_as_it_is(self):
        r = self.call("--", "echo", "$HOME")
        self.assertEqual(json.loads(r.stdout)["argv"], ["echo", "$HOME"])

    def test_a_crash_is_not_an_answer(self):
        r = subprocess.run([sys.executable, "-I", str(GATE), "--no-such-flag"], capture_output=True, text=True)
        self.assertNotIn(r.returncode, (0, 1))


if __name__ == "__main__":
    unittest.main()
