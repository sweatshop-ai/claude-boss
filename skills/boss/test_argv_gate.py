#!/usr/bin/env python3
"""Tests for argv_gate.py: the allowlist boss-run puts in front of the reviewer (ticket 53b).

Run: python3 skills/boss/test_argv_gate.py

boss-run runs only what it can see completely: an argument list, never a shell string, and
only programs on a short list (the ones the 714 approved commands of the log used, 2026-11-13).
Everything else is refused before a reviewer sees it. A boss that needs a script dispatches it
to a worker.
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
from argv_gate import Refused, plan, prepare  # noqa: E402

GATE = HERE / "argv_gate.py"


def refused(args, single=None):
    try:
        plan(list(args), single=(len(args) == 1) if single is None else single)
    except Refused as e:
        return e
    return None


class CodexBypasses(unittest.TestCase):
    """The twelve findings of PR 148 (rounds 1 to 3) and the nine of PR 150's round 2. Each is refused
    before a reviewer sees it, none is read."""

    PR148 = [
        """env -S '"gh" pr merge 5'""", """flock /tmp/x -c '"gh" pr merge 5'""", """script -qc '"gh" pr merge 5' /dev/null""",
        "watch -n1 gh pr merge 5", """time -p sh -c '"gh" pr merge 5'""", """coproc JOB sh -c '"gh" pr merge 5'""",
        "BASH_ENV=/tmp/unseen bash -c true", "bash --rcfile /tmp/unseen -ic true", 'env --split-string="$X"',
        """"curl" -X "PUT" https://api.github.com/repos/o/r/pulls/5/merge""",
        "x=\"$(printf '\\\\$(gh pr merge 5)')\"; echo ${x@P}",
        """GH=g'h'; export GH; find . -maxdepth 0 -exec sh -c true \\; -exec "$GH" pr m'er'ge 5 \\;""",
        "gh alias set m 'pr merge'; gh m 5",
    ]
    PR150_ROUND2 = [
        ["-a", "x", "/bin/bash", "-c", "gh pr merge 5"], ["-l", "/bin/sh", "-c", "true"],
        ["git", "rebase", "--exe", "gh pr merge 5", "main"], ["git", "fetch", "--upload-pa=sh", "origin"],
        ["git", "push", "--receive-p=sh", "o"], ["git", "rebase", "-mx", "gh pr merge 5", "main"],
        ["git", "clone", "-ush", "url", "dst"], ["git", "grep", "-Ocmd", "x"],
        ["git", "grep", "--open-files-in-pager=cmd", "x"],
        ["/usr/lib/git-core/git-push", "origin", "main"], ["git-push", "origin", "main"], ["git-rebase", "-i"],
        ["hub", "pr", "merge", "5"], ["/tmp/hub", "pr", "merge", "5"],
        ["git", "fetch", "-c", "remote.o.uploadpack=sh", "o"], ["git", "clone", "-c", "core.hooksPath=/x", "u"],
        ["git", "config", "remote.o.uploadpack", "sh"], ["git", "remote", "add", "o", "ext::sh -c true"],
        ["/lib64/ld-linux-x86-64.so.2", "/bin/bash", "-c", "true"], ["x", "-c", "true"],
        ["ssh-agent", "sh"], ["sqlite3", "db", ".shell id"], ["psql", "-c", "\\! id"], ["nix-shell", "--run", "id"],
        ["pwsh", "-c", "id"], ["fakeroot", "sh"], ["bwrap", "sh"], ["xterm", "-e", "sh"],
    ]

    def test_every_pr148_finding_is_refused(self):
        for cmd in self.PR148:
            with self.subTest(cmd):
                self.assertIsNotNone(refused([cmd]))

    def test_every_pr150_round2_finding_is_refused(self):
        for argv in self.PR150_ROUND2:
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_gh_pr_merge_in_every_literal_spelling_is_refused_as_a_merge(self):
        for cmd in ('"gh" pr merge 5', "gh pr 'merge' 5", "g'h' pr m'er'ge 5", "gh pr --repo o/r merge 5",
                    "gh pr -Ro/r merge 5", "gh pr -R=o/r merge 5", "gh pr --repo= merge 5", "gh pr merge 5 --auto",
                    "gh pr -R o/r -Ro/r merge 5", "gh pr --repo o/r -Ro/r --repo=o/r merge 5"):
            with self.subTest(cmd):
                self.assertEqual(refused([cmd]).name, "PR merge outside boss_merge")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="argv-gate-")).resolve()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.cfg = self.tmp / "cfg"
        self.cfg.mkdir()
        (self.cfg / argv_gate.TRUSTED_FILE).write_text("%s\n" % self.bin)
        self.work = self.tmp / "work"
        self.work.mkdir()

    def program(self, name, body="exit 0"):
        path = self.bin / name
        path.write_text("#!/bin/sh\n%s\n" % body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def prepare(self, argv, cfg=None, env=None):
        return prepare(argv, str(cfg or self.cfg), str(self.work), env=env)

    def prepare_refused(self, argv):
        with self.assertRaises(Refused) as cm:
            self.prepare(argv)
        return cm.exception


class LiteralSingleArgument(unittest.TestCase):
    def argv(self, cmd):
        return plan([cmd], single=True).argv

    def test_plain_words_and_quotes_split_into_an_argument_list(self):
        for cmd, argv in (
            ("touch a.flag", ["touch", "a.flag"]),
            ("cat 'a  b' \"c d\"", ["cat", "a  b", "c d"]),
            ("cat 'it'\"'\"'s'", ["cat", "it's"]),
            ("cat a'b'\"c\"", ["cat", "abc"]),
            ("  cat   x\ty ", ["cat", "x", "y"]),
            ("cat ''", ["cat", ""]),
            ("cat 'a;b|c&d<e>f$g`h*i?j[k'", ["cat", "a;b|c&d<e>f$g`h*i?j[k"]),
            ('cat "a;b|c&d<e>f*g?h[i{j}k(l)m#n~o"', ["cat", "a;b|c&d<e>f*g?h[i{j}k(l)m#n~o"]),
            ("cat 'two\nlines'", ["cat", "two\nlines"]),
            ("cat a#b", ["cat", "a#b"]),
            ("cat a=b", ["cat", "a=b"]),
            ("head -n 5 x", ["head", "-n", "5", "x"]),
        ):
            with self.subTest(cmd):
                self.assertEqual(self.argv(cmd), argv)

    def test_every_expansion_and_operator_is_refused_with_its_name(self):
        for cmd in (
            "cat $HOME", "cat ${HOME}", "cat $(date)", "cat `date`", 'cat "$HOME"', 'cat "`date`"',
            'cat "$(date)"', "cat $'a'", 'cat $"a"', "cat $((1+1))",
            "cat a; cat b", "cat a && cat b", "cat a || cat b", "cat a | cat", "cat a & ",
            "cat a > f", "cat a >> f", "cat a < f", "cat <(date)", "cat >(cat)", "cat a 2>&1",
            "cat <<EOF\nx\nEOF", "cat <<< x", "cat a\ncat b", "cat a\r", "cat a\vb",
            "cat *", "cat ?", "cat [a]", "cat a*", "cat ~", "cat ~root", "cat {a,b}", "cat {1..3}",
            "cat (a)", "( cat a )", "{ cat a; }", "# a comment", "cat a #b", "cat \\a", 'cat "a\\"b"',
            "cat 'unterminated", 'cat "unterminated', "", "   ", "cat a\x00b", "!cat a", "cat !a ; x",
        ):
            with self.subTest(cmd):
                e = refused([cmd])
                self.assertIsNotNone(e)
                self.assertEqual(e.exit, 5)

    def test_a_dollar_in_single_quotes_is_the_word_it_looks_like(self):
        self.assertEqual(self.argv("cat '$HOME' '$(date)' '`x`'"), ["cat", "$HOME", "$(date)", "`x`"])

    def test_several_arguments_are_taken_exactly_as_they_are(self):
        self.assertEqual(plan(["cat", "$HOME", "a b", "*", "x;y"], single=False).argv, ["cat", "$HOME", "a b", "*", "x;y"])

    def test_an_argument_that_is_not_utf8_is_refused(self):
        self.assertIn("not text", refused(["cat", "a\udcffb"], single=False).name)

    def test_an_empty_argument_list_is_refused(self):
        self.assertIsNotNone(refused([], single=False))


class OnlyThePrograms(unittest.TestCase):
    ON_LIST = "gh git cp mv mkdir touch rm ls cat head tail jq grep rg date systemctl".split()

    def test_the_list_is_exactly_what_the_log_needs(self):
        self.assertEqual(sorted(argv_gate.PROGRAMS), sorted(self.ON_LIST))

    def test_every_program_off_the_list_is_refused_by_name_with_exit_5(self):
        names = ("bash sh zsh dash ksh fish csh env eval exec command builtin xargs find time nice nohup timeout sudo su doas "
                 "watch script parallel make python python3 python3.12 perl ruby node deno php lua awk gawk mawk sed ed ex "
                 "osascript ssh scp sftp mosh setsid flock ionice taskset stdbuf chroot unshare nsenter runuser pkexec "
                 "systemd-run tmux screen at batch crontab busybox expect socat nc ncat telnet strace gdb vi vim nvim nano "
                 "emacs less more man claude codex gemini npx npm pnpm yarn bun uv uvx pipx pip cargo go java tclsh bc "
                 "curl wget http xh tar rsync zip unzip docker psql sqlite3 sleep echo printf test true false tee dd ln "
                 "chmod chown install xxd base64 sort uniq wc cut tr diff patch ar cpio coproc editorconfig-checker virsh").split()
        for name in names:
            with self.subTest(name):
                e = refused([name, "x"], single=False)
                self.assertEqual(e.exit, 5)
                self.assertIn(e.name, (argv_gate.NOT_ON_LIST, "program given by path or by an odd name"))

    def test_a_program_given_by_path_or_an_odd_name_is_refused_even_when_its_name_is_on_the_list(self):
        for name in ("/usr/bin/git", "/bin/ls", "./gh", "../ls", "bin/cat", "-a", "-l", "FOO=bar", "GH", "Git", "gh ", "git-push", ""):
            with self.subTest(name):
                self.assertIsNotNone(refused([name, "x"], single=False))

    def test_every_program_on_the_list_with_ordinary_arguments_is_accepted(self):
        for argv in (["cp", "a.md", "b.md"], ["mv", "a", "b"], ["mkdir", "-p", "x/y"], ["touch", "x"], ["rm", "x.tmp"],
                     ["ls", "-la"], ["cat", "x"], ["head", "-5", "x"], ["tail", "-n", "20", "x"], ["jq", ".a", "x.json"],
                     ["grep", "-rn", "x", "."], ["rg", "-n", "x"], ["date", "-Is"],
                     ["systemctl", "--user", "status", "foo.service"], ["systemctl", "show", "foo.service", "-p", "ActiveState"]):
            with self.subTest(argv):
                self.assertEqual(plan(argv, single=False).argv, argv)


class Git(unittest.TestCase):
    def test_the_common_forms_of_the_log_pass(self):
        for argv in (["git", "worktree", "add", "../x", "-b", "y"], ["git", "worktree", "remove", "../x"],
                     ["git", "worktree", "list"], ["git", "push", "origin", "fix/53b"], ["git", "push", "-u", "origin", "fix/x"],
                     ["git", "-C", "/some/dir", "status", "--short"], ["git", "-C", "/some/dir", "log", "--oneline", "-3"],
                     ["git", "merge", "origin/main"], ["git", "merge", "--no-ff", "-m", "x", "dev"], ["git", "commit", "-m", "x"],
                     ["git", "commit", "-a", "-m", "x"], ["git", "branch", "-d", "x"], ["git", "pull", "--ff-only"],
                     ["git", "add", "a.py", "b.py"], ["git", "restore", "--staged", "a.py"], ["git", "fetch", "origin"],
                     ["git", "diff", "origin/main...HEAD", "--stat"], ["git", "show", "HEAD:a.py"], ["git", "rev-parse", "HEAD"],
                     ["git", "--no-pager", "log"], ["git", "log", "--format=%h %s", "-5"], ["git", "diff", "--name-only"]):
            with self.subTest(argv):
                self.assertEqual(plan(argv, single=False).argv, argv)

    def test_a_subcommand_off_the_list_is_refused(self):
        for sub in ("rebase", "clone", "config", "checkout", "switch", "reset", "clean", "stash", "remote", "bisect",
                    "submodule", "difftool", "mergetool", "filter-branch", "help", "grep", "cherry-pick", "tag", "rm", "mv",
                    "archive", "gc", "init", "ls-remote", "send-email", "daemon", "instaweb", "credential", "alias"):
            with self.subTest(sub):
                self.assertIn("subcommand not on boss-run's list", refused(["git", sub, "x"], single=False).name)

    def test_options_before_the_subcommand_other_than_C_are_refused(self):
        for argv in (["git", "-c", "alias.x=!gh pr merge 5", "status"], ["git", "-c", "core.pager=sh", "log"],
                     ["git", "-ccore.pager=sh", "log"], ["git", "--config-env=core.pager=X", "log"],
                     ["git", "--config-env", "core.pager=X", "log"], ["git", "--exec-path=/tmp/x", "log"],
                     ["git", "--paginate", "log"], ["git", "--git-dir=/x", "status"], ["git", "--work-tree=/x", "status"],
                     ["git", "-C"], ["git", "-C", "-c", "status"], ["git", "-p", "log"], ["git"], ["git", "--unknown", "log"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_options_that_run_a_program_are_refused_in_every_spelling(self):
        for argv in (["git", "fetch", "--upload-pack=sh", "origin"], ["git", "fetch", "--upload-pa=sh", "origin"],
                     ["git", "fetch", "--upload-pack", "sh", "origin"], ["git", "pull", "--upload-pack=sh"],
                     ["git", "push", "--receive-pack=sh", "o"], ["git", "push", "--receive-p=sh", "o"],
                     ["git", "push", "--exec=sh", "o"], ["git", "push", "--exe=sh", "o"],
                     ["git", "merge", "-s", "foo", "x"], ["git", "merge", "-sfoo", "x"], ["git", "merge", "-ksfoo", "x"],
                     ["git", "merge", "--strategy=foo", "x"], ["git", "merge", "--strat=foo", "x"],
                     ["git", "diff", "--output=/tmp/x"], ["git", "log", "--out=/tmp/x"],
                     ["git", "fetch", "ext::sh -c true"], ["git", "push", "ext::sh", "main:x"], ["git", "pull", "ext::sh"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_options_that_look_alike_but_are_ordinary_pass(self):
        for argv in (["git", "diff", "--stat"], ["git", "log", "--stat", "--oneline"], ["git", "diff", "--exit-code"],
                     ["git", "log", "--exclude=x"], ["git", "merge", "--squash", "x"], ["git", "commit", "--signoff", "-m", "x"],
                     ["git", "push", "--set-upstream", "origin", "x"], ["git", "status", "-sb"], ["git", "log", "-s"]):
            with self.subTest(argv):
                self.assertEqual(plan(argv, single=False).argv, argv)

    def test_git_C_dir_does_not_hide_the_push_rule(self):
        self.assertEqual(plan(["git", "-C", "/x", "push", "origin", "main"], single=False).flat, "git push origin main")
        self.assertEqual(plan(["git", "--no-pager", "-C", "/x", "push", "origin", "main"], single=False).flat, "git push origin main")


class Gh(unittest.TestCase):
    def test_the_common_forms_of_the_log_pass(self):
        for argv in (["gh", "pr", "comment", "5", "--body-file", "/tmp/x.md"], ["gh", "pr", "comment", "5", "--body", "merge when green"],
                     ["gh", "pr", "create", "--title", "t", "--body-file", "b.md", "--base", "dev"],
                     ["gh", "pr", "view", "5", "--json", "state"], ["gh", "pr", "list", "--state", "open"],
                     ["gh", "pr", "checks", "5", "--repo", "o/r"], ["gh", "pr", "-Ro/r", "view", "5"], ["gh", "pr", "-R", "o/r", "view", "5"],
                     ["gh", "pr", "--repo=o/r", "diff", "5"], ["gh", "pr", "close", "5", "--comment", "x"], ["gh", "pr", "edit", "5", "--title", "t"],
                     ["gh", "issue", "view", "5"], ["gh", "issue", "list"], ["gh", "issue", "comment", "5", "--body-file", "x.md"],
                     ["gh", "run", "list"], ["gh", "run", "view", "5"], ["gh", "run", "watch", "5"], ["gh", "workflow", "run", "x.yml"],
                     ["gh", "label", "list"], ["gh", "repo", "view", "o/r"],
                     ["gh", "api", "repos/o/r/pulls/5"], ["gh", "api", "repos/o/r/commits/abc/check-runs", "-q", ".total_count"],
                     ["gh", "api", "repos/o/r/issues/5/comments", "-f", "body=hi"],
                     ["gh", "api", "-X", "PATCH", "repos/o/r/pulls/5", "-f", "state=closed"],
                     ["gh", "api", "graphql", "-f", "query={ viewer { login } }"], ["gh", "--version"]):
            with self.subTest(argv):
                self.assertEqual(plan(argv, single=False).argv, argv)

    def test_a_subcommand_off_the_list_is_refused(self):
        for argv in (["gh", "alias", "set", "m", "pr merge"], ["gh", "extension", "install", "x/y"], ["gh", "ext", "exec", "x"],
                     ["gh", "codespace", "ssh"], ["gh", "cs", "ssh"], ["gh", "copilot"], ["gh", "agent-task"], ["gh", "auth", "login"],
                     ["gh", "config", "set", "editor", "sh"], ["gh", "gist", "create", "x"], ["gh", "release", "create", "v1"],
                     ["gh", "repo", "delete", "o/r"], ["gh", "repo", "clone", "o/r"], ["gh", "repo", "edit", "o/r"],
                     ["gh", "pr", "revert", "5"], ["gh", "issue", "delete", "5"], ["gh", "run", "download", "5"],
                     ["gh", "co", "5"], ["gh", "-R", "o/r", "pr", "view"], ["gh"], ["gh", "pr"], ["gh", "pr", "--help"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_a_merge_is_refused_in_every_spelling_gh_api_can_send(self):
        for argv in (["gh", "api", "repos/o/r/pulls/5/merge", "--method", "PUT"], ["gh", "api", "repos/o/r/pulls/5/merge", "-X", "put"],
                     ["gh", "api", "repos/o/r/pulls/5/merge"], ["gh", "api", "repos/o/r/pulls/5/merge", "--method", "GET"],
                     ["gh", "api", "repos/o/r/pulls/5/./merge", "-X", "PUT"], ["gh", "api", "repos/o/r/pulls/5//merge", "-X", "PUT"],
                     ["gh", "api", "repos/o/r/merges", "-f", "base=main", "-f", "head=x"],
                     ["gh", "api", "repos/o/r/pulls/5/%6derge", "-X", "PUT"],
                     ["gh", "api", "graphql", "-f", "query=mutation{mergePullRequest(input:{})}"],
                     ["gh", "api", "graphql", "-f", "query=mutation{enablePullRequestAutoMerge(input:{})}"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_a_graphql_body_that_cannot_be_read_is_refused(self):
        for argv in (["gh", "api", "graphql", "-F", "query=@q.graphql"], ["gh", "api", "graphql", "--input", "q.json"],
                     ["gh", "api", "graphql", "-f", "query=@q.graphql"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_the_hard_rule_text_is_the_literal_list_with_quotes_gone(self):
        self.assertEqual(plan(["g'h' pr 'view' 5"], single=True).flat, "gh pr view 5")


class FileAndOtherPrograms(unittest.TestCase):
    def test_systemctl_only_status_and_show(self):
        for argv in (["systemctl", "restart", "x"], ["systemctl", "--user", "restart", "x"], ["systemctl", "stop", "x"],
                     ["systemctl", "start", "x"], ["systemctl", "edit", "x"], ["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "kill", "x"], ["systemctl"], ["systemctl", "--user"], ["systemctl", "status", "-H", "host", "x"],
                     ["systemctl", "status", "--host=h", "x"], ["systemctl", "status", "-M", "m", "x"],
                     ["systemctl", "--user", "--now", "status", "x"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))

    def test_the_file_programs_do_not_write_where_code_or_trust_lives(self):
        for argv in (["cp", "x", "repo/.git/config"], ["cp", "x", ".git/hooks/pre-commit"], ["mv", "x", "r/.git/hooks/pre-commit"],
                     ["touch", "/h/.bashrc"], ["cp", "x", "/h/.ssh/authorized_keys"], ["cp", "x", "/h/.config/gh/hosts.yml"],
                     ["cp", "x", "/h/.config/systemd/user/x.service"], ["mkdir", "-p", "repo/hooks"], ["rm", "-f", "repo/.git/index.lock"],
                     ["cp", "x", "/c/boss-run-trusted-path"], ["cp", "x", "/c/boss-hard-rules.tsv"], ["cp", "x", "/h/.gitconfig"],
                     ["cp", "x", "r/.githooks/pre-commit"], ["cp", "x", "/h/.zshrc"], ["mv", "/h/.profile", "x"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))
        for argv in (["cp", "a.md", "b.md"], ["mkdir", "-p", "out/dir"], ["touch", "x.flag"], ["rm", "a.tmp"],
                     ["cp", "-r", "gitroot", "copy"], ["cp", "x", "docs/hooks-explained.md"]):
            with self.subTest(argv):
                self.assertIsNone(refused(argv, single=False))

    def test_rg_options_that_run_a_program_are_refused(self):
        for argv in (["rg", "--pre", "sh", "x"], ["rg", "--pre=sh", "x"], ["rg", "--hostname-bin", "sh", "x"]):
            with self.subTest(argv):
                self.assertIsNotNone(refused(argv, single=False))


class Resolution(Fixture):
    def test_the_program_runs_as_the_absolute_path_found_in_a_trusted_directory(self):
        gh = self.program("gh")
        self.assertEqual(self.prepare(["gh", "pr", "view", "5"]), [str(gh), "pr", "view", "5"])

    def test_path_is_not_consulted(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "gh").write_text("#!/bin/sh\nexit 0\n")
        (elsewhere / "gh").chmod(0o755)
        self.program("gh")
        env = {"PATH": "%s:%s" % (elsewhere, self.bin)}
        self.assertEqual(self.prepare(["gh", "pr", "view", "5"], env=env)[0], str(self.bin / "gh"))

    def test_a_program_found_nowhere_trusted_is_refused(self):
        self.assertIn("not found", self.prepare_refused(["jq-not-here"]).name)

    def test_a_link_in_a_trusted_directory_that_leads_out_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        target = outside / "real"
        target.write_text("#!/bin/sh\nexit 0\n")
        target.chmod(0o755)
        (self.bin / "gh").symlink_to(target)
        self.assertIn("outside the trusted", self.prepare_refused(["gh", "pr", "view", "5"]).name)

    def test_the_default_directories_resolve_the_programs_of_this_machine(self):
        for name in ("ls", "cat", "cp", "git"):
            with self.subTest(name):
                self.assertTrue(self.prepare([name], cfg=self.tmp / "no-cfg")[0].startswith("/"))

    def test_a_gh_alias_the_gh_reports_is_refused_whatever_it_expands_to(self):
        for expansion in ("pr merge", "pr \\u006derge", "!gh pr merge"):
            with self.subTest(expansion):
                self.program("gh", 'if [ "$1" = alias ]; then printf "m: %s\\nco: pr checkout\\n"; fi' % expansion)
                self.assertIn("alias", self.prepare_refused(["gh", "m", "5"]).name)

    def test_a_gh_that_cannot_report_its_aliases_is_refused_and_one_that_can_passes(self):
        self.program("gh", "echo boom >&2; exit 4")
        self.assertIn("alias", self.prepare_refused(["gh", "pr", "view", "5"]).name)
        self.program("gh", 'printf "co: pr checkout\\n"')
        self.assertEqual(self.prepare(["gh", "pr", "view", "5"])[1:], ["pr", "view", "5"])


class CommandLine(Fixture):
    def call(self, *args):
        return subprocess.run([sys.executable, "-I", str(GATE), "--cwd", str(self.work), "--config-dir", str(self.cfg), *args],
                              capture_output=True, text=True)

    def test_an_accepted_single_argument_prints_the_argument_list(self):
        r = self.call("--single", "--", "touch 'a b'")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "argv": ["touch", "a b"], "flat": "touch a b", "display": "touch 'a b'"})

    def test_a_refusal_prints_the_rule_and_exits_1(self):
        r = self.call("--single", "--", "cat $HOME")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("literal", out["rule"])
        self.assertTrue(out["detail"])

    def test_a_list_is_taken_as_it_is(self):
        r = self.call("--", "cat", "$HOME")
        self.assertEqual(json.loads(r.stdout)["argv"], ["cat", "$HOME"])

    def test_resolve_prints_the_absolute_exec_list(self):
        gh = self.program("gh")
        r = self.call("--resolve", "--", "gh", "pr", "view", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["exec"], [str(gh), "pr", "view", "5"])

    def test_a_crash_is_not_an_answer(self):
        r = subprocess.run([sys.executable, "-I", str(GATE), "--no-such-flag"], capture_output=True, text=True)
        self.assertNotIn(r.returncode, (0, 1))


if __name__ == "__main__":
    unittest.main()
