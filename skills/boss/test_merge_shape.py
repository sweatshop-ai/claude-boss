#!/usr/bin/env python3
"""Tests for merge_shape.py: the hard rule sees what the shell will run, not the raw text (ticket 53).

Run: python3 skills/boss/test_merge_shape.py
"""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import merge_shape  # noqa: E402

MERGE = "PR merge outside boss_merge"
OPAQUE = "merge rule cannot see through"

# Codex's three, then every other way valid shell syntax hides the same operation.
MERGES = [
    '"gh" pr merge 5',
    'gh pr "merge" 5',
    'gh api -X "PUT" repos/o/r/pulls/5/merge',
    "'gh' 'pr' 'merge' 5",
    'g"h" pr mer"ge" 5',
    r"g\h pr merge 5",
    r"\gh pr merge 5",
    "gh pr $'merge' 5",
    '"/usr/bin/gh" pr merge 5',
    'gh -R o/r pr "merge" 5',
    'gh pr -R "o/r" "merge" 5',
    'gh pr --repo="o/r" merge 5',
    'gh api --method "PUT" repos/o/r/pulls/5/merge',
    'gh api --method="PUT" repos/o/r/pulls/5/merge',
    'gh api -XPUT repos/o/r/pulls/5/merge',
    'gh api -X put repos/o/r/pulls/5/merge',
    'gh api repos/o/r/pulls/5/"merge" -X PUT',
    'gh api "repos/o/r/pulls/5/merge" -X PUT',
    'gh api -X POST repos/o/r/pulls/5/merge',
    'gh api graphql -f query="mutation { merge""PullRequest(input: {}) { x } }"',
    "gh api graphql -f 'query=mutation { enablePull''RequestAutoMerge(input: {}) { x } }'",
    "FOO=1 gh pr merge 5",
    "true && 'gh' pr merge 5",
    "true; \"gh\" pr merge 5",
    "true | gh pr 'merge' 5",
    "{ gh pr 'merge' 5; }",
    "if true; then gh pr 'merge' 5; fi",
    "(gh pr 'merge' 5)",
    "echo $(gh pr 'merge' 5)",
    "echo `gh pr 'merge' 5`",
    "echo \"$(gh pr 'merge' 5)\"",
    "echo ${x:-$(gh pr 'merge' 5)}",
    "echo $(echo $(gh pr 'merge' 5))",
    "cat <(gh pr 'merge' 5)",
    "bash -c 'gh pr \"merge\" 5'",
    "sh -lc 'gh pr \"merge\" 5'",
    "eval 'gh pr \"merge\" 5'",
    "eval gh pr '\"merge\"' 5",
    "env gh pr 'merge' 5",
    "env -i FOO=1 gh pr 'merge' 5",
    "command gh pr 'merge' 5",
    "exec gh pr 'merge' 5",
    "sudo -u x gh pr 'merge' 5",
    "timeout 5 gh pr 'merge' 5",
    "nohup gh pr 'merge' 5",
    "env bash -c 'gh pr \"merge\" 5'",
    "find . -exec gh pr 'merge' 5 \\;",
    "bash <<EOF\ngh pr 'merge' 5\nEOF",
    "bash <<< \"gh pr 'merge' 5\"",
    "cat <<EOF\n$(gh pr 'merge' 5)\nEOF",
    "gh pr merge 5 >/dev/null",
    "2>/dev/null gh pr 'merge' 5",
    "gh pr merge\n",
    "echo ok\ngh pr 'merge' 5",
]

# What the shell cannot be seen through: refused, and the reason says so.
OPAQUE_CMDS = [
    "$GH pr view 5",
    "${GH} pr view 5",
    "gh${IFS}pr${IFS}merge 5",
    '"$GH" pr view 5',
    "$(echo gh) pr view 5",
    "`echo gh` pr view 5",
    "/usr/bin/g[h] pr view 5",
    "/usr/bin/g? pr view 5",
    "{g,}h pr view 5",
    "FOO=1 $GH pr view 5",
    "gh pr $SUB 5",
    "gh $X merge 5",
    "gh pr m* 5",
    "gh pr {merge,view} 5",
    "eval \"$X\"",
    "eval gh pr $SUB",
    "bash -c \"$X\"",
    "bash -c \"gh pr $SUB 5\"",
    "bash -c",
    "bash script.sh",
    "bash",
    "echo 'gh pr merge 5' | sh",
    "echo x | bash -",
    "source ./x.sh",
    ". ./x.sh",
    "env $GH pr view 5",
    "command $GH pr view 5",
    "exec $GH pr view 5",
    "xargs gh pr view",
    "echo 5 | xargs -I{} gh pr view {}",
    "xargs sh -c 'x'",
    "find . -exec $GH {} \\;",
    "gh alias set m 'pr merge'",
    "gh alias import aliases.yml",
    "gh m 5",
    "gh extension-name 5",
    "gh api -X PUT repos/o/r/pulls/$N/merge",
    "gh api -X PUT $EP",
    "gh api graphql -f query=@q.graphql",
    "gh api graphql -F query=@q.graphql",
    "gh api graphql --input q.json",
    'gh api graphql -f query="$Q"',
    "gh api graphql -f query=$Q",
    "gh api graphql --input -",
    "echo $(",
    "echo `unclosed",
    "echo 'unclosed",
    'echo "unclosed',
    "echo $(echo (",
    "bash <<EOF\n$X\nEOF",
    "cat <<EOF\nnever closed",
]

CLEAN = [
    "touch dry.flag",
    "gh pr view 5",
    "gh pr comment 5 --body 'merge when green'",
    "gh pr comment 5 --body \"merge\"",
    "gh pr checks 5 --repo o/r",
    "gh pr -Ro/r view 5",
    "gh pr -R=o/r checks 5",
    "gh pr --repo= view 5",
    "gh pr -R o/r -Ro/r comment 5 --body 'merge'",
    "gh pr -R merge view 5",              # the repo is called "merge"
    "gh -R merge pr view 5",
    "gh pr view $N",
    "gh pr comment $N --body \"$MSG\"",
    "gh pr list --repo $R",
    "gh -R $R pr view 5",
    "gh issue comment 5 --body merge",
    "github pr merge-notes",
    "my-gh pr merge-notes",
    "python3 skills/boss/boss_merge.py --repo o/r --pr 5",
    "python3 skills/boss/boss_merge.py --repo o/r --pr 5 --dry-run",
    "gh api repos/o/r/pulls/5/merge",
    "gh api repos/o/r/pulls/5/merge --method GET",
    "gh api -X GET repos/o/r/pulls/5/merge",
    "gh api -X PUT repos/o/r/issues/5/labels",
    "gh api graphql -f query='query($o: String!) { repository(owner: $o, name: \"r\") { id } }' -f o=x",
    "gh api graphql -f query='{ viewer { login } }'",
    "gh api -X PATCH repos/o/r/issues/5 -f title=x",
    "gh --version",
    "gh",
    "echo $(date)",
    "echo \"$(date) $HOME\"",
    "ls | wc -l",
    "grep -c merge file.txt",
    "echo merge",
    "bash -c 'echo hi'",
    "sh -c \"echo hi\"",
    "eval 'echo hi'",
    "env FOO=1 ls",
    "command -v git",
    "command -v gh codex claude tmux > found.txt",
    "which gh codex",
    "timeout 5 ls",
    "xargs rm",
    "find . -name '*.py' -exec ls {} \\;",
    "cat <<EOF\nmerge it\nEOF",
    "cat <<'EOF'\n$X gh pr merge\nEOF",
    "echo a > out.txt",
    "ls 2>&1",
    "for f in a b; do echo $f; done",
    "while read x; do echo $x; done < in.txt",
    "gh alias list",
    "gh pr view 5 && gh pr checks 5",
    "FOO=\"a b\" gh pr view 5",
    "echo 'it'\"'\"'s'",
    "echo $((1+2))",
    "echo ${x:-default}",
]


class Scan(unittest.TestCase):
    def test_each_hidden_merge_is_found(self):
        for cmd in MERGES:
            with self.subTest(cmd):
                f = merge_shape.scan(cmd)
                self.assertIsNotNone(f, cmd)
                self.assertEqual(f[0], MERGE, f)

    def test_what_cannot_be_seen_through_is_refused_and_says_so(self):
        for cmd in OPAQUE_CMDS:
            with self.subTest(cmd):
                f = merge_shape.scan(cmd)
                self.assertIsNotNone(f, cmd)
                self.assertIn(f[0], (MERGE, OPAQUE), f)

    def test_the_opaque_ones_name_the_opacity_not_a_merge(self):
        for cmd in ("$GH pr view 5", "bash script.sh", "gh m 5", "eval \"$X\"", "echo $("):
            with self.subTest(cmd):
                self.assertEqual(merge_shape.scan(cmd)[0], OPAQUE)

    def test_what_is_not_a_merge_passes(self):
        for cmd in CLEAN:
            with self.subTest(cmd):
                self.assertIsNone(merge_shape.scan(cmd), cmd)

    def test_the_finding_carries_a_detail_to_show_the_owner(self):
        name, detail = merge_shape.scan('"gh" pr merge 5')
        self.assertIn("gh pr merge", detail)
        name, detail = merge_shape.scan("$GH pr view")
        self.assertIn("$GH", detail)

    def test_a_deeply_nested_command_cannot_exhaust_the_scanner(self):
        f = merge_shape.scan("echo " + "$(" * 400 + "x" + ")" * 400)
        self.assertEqual(f[0], OPAQUE)


class Cli(unittest.TestCase):
    def run_cli(self, cmd):
        return subprocess.run([sys.executable, str(HERE / "merge_shape.py")], input=cmd,
                              capture_output=True, text=True)

    def test_clean_exits_0_with_no_output(self):
        r = self.run_cli("gh pr view 5")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_finding_exits_1_and_prints_name_tab_detail(self):
        r = self.run_cli('"gh" pr merge 5')
        self.assertEqual(r.returncode, 1)
        name, _, detail = r.stdout.rstrip("\n").partition("\t")
        self.assertEqual(name, MERGE)
        self.assertTrue(detail)


if __name__ == "__main__":
    unittest.main()
