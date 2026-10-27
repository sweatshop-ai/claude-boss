#!/usr/bin/env python3
"""boss-goal and boss-tracker keep their own path code; this keeps it true.

Run: python3 skills/boss/test_bash_agreement.py

The two scripts work out the track-name rule, the pm/ paths and the frontier
cache key in bash, so a call costs no extra python3. The track store is the
rule. Each test lifts the script's own lines (PM=, plain(), live(), arch(),
goal(), the two frontier lines), runs them in bash, and compares the answer with
boss_store. A line changed by one character makes `disagreements()` name it;
MutationCheck proves that on copies.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_store  # noqa: E402

BIN = HERE / "bin"

NAMES = ["demo", "a", "0", "a.b", "a_b-c", "x" * 64, "x" * 65, "", "A", "-a", ".a", "_a",
         "a..b", "..", "a/b", "a b", "a\nb", "é", "aé", "日本", "a$b", "a.md"]
SOURCES = ["gh:tiroir/x#1", "gh:a/b#2", "folder/issues", "", "é", "gh:日本/ö#3", "a\n", "a\n\n",
           "\n", "gh:é\n", "x" * 300, "a b", "a'b", 'a"b', "a$b"]
LOCALES = ["C", "C.UTF-8", "en_US.UTF-8"]


class Missing(Exception):
    """A line the store's rule is held against is gone or ambiguous."""


def lift(script, pattern):
    """The one line of `script` that matches `pattern`, as text."""
    hits = [ln for ln in script.read_text(encoding="utf-8").splitlines() if re.match(pattern, ln)]
    if len(hits) != 1:
        raise Missing("%s: %d lines match %r, want 1" % (script.name, len(hits), pattern))
    return hits[0]


def bash(snippet, env_extra=None, args=()):
    env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent"}
    env.update(env_extra or {})
    r = subprocess.run(["bash", "-c", snippet, "_", *args], capture_output=True, env=env)
    return r.returncode, r.stdout.decode("utf-8", "surrogateescape")


def pm_prelude(script):
    return "die() { exit 9; }\n%s\n" % lift(script, r"^PM=")


def disagreements(bindir):
    """Every way the bash in `bindir` differs from the store; [] when it agrees."""
    try:
        return _disagreements(bindir)
    except Missing as exc:
        return [str(exc)]


def _disagreements(bindir):
    out = []
    tracker, goal = Path(bindir) / "boss-tracker", Path(bindir) / "boss-goal"
    cfg = "/cfg"
    pm = boss_store.pm_dir(cfg)
    for script, fns in ((tracker, ("live", "arch")), (goal, ("goal",))):
        pre = pm_prelude(script) + lift(script, r"^plain\(\)") + "\n"
        for fn in fns:
            pre += lift(script, r"^%s\(\)" % fn) + "\n"
        # the config directory rule: unset and empty both mean ~/.claude
        for env, want in (({"CLAUDE_CONFIG_DIR": cfg}, pm),
                          ({"CLAUDE_CONFIG_DIR": ""}, boss_store.pm_dir(None)),
                          ({}, boss_store.pm_dir(None))):
            rc, got = bash(pre + 'printf %s "$PM"', dict(env, HOME=str(Path.home())))
            if got != str(boss_store.pm_dir(env.get("CLAUDE_CONFIG_DIR") or None)):
                out.append("%s: PM is %r for %r" % (script.name, got, env))
        for name in NAMES:
            ok = boss_store.valid_track(name)
            for fn, loc in ((f, l) for f in fns for l in LOCALES):
                rc, got = bash(pre + '%s "$1"' % fn, {"CLAUDE_CONFIG_DIR": cfg, "LC_ALL": loc}, [name])
                want = {"live": boss_store.tracker_path, "goal": boss_store.objective_path}.get(fn, lambda n, cfg: pm / ("%s.archive.md" % n))(name, cfg)
                want = str(want)
                if ok and (rc != 0 or got != want):
                    out.append("%s %s(%r) under %s: got rc=%d %r, want %r" % (script.name, fn, name, loc, rc, got, want))
                if not ok and rc == 0:
                    out.append("%s %s(%r) under %s accepts a name the store refuses" % (script.name, fn, name, loc))
    # the frontier cache: key line and path line, run with the same inputs
    keyln = lift(goal, r"^\s*key=\$\(")
    pathln = lift(goal, r"^\s*c=\"\$PM/\.pulse/")
    snippet = pm_prelude(goal) + keyln + "\n" + pathln + '\nprintf %s "$c"'
    for track in ("demo", "a.b-c"):
        for src in SOURCES:
            for loc in LOCALES:
                env = {"CLAUDE_CONFIG_DIR": cfg, "LC_ALL": loc}
                rc, got = bash('tk="$TK"; t="$TR"\n' + snippet, dict(env, TK=src, TR=track))
                want = str(boss_store.frontier_cache(track, src, cfg=cfg))
                if got != want:
                    out.append("boss-goal frontier cache (%r, %r, %s): got %r, want %r" % (track, src, loc, got, want))
    return out


class Agreement(unittest.TestCase):
    def test_bash_and_store_agree(self):
        self.assertEqual(disagreements(BIN), [])

    def test_the_key_is_the_sha1_of_the_source_bytes(self):
        # not only ASCII: the store hashes utf-8 bytes, newlines included
        for src in ("é", "gh:日本#1", "a\n", "a\n\n"):
            want = hashlib.sha1(src.encode("utf-8")).hexdigest()[:10]
            self.assertTrue(boss_store.frontier_cache("t", src, cfg="/c").name.startswith("t.%s." % want))
            _, got = bash('printf "%s" "$TK" | sha1sum | cut -c1-10', {"TK": src, "LC_ALL": "C"})
            self.assertEqual(got.strip(), want, repr(src))


class MutationCheck(unittest.TestCase):
    """One character changed in a COPY of the scripts must make the test fail."""

    MUTATIONS = [
        ("boss-tracker", "^[a-z0-9][a-z0-9._-]{0,63}$", "^[a-z0-9][a-z0-9._-]{0,64}$", "regex length"),
        ("boss-goal", "^[a-z0-9][a-z0-9._-]{0,63}$", "^[a-z0-9][a-z0-9._-]{0,63}", "regex anchor"),
        ("boss-goal", "[a-z0-9._-]", "[a-z0-9_-]", "regex class"),
        ("boss-goal", "%s.goal.md", "%s.goals.md", "objective path"),
        ("boss-tracker", "%s/%s.md", "%s/%s.m", "tracker path"),
        ("boss-tracker", "%s.archive.md", "%s.archives.md", "archive path"),
        ("boss-goal", "$PM/.pulse/$t.$key", "$PM/pulse/$t.$key", "cache directory"),
        ("boss-goal", ".frontier.json", ".frontier.jsn", "cache suffix"),
        ("boss-goal", "cut -c1-10", "cut -c1-9", "key length"),
        ("boss-goal", "sha1sum", "sha256sum", "key hash"),
        ("boss-goal", "printf '%s' \"$tk\" | sha1sum", "echo \"$tk\" | sha1sum", "echo for printf"),
        ("boss-goal", "printf '%s' \"$tk\" | sha1sum", "printf '%s' \"${tk:0:20}\" | sha1sum", "truncated source"),
        ("boss-tracker", '"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/pm"', '"${CLAUDE_CONFIG_DIR-$HOME/.claude}/pm"', "empty config dir"),
    ]

    def test_each_mutation_is_caught(self):
        for script, old, new, what in self.MUTATIONS:
            with self.subTest(what):
                with tempfile.TemporaryDirectory() as d:
                    copy = Path(d) / "bin"
                    shutil.copytree(BIN, copy)
                    text = (copy / script).read_text(encoding="utf-8")
                    self.assertIn(old, text, "mutation target is gone from %s" % script)
                    (copy / script).write_text(text.replace(old, new, 1), encoding="utf-8")
                    self.assertNotEqual(disagreements(copy), [], "not caught: %s" % what)


if __name__ == "__main__":
    unittest.main()
