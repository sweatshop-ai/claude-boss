#!/usr/bin/env python3
"""Tests for boss_review.py: one command that reviews one PR head, hermetically.

Run: python3 skills/boss/test_boss_review.py

`review()` reads a PR with `gh`, asks Codex (through reviewer_chain, in a child process started
in the checkout), keeps the round on disk and posts a minimal comment. Every test goes through
hermetic.Sandbox: `codex`, `claude` and `gh` are stubs that log their argv, stdin and working
directory, `git` is the only other real tool and runs on a throwaway repo, HOME and
CLAUDE_CONFIG_DIR are temporary, and TypeSafe has no key to find. Two seams are tested:
`review()` in-process, and the command line. The five write functions (`open_lock`,
`claim_round`, `append_attempts`, `write_out`, `replace_record`) are patched only to make a
write fail.
"""
import dataclasses
import inspect
import itertools
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_review as br  # noqa: E402
import policy  # noqa: E402
from hermetic import Sandbox, alive  # noqa: E402

REPO = "Owner/Repo"
PR = 5
AUTHOR = "worker-a"
OTHER_SHA = "b" * 40
TITLE = "Keep the round on disk"
BODY = "Writes round<NN>.json before it posts.\n\nCloses nothing."
DIFF = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new"

# The `gh` stub. It keeps a PR in side/pr.json and answers `pr view`, `pr diff` and `pr comment` from
# side/gh.json: per kind, a list of per-call entries (the last one repeats) with optional
# `patch` (fields of the PR changed before answering), `sleep`, `rc`, `raw` (printed instead of
# the JSON) and `drop` (fields left out). The bash prologue has already logged the call.
GH_HANDLER = r'''
import json, sys, time
from pathlib import Path

side, argv = Path(sys.argv[1]), sys.argv[2:]
cfg = json.loads((side / "gh.json").read_text())
state_file = side / "pr.json"


def entry(kind):
    entries = cfg.get(kind) or [{}]
    with open(side / ("count-" + kind), "ab") as f:      # O_APPEND: the size before is the call number
        f.write(b"x")
        n = f.tell() - 1
    return entries[min(n, len(entries) - 1)]


def patched(e):
    state = json.loads(state_file.read_text())
    if e.get("patch"):
        state.update(e["patch"])
        state_file.write_text(json.dumps(state))
    return state


if argv[:2] == ["pr", "view"]:
    e = entry("view")
    state = patched(e)
    time.sleep(e.get("sleep", 0))
    if "raw" in e:
        sys.stdout.write(e["raw"])
    else:
        fields = argv[argv.index("--json") + 1].split(",")
        sys.stdout.write(json.dumps({f: state[f] for f in fields if f not in e.get("drop", [])}))
    sys.exit(e.get("rc", 0))
if argv[:2] == ["pr", "diff"]:
    e = entry("diff")
    state = patched(e)
    time.sleep(e.get("sleep", 0))
    sys.stdout.write(e["raw"] if "raw" in e else state["diff"])
    sys.stderr.write(e.get("err", ""))
    sys.exit(e.get("rc", 0))
if argv[:2] == ["pr", "comment"]:
    e = entry("comment")
    patched(e)
    time.sleep(e.get("sleep", 0))
    sys.stderr.write(e.get("err", ""))
    sys.exit(e.get("rc", 0))
sys.stderr.write("gh stub: no handler for %r\n" % (argv,))
sys.exit(64)
'''


class Gh:
    """The `gh` stub and the PR it serves."""

    def __init__(self, sb, head, repo=REPO, pr=PR, base="main"):
        self.side = sb.side
        (self.side / "gh_handler.py").write_text(GH_HANDLER, encoding="utf-8")
        self.set_pr(number=pr, url="https://github.com/%s/pull/%d" % (repo, pr),
                    headRefOid=head, baseRefName=base, title=TITLE, body=BODY, diff=DIFF)
        self.configure()
        sb.stub_script("gh", 'exec python3 "$R/side/gh_handler.py" "$R/side" "$@"')

    def set_pr(self, **fields):
        path = self.side / "pr.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        state.update(fields)
        path.write_text(json.dumps(state), encoding="utf-8")

    def configure(self, view=None, comment=None, diff=None):
        (self.side / "gh.json").write_text(json.dumps({"view": view, "comment": comment, "diff": diff}),
                                           encoding="utf-8")


def git(sb, cwd, *args):
    env = dict(sb.env, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(extra_tools=("git",))
        self.addCleanup(self.sb.cleanup)
        env = dict(self.sb.env, BOSS_TYPESAFE_ENV=str(self.sb.root / "no-typesafe.env"))
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(tempfile, "tempdir", str(self.sb.tmp))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.checkout = self.sb.work / "checkout"
        self.checkout.mkdir()
        git(self.sb, self.checkout, "init", "-q")
        git(self.sb, self.checkout, "commit", "-q", "--allow-empty", "-m", "the PR head")
        self.head = git(self.sb, self.checkout, "rev-parse", "HEAD")
        self.gh = Gh(self.sb, self.head)
        self.sb.stub("claude", answer="VERDICT: GO")      # there is no fallback here: it must never run
        self.reviews = self.sb.cfg / "pm" / "reviews"
        self.pr_dir = self.reviews / "owner" / "repo" / ("pr%d" % PR)

    def setUp_clean(self):
        """A fresh review directory, PR and call logs inside one test (for subTest loops)."""
        for d in (self.sb.cfg, self.sb.calls, self.sb.side):
            shutil.rmtree(d)
            d.mkdir()
        (self.sb.stubs / "codex").unlink(missing_ok=True)
        self.gh = Gh(self.sb, self.head)
        self.sb.stub("claude", answer="VERDICT: GO")

    def tearDown(self):
        self.sb.guard()
        self.assertEqual(self.sb.calls_of("claude"), [], "claude was called: there is no fallback here")
        for call in self.sb.calls_of("gh"):
            self.assertGhCallIsScoped(call.argv)

    def assertGhCallIsScoped(self, argv):
        """Every `gh pr` call carries --repo, every `gh api` endpoint starts repos/<owner>/<repo>/."""
        owner, name = REPO.lower().split("/")
        if argv[0] == "pr":
            self.assertIn("--repo", argv, argv)
            self.assertEqual(argv[argv.index("--repo") + 1].lower(), REPO.lower(), argv)
        elif argv[0] == "api":
            self.assertTrue(argv[1].lower().startswith("repos/%s/%s/" % (owner, name)), argv)
        else:
            self.fail("an unscoped gh call: %r" % (argv,))

    # ---------------------------------------------------------------- helpers ----
    def review(self, repo=REPO, pr=PR, author=AUTHOR, checkout=None, **kw):
        return br.review(repo, pr, str(checkout or self.checkout), author, **kw)

    def codex(self, **kw):
        return self.sb.stub("codex", **kw)

    def assertAttemptsLogged(self, *rounds):
        self.assertEqual([line["round"] for line in self.attempts_log()], list(rounds))

    def comments(self):
        return [c for c in self.sb.calls_of("gh") if c.argv[:2] == ["pr", "comment"]]

    def views(self):
        return [c for c in self.sb.calls_of("gh") if c.argv[:2] == ["pr", "view"]]

    def round_names(self):
        return sorted(p.name for p in self.pr_dir.glob("round*"))

    def round_file(self, n, suffix="json"):
        return self.pr_dir / ("round%02d.%s" % (n, suffix))

    def record(self, n):
        return json.loads(self.round_file(n).read_text(encoding="utf-8"))

    def attempts_log(self):
        path = self.reviews / "attempts.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def body(self, n, verdict, sha=None, author=AUTHOR):
        return "Codex review %d (run by %s)\nHead: %s\nVerdict: %s" % (n, author, sha or self.head, verdict)


TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
KEYS = ["repo", "pr", "round", "head_sha", "base", "reviewer", "model", "kind", "verdict",
        "status", "author", "ts", "attempts"]
ATTEMPT_KEYS = ["reviewer", "reason", "exit_code", "stderr_tail", "model"]
LOG_KEYS = ["ts", "repo", "pr", "round", "reviewer", "reason", "exit_code"]


class GoPosted(Base):
    def test_a_codex_go_is_posted_and_the_round_is_kept(self):
        self.codex(answer="FINDING: none\nVERDICT: GO\nREASON: fine")
        result = self.review()
        self.assertEqual(result, br.ReviewResult(0, 1, "posted", "GO", self.round_file(1)))
        (comment,) = self.comments()
        self.assertEqual(comment.argv, ["pr", "comment", str(PR), "--repo", REPO,
                                        "--body", self.body(1, "GO") + "\n\n    FINDING: none"])
        record = self.record(1)
        self.assertEqual(list(record), KEYS)
        self.assertRegex(record.pop("ts"), TS)
        self.assertEqual(record, {
            "repo": "owner/repo", "pr": PR, "round": 1, "head_sha": self.head, "base": "main",
            "reviewer": "codex", "model": None, "kind": "codex", "verdict": "GO",
            "status": "posted", "author": AUTHOR,
            "attempts": [{"reviewer": "codex", "reason": "answered", "exit_code": 0,
                          "stderr_tail": "", "model": None}]})
        self.assertEqual(list(self.record(1)["attempts"][0]), ATTEMPT_KEYS)
        self.assertEqual(self.round_file(1, "out").read_text(encoding="utf-8"),
                         "FINDING: none\nVERDICT: GO\nREASON: fine")
        (line,) = self.attempts_log()
        self.assertEqual(list(line), LOG_KEYS)
        self.assertRegex(line.pop("ts"), TS)
        self.assertEqual(line, {"repo": "owner/repo", "pr": PR, "round": 1, "reviewer": "codex",
                                "reason": "answered", "exit_code": 0})

    def test_codex_is_asked_to_review_the_head_it_is_standing_on_with_the_prs_text_in_the_brief(self):
        self.codex(answer="VERDICT: GO")
        self.review()
        (call,) = self.sb.calls_of("codex")
        self.assertEqual(Path(call.cwd), self.checkout.resolve())
        brief = call.argv[-1]
        for needle in (self.head, "main", "FINDING:", "VERDICT: GO", "VERDICT: NO-GO", TITLE, BODY, DIFF):
            self.assertIn(needle, brief)
        self.assertEqual(call.argv[:6], ["exec", "-s", "read-only", "--skip-git-repo-check", "-c",
                                         'model_reasoning_effort="%s"' % br.REVIEW_EFFORT])


RAMBLE = "I would need more context before I can say anything about this."


class NoGoAndNoVerdict(Base):
    def test_a_codex_no_go_is_posted_and_is_exit_three(self):
        self.codex(answer="FINDING: boss_review.py:10 loses a round\nVERDICT: NO-GO")
        result = self.review()
        self.assertEqual(result, br.ReviewResult(3, 1, "posted", "NO-GO", self.round_file(1)))
        (comment,) = self.comments()
        expected = self.body(1, "NO-GO") + "\n\n    FINDING: boss_review.py:10 loses a round"
        self.assertEqual(comment.argv[-1], expected)
        self.assertEqual((self.record(1)["verdict"], self.record(1)["status"]), ("NO-GO", "posted"))

    def test_no_reviewer_answering_posts_nothing_and_keeps_why_for_each_reason(self):
        cases = [
            ("absent", None, {}, None, ""),
            ("timeout", {"hang": True}, {"codex_timeout": 1}, None, ""),
            ("error", {"rc": 3, "err": "codex: model overloaded"}, {}, 3, ""),
            ("noverdict", {"answer": RAMBLE}, {}, 0, RAMBLE + "\n"),
        ]
        for reason, stub, kw, exit_code, raw in cases:
            with self.subTest(reason=reason):
                self.setUp_clean()
                if stub is not None:
                    self.codex(**stub)
                result = self.review(**kw)
                self.assertEqual(result, br.ReviewResult(4, 1, "no-verdict", None, self.round_file(1)))
                self.assertEqual(self.comments(), [])
                record = self.record(1)
                self.assertEqual((record["reviewer"], record["verdict"], record["status"], record["kind"]),
                                 ("none", None, "no-verdict", "codex"))
                (attempt,) = record["attempts"]
                self.assertEqual(list(attempt), ATTEMPT_KEYS)
                self.assertEqual([attempt[k] for k in ("reviewer", "reason", "exit_code", "model")],
                                 ["codex", reason, exit_code, None])
                self.assertEqual(self.round_file(1, "out").read_text(encoding="utf-8"),
                                 "--- codex %s ---\n%s" % (reason, raw))
                (line,) = self.attempts_log()
                self.assertEqual((line["reviewer"], line["reason"], line["exit_code"], line["round"]),
                                 ("codex", reason, exit_code, 1))

    def test_two_different_verdicts_are_no_verdict_and_a_look_alike_word_is_not_a_verdict(self):
        for answer in ("VERDICT: GO\nVERDICT: NO-GO", "VERDICT: GOOD", "VERDICT: GO-AHEAD"):
            with self.subTest(answer=answer):
                self.setUp_clean()
                self.codex(answer=answer)
                self.assertEqual(self.review().exit_code, 4)
                self.assertEqual(self.comments(), [])


REFUSED = br.ReviewResult(2, None, None, None, None)
INFRA = br.ReviewResult(7, None, None, None, None)


class Refused(Base):
    """Nothing is asked, claimed or posted: the review never starts."""

    def assertNothingHappened(self, codex_called=False):
        self.assertEqual(self.comments(), [])
        self.assertFalse(self.reviews.exists(), "a round directory was made")
        if not codex_called:
            self.assertEqual(self.sb.calls_of("codex"), [])

    def test_a_repo_that_is_not_two_plain_names_is_refused_before_anything_runs(self):
        bad = ["../x", "x/..", "./x", "a/b/c", "owner", "owner/", "/repo", "o wner/repo", "owner/re po",
               "owner/repo\n", "owner\n/repo", "ow/ner/", "../..", "./.", "owner/re:po", "ö/repo", ""]
        for repo in bad:
            with self.subTest(repo=repo):
                with self.assertRaises(ValueError):
                    self.review(repo=repo)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.assertNothingHappened()

    def test_the_owner_and_repo_may_hold_dots_dashes_and_underscores_but_are_not_dot_or_dotdot(self):
        for repo in ("sweatshop-ai/claude-boss", "a_b/c.d", "...a/b..", "x/.hidden"):
            self.assertEqual(br.repo_key(repo), repo.lower())
        for repo in (".", "..", "./x", "x/.", "x/.."):
            with self.assertRaises(ValueError):
                br.repo_key(repo)

    def test_the_repo_key_is_the_lowercased_repo(self):
        self.assertEqual(br.repo_key("Owner/Repo"), "owner/repo")
        self.assertEqual(br.repo_key("OWNER/REPO"), br.repo_key("owner/repo"))

    def test_an_author_that_is_not_a_plain_name_is_refused(self):
        for author in ("", "a b", "a/b", "x\n", "né", "a;b", "$(x)"):
            with self.subTest(author=author):
                with self.assertRaises(ValueError):
                    self.review(author=author)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.assertNothingHappened()

    def test_a_pr_that_is_not_a_positive_integer_is_refused(self):
        for pr in (0, -1, "5", 5.0, None, True):
            with self.subTest(pr=pr):
                with self.assertRaises(ValueError):
                    self.review(pr=pr)
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_checkout_that_is_not_a_directory_is_refused(self):
        for path in (self.sb.work / "nope", self.sb.work / "checkout" / ".git" / "HEAD"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.review(checkout=path)
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_pr_that_is_not_the_one_asked_for_is_exit_two_with_nothing_claimed(self):
        wrong = {
            "number": {"number": PR + 1},
            "repo in the url": {"url": "https://github.com/Owner/Other/pull/5"},
            "owner in the url": {"url": "https://github.com/Else/Repo/pull/5"},
            "number in the url": {"url": "https://github.com/Owner/Repo/pull/6"},
            "an issue url": {"url": "https://github.com/Owner/Repo/issues/5"},
            "a longer path": {"url": "https://github.com/Owner/Repo/pull/5/files"},
        }
        for what, fields in wrong.items():
            with self.subTest(what=what):
                self.gh.set_pr(**fields)
                self.assertEqual(self.review(), REFUSED)
                self.assertNothingHappened()
                self.gh.set_pr(number=PR, url="https://github.com/Owner/Repo/pull/5")

    def test_the_owner_and_repo_in_the_url_match_whatever_their_case(self):
        self.gh.set_pr(url="https://github.com/OWNER/rEpO/pull/5")
        self.codex(answer="VERDICT: GO")
        self.assertEqual(self.review().exit_code, 0)

    def test_a_checkout_whose_head_is_not_the_pr_head_is_exit_two_with_nothing_claimed(self):
        self.gh.set_pr(headRefOid=OTHER_SHA)
        self.assertEqual(self.review(), REFUSED)
        self.assertNothingHappened()

    def test_a_git_that_outlasts_the_io_timeout_is_infrastructure_not_a_wrong_checkout(self):
        self.sb.stub_script("git", "sleep 60")
        started = time.monotonic()
        self.assertEqual(self.review(io_timeout=1), INFRA)
        self.assertLess(time.monotonic() - started, 15)
        self.assertNothingHappened()

    def test_a_directory_that_is_not_a_git_checkout_is_exit_two_too(self):
        elsewhere = self.sb.work / "plain"
        elsewhere.mkdir()
        self.assertEqual(self.review(checkout=elsewhere), REFUSED)
        self.assertNothingHappened()


class GhFailures(Base):
    def test_gh_pr_view_failing_is_exit_seven_with_nothing_claimed(self):
        cases = {
            "non-zero exit": {"rc": 1, "raw": ""},
            "not json": {"raw": "this is not json"},
            "empty": {"raw": ""},
            "a list": {"raw": "[]"},
            "a missing number": {"drop": ["number"]},
            "a missing url": {"drop": ["url"]},
            "a missing head": {"drop": ["headRefOid"]},
            "a missing base": {"drop": ["baseRefName"]},
            "a head that is not a sha": {"patch": {"headRefOid": None}},
            "a base that is not a string": {"patch": {"baseRefName": 7}},
            "a number that is a string": {"patch": {"number": "5"}},
            "a url that does not parse": {"patch": {"url": "https://[broken"}},
        }
        for what, entry in cases.items():
            with self.subTest(what=what):
                self.gh.configure(view=[entry])
                self.assertEqual(self.review(), INFRA)
                self.assertEqual(self.comments(), [])
                self.assertEqual(self.sb.calls_of("codex"), [])
                self.assertFalse(self.reviews.exists())
                self.gh.configure()
                self.gh.set_pr(headRefOid=self.head, baseRefName="main", number=PR)

    def test_gh_missing_from_the_path_is_exit_seven(self):
        (self.sb.stubs / "gh").unlink()
        self.assertEqual(self.review(), INFRA)
        self.assertFalse(self.reviews.exists())

    def test_a_gh_call_that_outlasts_the_io_timeout_is_exit_seven_and_is_stopped(self):
        self.gh.configure(view=[{"sleep": 30}])
        started = time.monotonic()
        self.assertEqual(self.review(io_timeout=1), INFRA)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertFalse(self.reviews.exists())


class Moved(Base):
    def sequence(self):
        """The stub calls of the whole run, oldest first, as `tool arg arg`."""
        calls = []
        for argv_file in sorted(self.sb.calls.glob("*.argv")):
            name = argv_file.name.split("-", 1)[1].rsplit(".", 1)[0]
            argv = argv_file.read_bytes().decode("utf-8", "surrogateescape").split("\0")[:-1]
            calls.append(name if name != "gh" else "gh " + " ".join(argv[:2]))
        return calls

    def test_the_pr_is_read_before_the_review_and_again_just_before_the_claim_and_post(self):
        self.codex(answer="VERDICT: GO")
        self.review()
        expected = ["gh pr view", "gh pr diff", "gh pr view", "codex", "gh pr view",
                    "gh pr comment"]
        self.assertEqual(self.sequence(), expected)

    def test_a_head_that_moved_during_the_review_posts_nothing_and_is_exit_six(self):
        for verdict, answer in (("GO", "VERDICT: GO"), ("NO-GO", "VERDICT: NO-GO"), (None, RAMBLE)):
            with self.subTest(verdict=verdict):
                self.setUp_clean()
                self.codex(answer=answer)
                self.gh.configure(view=[{}, {}, {"patch": {"headRefOid": OTHER_SHA}}])
                result = self.review()
                self.assertEqual(result, br.ReviewResult(6, 1, "head-moved", verdict, self.round_file(1)))
                self.assertEqual(self.comments(), [])
                record = self.record(1)
                self.assertEqual((record["head_sha"], record["base"], record["status"], record["verdict"]),
                                 (self.head, "main", "head-moved", verdict))
                self.assertEqual(record["kind"], "codex")
                self.assertEqual(len(self.attempts_log()), 1)
                self.assertTrue(self.round_file(1, "out").exists())

    def test_a_base_that_was_retargeted_during_the_review_is_exit_six_and_the_record_names_the_old_base(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(view=[{}, {}, {"patch": {"baseRefName": "release"}}])
        result = self.review()
        self.assertEqual(result, br.ReviewResult(6, 1, "head-moved", "GO", self.round_file(1)))
        self.assertEqual(self.comments(), [])
        self.assertEqual((self.record(1)["base"], self.record(1)["head_sha"]), ("main", self.head))
        self.assertAttemptsLogged(1)

    def test_a_checkout_that_moved_during_the_review_is_head_moved_too(self):
        # Codex reviewed whatever the checkout held; the comment must not name a head it did not read.
        who = ("GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid "
               "GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid")
        self.sb.stub_script("codex", who + ''' git commit -q --allow-empty -m moved
prev=""; dest=""
for a in "$@"; do [ "$prev" = "-o" ] && dest=$a; prev=$a; done
printf 'VERDICT: GO\\n' > "$dest"''')
        result = self.review()
        self.assertEqual(result, br.ReviewResult(6, 1, "head-moved", "GO", self.round_file(1)))
        self.assertNotEqual(git(self.sb, self.checkout, "rev-parse", "HEAD"), self.head)
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.record(1)["head_sha"], self.head)

    def test_a_head_that_moves_during_the_post_leaves_a_comment_that_names_the_reviewed_head(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(comment=[{"patch": {"headRefOid": OTHER_SHA}}])
        result = self.review()
        self.assertEqual(result, br.ReviewResult(0, 1, "posted", "GO", self.round_file(1)))
        (comment,) = self.comments()
        self.assertEqual(comment.argv[-1], self.body(1, "GO", sha=self.head))
        self.assertNotIn(OTHER_SHA, comment.argv[-1])
        self.assertEqual(self.record(1)["head_sha"], self.head)
        self.assertEqual(len(self.views()), 3, "the window after the re-read is not read again")
        self.assertAttemptsLogged(1)


class PostFailures(Base):
    def test_a_comment_that_gh_refuses_is_post_failed_and_the_verdict_stays_in_the_record(self):
        for verdict, answer in (("GO", "VERDICT: GO"), ("NO-GO", "VERDICT: NO-GO")):
            with self.subTest(verdict=verdict):
                self.setUp_clean()
                self.codex(answer=answer)
                self.gh.configure(comment=[{"rc": 1, "err": "HTTP 502"}])
                result = self.review()
                self.assertEqual(result, br.ReviewResult(7, 1, "post-failed", verdict, self.round_file(1)))
                self.assertEqual(len(self.comments()), 1)
                record = self.record(1)
                self.assertEqual((record["status"], record["verdict"], record["reviewer"]),
                                 ("post-failed", verdict, "codex"))
                self.assertAttemptsLogged(1)

    def test_a_comment_that_times_out_after_gh_recorded_it_is_post_failed_too(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(comment=[{"sleep": 30}])
        started = time.monotonic()
        result = self.review(io_timeout=1)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(result, br.ReviewResult(7, 1, "post-failed", "GO", self.round_file(1)))
        self.assertEqual(len(self.comments()), 1, "the stub logged the call before it hung")
        self.assertEqual(self.record(1)["status"], "post-failed")
        self.assertAttemptsLogged(1)

    def test_a_retry_after_a_failed_post_is_a_new_round_with_a_higher_number(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(comment=[{"rc": 1}, {}])
        first, second = self.review(), self.review()
        self.assertEqual((first.round, first.status, second.round, second.status),
                         (1, "post-failed", 2, "posted"))
        self.assertAttemptsLogged(1, 2)
        self.assertEqual(self.record(1)["status"], "post-failed", "no round file is edited after its write")


class WriteFailures(Base):
    """Before the claim nothing is left behind; after it the claimed file stays empty."""

    def assertLockIsFree(self):
        """The failed run let go of the PR's lock: the next review is not held up by it."""
        self.codex(answer="VERDICT: GO")
        self.assertEqual(self.review(io_timeout=2).exit_code, 0)

    def test_a_lock_or_directory_that_cannot_be_opened_claims_nothing_and_posts_nothing(self):
        self.codex(answer="VERDICT: GO")
        with mock.patch.object(br, "open_lock", side_effect=OSError("read-only file system")):
            result = self.review()
        self.assertEqual(result, INFRA)
        self.assertEqual(self.comments(), [])
        self.assertEqual(len(self.sb.calls_of("codex")), 1, "the review runs first")
        self.assertEqual(len(self.views()), 2)
        self.assertAttemptsLogged()

    def test_a_claim_that_fails_claims_nothing_and_posts_nothing(self):
        self.codex(answer="VERDICT: GO")
        with mock.patch.object(br, "claim_round", side_effect=OSError("no space left")):
            result = self.review()
        self.assertEqual(result, INFRA)
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.attempts_log(), [])
        self.assertEqual(self.round_names(), [])
        self.assertLockIsFree()
        self.assertEqual(self.record(1)["round"], 1, "the failed run took no number")

    def test_a_live_read_that_fails_under_the_lock_claims_nothing_and_posts_nothing(self):
        self.codex(answer="VERDICT: GO")
        self.gh.configure(view=[{}, {}, {"rc": 1}])
        self.assertEqual(self.review(), INFRA)
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.round_names(), [])
        self.assertAttemptsLogged()
        self.gh.configure()
        self.assertLockIsFree()

    def test_attempts_that_cannot_be_appended_leave_the_claimed_file_empty_and_post_nothing(self):
        for verdict, answer in (("GO", "VERDICT: GO"), (None, RAMBLE)):
            with self.subTest(verdict=verdict):
                self.setUp_clean()
                self.codex(answer=answer)
                with mock.patch.object(br, "append_attempts", side_effect=OSError("disk full")):
                    result = self.review()
                self.assertEqual(result, br.ReviewResult(7, 1, None, verdict, self.round_file(1)))
                self.assertEqual(self.round_file(1).read_bytes(), b"")
                self.assertEqual(self.comments(), [])
                self.assertFalse(self.round_file(1, "out").exists())
                self.assertAttemptsLogged()
                self.assertLockIsFree()

    def test_an_out_file_that_cannot_be_written_leaves_the_claimed_file_empty_and_posts_nothing(self):
        self.codex(answer="VERDICT: NO-GO")
        with mock.patch.object(br, "write_out", side_effect=OSError("disk full")):
            result = self.review()
        self.assertEqual(result, br.ReviewResult(7, 1, None, "NO-GO", self.round_file(1)))
        self.assertEqual(self.round_file(1).read_bytes(), b"")
        self.assertEqual(self.comments(), [])
        self.assertAttemptsLogged(1)
        self.assertLockIsFree()

    def test_a_final_write_that_fails_after_the_post_leaves_the_comment_and_an_empty_claimed_file(self):
        self.codex(answer="VERDICT: GO")
        with mock.patch.object(br, "replace_record", side_effect=OSError("disk full")):
            result = self.review()
        self.assertEqual(result, br.ReviewResult(7, 1, None, "GO", self.round_file(1)))
        self.assertEqual(len(self.comments()), 1)
        self.assertEqual(self.round_file(1).read_bytes(), b"")
        self.assertAttemptsLogged(1)
        self.assertLockIsFree()

    def test_a_real_write_error_while_replacing_the_record_leaves_no_temporary_file(self):
        self.codex(answer="VERDICT: GO")
        with mock.patch.object(os, "replace", side_effect=OSError("io error")):
            result = self.review()
        self.assertEqual((result.exit_code, result.status), (7, None))
        self.assertEqual(sorted(p.name for p in self.pr_dir.iterdir() if p.name.startswith(".round")), [])

    def test_a_lock_held_by_another_process_past_the_wait_is_exit_seven_and_claims_nothing(self):
        self.pr_dir.mkdir(parents=True)
        holder = subprocess.Popen(
            [sys.executable, "-c", "import fcntl, sys, time\nf = open(sys.argv[1], 'a')\n"
             "fcntl.flock(f, fcntl.LOCK_EX)\nprint('held', flush=True)\ntime.sleep(60)",
             str(self.pr_dir / ".lock")], stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        self.codex(answer="VERDICT: GO")
        started = time.monotonic()
        result = self.review(io_timeout=1)
        elapsed = time.monotonic() - started
        self.assertEqual(result, INFRA)
        self.assertLess(elapsed, 15)
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.round_names(), [])
        self.assertEqual(len(self.views()), 2, "the live read waits for the lock")


class Numbering(Base):
    def test_an_empty_file_left_by_a_crash_is_superseded_by_the_next_round(self):
        self.pr_dir.mkdir(parents=True)
        self.round_file(1).touch()
        self.codex(answer="VERDICT: GO")
        result = self.review()
        self.assertEqual((result.round, result.status), (2, "posted"))
        self.assertEqual(self.round_file(1).read_bytes(), b"", "the leftover is not edited or deleted")
        self.assertEqual(self.comments()[0].argv[-1], self.body(2, "GO"))

    def test_numbers_follow_the_highest_file_not_the_first_free_one(self):
        self.pr_dir.mkdir(parents=True)
        self.round_file(3).touch()
        self.round_file(5, "out").touch()
        self.codex(answer="VERDICT: GO")
        self.assertEqual(self.review().round, 6)
        self.assertEqual(self.round_file(6).name, "round06.json")

    def test_a_third_digit_is_a_longer_name_and_still_sorts_after_the_two_digit_ones(self):
        self.pr_dir.mkdir(parents=True)
        self.round_file(99).touch()
        self.codex(answer="VERDICT: GO")
        result = self.review()
        self.assertEqual((result.round, result.record.name), (100, "round100.json"))
        self.assertEqual(self.review().round, 101)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Privacy(Base):
    """What a review keeps is for its owner alone."""

    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0))      # permissive: only the command can make it private
        self.codex(answer="VERDICT: GO")

    def tree(self):
        return (self.reviews, self.reviews / "owner", self.reviews / "owner" / "repo", self.pr_dir)

    def assertPrivate(self):
        for d in self.tree():
            self.assertEqual(oct(mode(d)), oct(0o700), d)
        for f in (self.pr_dir / ".lock", self.round_file(1), self.round_file(1, "out"),
                  self.reviews / "attempts.jsonl"):
            self.assertEqual(oct(mode(f)), oct(0o600), f)

    def test_directories_are_0700_and_files_0600_whatever_the_umask(self):
        self.assertEqual(self.review().exit_code, 0)
        self.assertPrivate()

    def test_a_pm_directory_the_command_had_to_make_is_0700_and_one_that_exists_is_left_alone(self):
        self.assertFalse((self.sb.cfg / "pm").exists())
        self.review()
        self.assertEqual(oct(mode(self.sb.cfg / "pm")), oct(0o700))
        os.chmod(self.sb.cfg / "pm", 0o755)
        self.review()
        self.assertEqual(oct(mode(self.sb.cfg / "pm")), oct(0o755), "pm is not the command's to tighten")

    def test_wider_modes_that_already_exist_are_tightened_when_the_command_uses_them(self):
        self.pr_dir.mkdir(parents=True)
        for d in self.tree():
            os.chmod(d, 0o755)
        for f in (self.pr_dir / ".lock", self.reviews / "attempts.jsonl"):
            f.touch()
            os.chmod(f, 0o644)
        self.assertEqual(self.review().exit_code, 0)
        self.assertPrivate()

    def test_a_second_round_is_private_too_and_the_first_is_left_as_it_was(self):
        self.review()
        os.chmod(self.round_file(1), 0o644)
        self.assertEqual(self.review().round, 2)
        self.assertEqual(oct(mode(self.round_file(2))), oct(0o600))
        self.assertEqual(oct(mode(self.round_file(1))), oct(0o644), "an old round is not touched")

    def test_a_directory_that_is_a_symlink_is_refused_not_followed(self):
        outside = self.sb.root / "outside"
        outside.mkdir()
        os.chmod(outside, 0o755)
        self.reviews.mkdir(parents=True)
        (self.reviews / "owner").symlink_to(outside)
        self.assertEqual(self.review(), INFRA)
        self.assertEqual(self.comments(), [])
        self.assertEqual(list(outside.iterdir()), [], "nothing was written through the link")
        self.assertEqual(oct(mode(outside)), oct(0o755), "its mode was not changed")

    def test_a_reviews_directory_in_the_worktree_is_refused_when_the_checkout_is_a_subdirectory(self):
        sub = self.checkout / "src"
        sub.mkdir()
        inside = self.checkout / ".claude-config"
        inside.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(inside)}):
            self.assertEqual(self.review(checkout=sub), INFRA)
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertEqual(self.comments(), [])
        self.assertEqual(list(inside.iterdir()), [])

    def test_a_reviews_directory_inside_the_checkout_is_refused_before_codex_is_asked(self):
        inside = self.checkout / ".claude-config"
        inside.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(inside)}):
            self.assertEqual(self.review(), INFRA)
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertEqual(self.comments(), [])
        self.assertEqual(list(inside.iterdir()), [])


class Concurrency(Base):
    def threads_for(self, *jobs):
        """A thread for each job (a callable returning a ReviewResult), not started, and the list
        its results will fill."""
        results = [None] * len(jobs)

        def target(i, job):
            results[i] = job()
        return [threading.Thread(target=target, args=(i, job)) for i, job in enumerate(jobs)], results

    def run_together(self, *jobs):
        """Start every job at once, wait for all of them, and return their results."""
        threads, results = self.threads_for(*jobs)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_two_runs_on_one_pr_spelled_differently_share_a_directory_and_get_two_numbers(self):
        self.codex(answer="VERDICT: GO", delay=0.3)
        results = self.run_together(lambda: self.review(repo="Owner/Repo", author="Anna"),
                                    lambda: self.review(repo="owner/repo", author="Boris"))
        self.assertEqual(sorted(r.round for r in results), [1, 2])
        self.assertEqual({r.status for r in results}, {"posted"})
        self.assertEqual(sorted(p.name for p in self.reviews.iterdir()), ["attempts.jsonl", "owner"])
        self.assertEqual(sorted(p.name for p in (self.reviews / "owner").iterdir()), ["repo"])
        self.assertEqual(sorted(p.name for p in self.pr_dir.glob("round*.json")),
                         ["round01.json", "round02.json"])
        for result in results:
            self.assertEqual(self.record(result.round)["round"], result.round)
        spelled = sorted(c.argv[c.argv.index("--repo") + 1] for c in self.comments())
        self.assertEqual(spelled, ["Owner/Repo", "owner/repo"], "each call carries the spelling it was given")
        self.assertEqual({self.record(n)["repo"] for n in (1, 2)}, {"owner/repo"})
        self.assertEqual(sorted(line["round"] for line in self.attempts_log()), [1, 2])

    def test_the_review_that_starts_first_and_finishes_last_gets_the_higher_number_and_posts_last(self):
        self.codex(answer="VERDICT: GO", first_delay=2)       # only the first call is slow
        threads, results = self.threads_for(lambda: self.review(author="Slow"),
                                            lambda: self.review(author="Quick"))
        threads[0].start()
        deadline = time.monotonic() + 20
        while not (self.sb.side / "first-codex").exists() and time.monotonic() < deadline:
            time.sleep(0.02)                                   # the slow review holds the slow turn
        threads[1].start()
        for t in threads:
            t.join()
        slow, quick = results
        self.assertEqual((quick.round, slow.round), (1, 2))
        self.assertEqual([c.argv[-1] for c in self.comments()],
                         [self.body(1, "GO", author="Quick"), self.body(2, "GO", author="Slow")])
        self.assertEqual((self.record(1)["author"], self.record(2)["author"]), ("Quick", "Slow"))

    def test_a_rounds_ts_is_when_it_was_claimed_even_when_it_waited_for_the_lock(self):
        # The run that reaches the lock first is made to dawdle, so the other claims round 1 first.
        self.codex(answer="VERDICT: GO")
        ticks, looks = itertools.count(1), itertools.count()
        real_open_lock = br.open_lock

        def dawdling_open_lock(*args):
            if next(looks) == 0:                  # next() on a count is atomic: exactly one run dawdles
                time.sleep(1)
            return real_open_lock(*args)
        patches = (mock.patch.object(br, "open_lock", dawdling_open_lock),
                   mock.patch.object(br, "_now", lambda: "2026-10-04T00:00:%02dZ" % next(ticks)))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        results = self.run_together(lambda: self.review(author="Anna"), lambda: self.review(author="Boris"))
        self.assertEqual(sorted(r.round for r in results), [1, 2])
        self.assertLess(self.record(1)["ts"], self.record(2)["ts"])
        self.assertEqual([line["ts"] for line in self.attempts_log()],
                         [self.record(1)["ts"], self.record(2)["ts"]])


class Contract(Base):
    def test_the_signature_later_callers_extend_with_keyword_only_parameters(self):
        sig = inspect.signature(br.review)
        self.assertEqual(list(sig.parameters),
                         ["repo", "pr", "checkout", "author", "codex_timeout", "io_timeout"])
        self.assertEqual([p.kind.name for p in sig.parameters.values()],
                         ["POSITIONAL_OR_KEYWORD"] * 4 + ["KEYWORD_ONLY"] * 2)
        self.assertEqual((sig.parameters["codex_timeout"].default, sig.parameters["io_timeout"].default),
                         (policy.REVIEW_CODEX_TIMEOUT, policy.REVIEW_IO_TIMEOUT))

    def test_the_review_waits_are_in_policy_with_their_values(self):
        self.assertEqual((policy.REVIEW_CODEX_TIMEOUT, policy.REVIEW_FALLBACK_TIMEOUT,
                          policy.REVIEW_IO_TIMEOUT), (600, 600, 60))
        self.assertEqual(policy.REVIEW_CHAIN_SLACK, 30)

    def test_a_result_is_a_frozen_value_with_the_five_fields_in_order(self):
        result = br.ReviewResult(0, 1, "posted", "GO", Path("x"))
        self.assertEqual([f.name for f in dataclasses.fields(result)],
                         ["exit_code", "round", "status", "verdict", "record"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.exit_code = 3

    def test_codexs_exit_code_and_stderr_are_kept_when_it_answered_anyway(self):
        self.codex(answer="VERDICT: GO", rc=3, err="warning: something")
        result = self.review()
        self.assertEqual((result.exit_code, result.status), (0, "posted"))
        (attempt,) = self.record(1)["attempts"]
        self.assertEqual((attempt["reason"], attempt["exit_code"], attempt["stderr_tail"]),
                         ("answered", 3, "warning: something\n"))
        self.assertEqual(self.attempts_log()[0]["exit_code"], 3)

    def test_a_review_writes_nothing_to_the_checkout_and_leaves_no_temporary_file(self):
        self.codex(answer="VERDICT: GO")
        before = sorted(str(p) for p in self.checkout.rglob("*") if ".git/" not in str(p))
        self.review()
        self.assertEqual(sorted(str(p) for p in self.checkout.rglob("*") if ".git/" not in str(p)), before)
        self.assertEqual(git(self.sb, self.checkout, "status", "--porcelain"), "")
        self.assertEqual(list(self.sb.tmp.iterdir()), [])


class ChainChild(Base):
    """The chain runs in a child process; what it hands back is checked before anything is claimed."""

    def fake_chain(self, body):
        path = self.sb.root / "fake_chain.py"
        path.write_text(body, encoding="utf-8")
        return mock.patch.object(br, "CHAIN", path)

    def assertInfraBeforeAnyClaim(self):
        self.assertEqual(self.review(codex_timeout=1), INFRA)
        self.assertEqual(self.comments(), [])
        self.assertFalse(self.reviews.exists())

    def test_a_child_that_crashes_is_exit_seven_not_a_codex_outage(self):
        with self.fake_chain("import sys\nsys.stderr.write('Traceback ...')\nsys.exit(1)\n"):
            self.assertInfraBeforeAnyClaim()

    def test_a_child_that_prints_something_that_is_not_a_chain_result_is_exit_seven(self):
        for out in ("not json", "[]", "{}", '{"reviewer": "codex"}',
                    json.dumps({"reviewer": "codex", "output": "", "attempts": [],
                                "parsed": {"word": "MAYBE", "reason": "x"}}),
                    json.dumps({"reviewer": "codex", "output": "", "parsed": None,
                                "attempts": [{"reviewer": "codex"}]})):
            with self.subTest(out=out):
                with self.fake_chain("import sys\nsys.stdout.write(%r)\n" % out):
                    self.assertInfraBeforeAnyClaim()

    GOOD = {"reviewer": "codex", "output": "VERDICT: GO", "parsed": {"word": "GO", "reason": "ok"},
            "attempts": [{"reviewer": "codex", "reason": "answered", "output": "VERDICT: GO",
                          "exit_code": 0, "stderr_tail": "", "model": None}]}

    def stand_in(self, code=0, **over):
        """A chain that prints GOOD with `over` applied to it, then exits with `code`."""
        data = json.loads(json.dumps(self.GOOD))
        for key, value in over.items():
            if key.startswith("attempt_"):
                data["attempts"][0][key[len("attempt_"):]] = value
            else:
                data[key] = value
        return self.fake_chain("import sys\nsys.stdout.write(%r)\nsys.exit(%d)\n" % (json.dumps(data), code))

    def test_a_consistent_result_from_a_stand_in_chain_is_accepted(self):
        self.gh.configure()
        with self.stand_in():
            self.assertEqual(self.review().exit_code, 0)
        self.assertEqual(len(self.comments()), 1)

    def test_a_result_that_contradicts_itself_or_its_exit_code_is_exit_seven_before_any_claim(self):
        none = {"reviewer": "none", "output": "", "parsed": None, "attempt_reason": "timeout",
                "attempt_exit_code": None, "attempt_output": ""}
        cases = {
            "a GO from a child that exited 1": (1, {}),
            "no reviewer from a child that exited 0": (0, none),
            "no reviewer yet an answered attempt": (1, dict(none, attempt_reason="answered")),
            "a Codex GO whose attempt timed out": (0, {"attempt_reason": "timeout"}),
            "a Codex GO with no parsed verdict": (0, {"parsed": None}),
            "a verdict for no reviewer": (1, dict(none, parsed={"word": "GO", "reason": "x"})),
            "a reason that is not in the closed set": (0, {"attempt_reason": "fine"}),
            "an answer that is not the attempt's": (0, {"output": "VERDICT: NO-GO"}),
            "a GO the answer contradicts": (0, {"output": "VERDICT: NO-GO",
                                                "attempt_output": "VERDICT: NO-GO"}),
            "a GO the answer does not carry": (0, {"output": "all fine", "attempt_output": "all fine"}),
            "a GO in an answer that holds a NUL": (0, {"output": "VERDICT: GO\u0000",
                                                       "attempt_output": "VERDICT: GO\u0000"}),
            "a GO that only a NUL makes": (0, {"output": "VERDICT: G\u0000O",
                                               "attempt_output": "VERDICT: G\u0000O"}),
            "a GO beside a NO-GO in the answer": (0, {"output": "VERDICT: GO\nVERDICT: NO-GO",
                                                      "attempt_output": "VERDICT: GO\nVERDICT: NO-GO"}),
            "two attempts": (0, {"attempts": [self.GOOD["attempts"][0]] * 2}),
            "no attempt": (0, {"attempts": []}),
            "a fallback's attempt": (0, {"attempt_reviewer": "haiku", "attempt_model": "claude-haiku"}),
            "a model on a Codex attempt": (0, {"attempt_model": "x"}),
            "an exit code that is a string": (0, {"attempt_exit_code": "0"}),
            "an exit code that is a bool": (0, {"attempt_exit_code": True}),
            "a stderr tail that is a number": (0, {"attempt_stderr_tail": 5}),
            "an attempt output that is a list": (0, {"attempt_output": ["x"]}),
            "a verdict word that is a list": (0, {"parsed": {"word": ["GO"], "reason": "x"}}),
        }
        for what, (code, over) in cases.items():
            with self.subTest(what=what):
                self.setUp_clean()
                with self.stand_in(code, **over):
                    self.assertInfraBeforeAnyClaim()

    def test_a_child_that_exits_with_anything_but_zero_or_one_is_exit_seven(self):
        good = json.dumps({"reviewer": "none", "output": "", "parsed": None, "attempts": [
            {"reviewer": "codex", "reason": "absent", "output": "", "exit_code": None,
             "stderr_tail": "", "model": None}]})
        with self.fake_chain("import sys\nsys.stdout.write(%r)\nsys.exit(2)\n" % good):
            self.assertInfraBeforeAnyClaim()

    def test_a_child_that_outlasts_codexs_timeout_and_its_slack_is_stopped_and_is_exit_seven(self):
        with self.fake_chain("import time\ntime.sleep(60)\n"), \
                mock.patch.object(policy, "REVIEW_CHAIN_SLACK", 1):
            started = time.monotonic()
            self.assertInfraBeforeAnyClaim()
            self.assertLess(time.monotonic() - started, 15)

    def test_a_wedged_chain_takes_a_reviewer_in_a_session_of_its_own_down_with_it(self):
        pid_file = self.sb.root / "reviewer.pid"
        body = ("import subprocess, time\n"
                "kid = subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
                "open(%r, 'w').write(str(kid.pid))\n"
                "time.sleep(60)\n" % str(pid_file))
        with self.fake_chain(body), mock.patch.object(policy, "REVIEW_CHAIN_SLACK", 1):
            self.assertInfraBeforeAnyClaim()
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 10
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(pid), "the reviewer outlived the chain that started it")

    def test_a_reviewer_in_a_session_of_its_own_is_asked_to_stop_before_it_is_killed(self):
        marker = self.sb.root / "reviewer.asked"
        kid = ("import signal, sys, time\n"
               "def asked(*_):\n    open(%r, 'w').write('x')\n    sys.exit(0)\n"
               "signal.signal(signal.SIGTERM, asked)\n"
               "while True:\n    time.sleep(0.1)\n" % str(marker))
        body = ("import subprocess, sys, time\n"
                "subprocess.Popen([sys.executable, '-c', %r], start_new_session=True)\n"
                "time.sleep(60)\n" % kid)
        with self.fake_chain(body), mock.patch.object(policy, "REVIEW_CHAIN_SLACK", 1):
            self.assertInfraBeforeAnyClaim()
        self.assertTrue(marker.exists(), "the reviewer was killed without being asked to stop first")

    def test_a_capture_file_that_cannot_be_made_is_exit_seven_not_an_error_out_of_review(self):
        with mock.patch.object(br.tempfile, "TemporaryFile",
                               side_effect=OSError(errno.EMFILE, "Too many open files")):
            self.assertInfraBeforeAnyClaim()

    def test_a_prompt_directory_that_cannot_be_made_is_exit_seven_not_an_error_out_of_review(self):
        with mock.patch.object(br.tempfile, "TemporaryDirectory",
                               side_effect=OSError(errno.ENOSPC, "No space left on device")):
            self.assertInfraBeforeAnyClaim()

    def test_the_chain_is_asked_for_codex_only_whole_word_go_no_go_and_strict(self):
        recorded = self.sb.root / "chain-argv.json"
        body = ("import json, sys\nopen(%r, 'w').write(json.dumps(sys.argv[1:]))\nsys.exit(2)\n"
                % str(recorded))
        with self.fake_chain(body):
            self.review(codex_timeout=7)
        argv = json.loads(recorded.read_text())
        self.assertEqual(argv[argv.index("--words") + 1], "GO,NO-GO")
        self.assertEqual(argv[argv.index("--match") + 1], "token")
        self.assertEqual(argv[argv.index("--codex-timeout") + 1], "7")
        self.assertEqual(argv[argv.index("--effort") + 1], br.REVIEW_EFFORT)
        self.assertIn("--strict", argv)
        self.assertIn("--no-fallback", argv)
        self.assertFalse([a for a in argv if a.startswith("--fallback-")])


class OddWorktreeNames(Base):
    """A worktree may sit in a directory whose name is any bytes but NUL and "/": git prints the path
    as it is, and the review must read it back as it is."""
    NAMES = {"bytes that are not text": b"odd-\xff-name", "a newline": b"odd-\nname",
             "a unicode line separator": "odd-\u2028name".encode()}

    def odd_checkout(self, name):
        odd = Path(os.fsdecode(os.fsencode(self.sb.work) + b"/" + name))
        odd.mkdir()
        git(self.sb, odd, "init", "-q")
        git(self.sb, odd, "commit", "-q", "--allow-empty", "-m", "the PR head")
        self.gh = Gh(self.sb, git(self.sb, odd, "rev-parse", "HEAD"))
        return odd

    def test_a_reviews_directory_inside_such_a_worktree_is_refused_before_codex_is_asked(self):
        for what, name in self.NAMES.items():
            with self.subTest(name=what):
                self.setUp_clean()
                odd = self.odd_checkout(name)
                inside = odd / ".claude-config"
                inside.mkdir()
                sub = odd / "src"
                sub.mkdir()
                self.codex(answer="VERDICT: GO")
                with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(inside)}):
                    self.assertEqual(self.review(checkout=sub), INFRA)
                self.assertEqual(self.sb.calls_of("codex"), [])
                self.assertEqual(self.comments(), [])
                self.assertEqual(list(inside.iterdir()), [])

    def test_a_review_from_such_a_worktree_is_posted_like_any_other(self):
        for what, name in self.NAMES.items():
            with self.subTest(name=what):
                self.setUp_clean()
                odd = self.odd_checkout(name)
                self.codex(answer="VERDICT: GO")
                self.assertEqual(self.review(checkout=odd).exit_code, 0)
                self.assertEqual(len(self.comments()), 1)


class StopBelow(unittest.TestCase):
    """What the timeout stops is the processes it saw below the chain, each by what it was then:
    a pid is reused once its process is gone, so a pid alone is not enough to signal."""

    def setUp(self):
        self.other = subprocess.Popen(["sleep", "300"])
        self.addCleanup(lambda: (self.other.kill(), self.other.wait()))
        self.start = br._start_time(self.other.pid)

    def test_below_names_what_a_process_started_with_when_it_started(self):
        seen = br._below(os.getpid())
        self.assertIn(br._Seen(self.other.pid, self.start), seen)
        self.assertNotIn(os.getpid(), [s.pid for s in seen])

    def fds(self):
        return len(os.listdir("/proc/self/fd"))

    def spawn_python(self, code):
        """A python process that has printed `ready`, killed when the test is over."""
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (proc.kill(), proc.wait(), proc.stdout.close()))
        self.assertEqual(proc.stdout.readline().strip(), "ready")
        return proc

    def test_the_stop_leaves_no_file_descriptor_open_after_a_process_that_gave_way_to_term(self):
        before = self.fds()
        br._stop_below([br._Seen(self.other.pid, self.start)])
        self.assertFalse(alive(self.other.pid))
        self.assertEqual(self.fds(), before)

    def test_a_process_that_ignores_term_is_killed_only_after_the_grace_and_leaves_no_descriptor_open(self):
        marker = Path(tempfile.mkdtemp(prefix="stop-below-")) / "termed"
        self.addCleanup(shutil.rmtree, marker.parent, True)
        stubborn = self.spawn_python(      # takes note of TERM, goes on running, and so must be killed
            "import signal, time\n"
            "def termed(*_):\n    open(%r, 'w').write(repr(time.monotonic()))\n"
            "signal.signal(signal.SIGTERM, termed)\nprint('ready', flush=True)\n"
            "while True:\n    time.sleep(0.02)\n" % str(marker))
        seen = br._Seen(stubborn.pid, br._start_time(stubborn.pid))
        died = []

        def watch():
            while alive(stubborn.pid):
                time.sleep(0.005)
            died.append(time.monotonic())
        before = self.fds()           # the watcher opens /proc files while it runs: count around it
        watcher = threading.Thread(target=watch)
        watcher.start()
        with mock.patch.object(br, "TERM_GRACE", 0.5):
            br._stop_below([seen])
        watcher.join(10)
        self.assertTrue(marker.exists(), "the process was killed before it could take note of TERM")
        self.assertGreaterEqual(died[0] - float(marker.read_text()), 0.4,
                                "the process was killed before the grace after TERM was over")
        self.assertEqual(self.fds(), before)

    def test_hold_reads_the_start_time_after_the_pidfd_is_open_not_before(self):
        order = []
        real_open, real_start = os.pidfd_open, br._start_time

        def opened(*a, **k):
            order.append("open")
            return real_open(*a, **k)

        def started(*a, **k):
            order.append("start")
            return real_start(*a, **k)
        with mock.patch.object(os, "pidfd_open", opened), mock.patch.object(br, "_start_time", started):
            fd = br._hold(br._Seen(self.other.pid, self.start))
        os.close(fd)
        self.assertEqual(order, ["open", "start"])

    def test_no_descriptor_survives_a_start_time_that_cannot_be_read(self):
        third = subprocess.Popen(["sleep", "300"])
        self.addCleanup(lambda: (third.kill(), third.wait()))
        seen = [br._Seen(self.other.pid, self.start), br._Seen(third.pid, br._start_time(third.pid))]
        before = self.fds()
        with mock.patch.object(br, "_start_time", side_effect=[self.start, RuntimeError("boom")]):
            with self.assertRaises(RuntimeError):
                br._stop_below(seen)
        self.assertEqual(self.fds(), before)
        self.assertTrue(alive(self.other.pid) and alive(third.pid))

    def test_the_walk_below_a_process_goes_on_past_one_whose_name_is_not_text(self):
        odd = self.spawn_python(
            "import ctypes, time\nctypes.CDLL(None).prctl(15, b'\\xff\\xfe', 0, 0, 0)\n"
            "print('ready', flush=True)\ntime.sleep(300)")
        self.assertIn(odd.pid, [s.pid for s in br._below(os.getpid())])

    def test_the_tree_below_a_process_is_what_descends_from_it(self):
        table = {10: (1, "a"), 11: (10, "b"), 12: (10, "c"), 13: (11, "d"), 14: (99, "e"), 99: (1, "f")}
        self.assertEqual(sorted(br._tree_below(table, 10)),
                         [br._Seen(11, "b"), br._Seen(12, "c"), br._Seen(13, "d")])
        self.assertEqual(br._tree_below(table, 13), [])

    def test_a_wide_process_tree_is_walked_in_linear_time(self):
        table = {1000: (1, "0"), 99999: (1, "0")}          # 99999 is not below 1000
        for i in range(20000):
            table[2000 + i] = (1000, "0")
            table[30000 + i] = (2000 + i, "0")
        started = time.monotonic()
        found = br._tree_below(table, 1000)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(found), 40000)

    def test_a_process_is_signalled_only_while_it_is_the_one_that_was_seen(self):
        before = self.fds()
        reused = br._Seen(self.other.pid, str(int(self.start) + 1))     # same pid, another process
        br._stop_below([reused])
        self.assertTrue(alive(self.other.pid), "a process that was not the one seen was stopped")
        self.assertEqual(self.fds(), before)
        br._stop_below([br._Seen(self.other.pid, self.start)])
        self.assertFalse(alive(self.other.pid))

    def test_a_process_that_cannot_be_signalled_is_skipped_not_an_error(self):
        before = self.fds()
        with mock.patch.object(br, "TERM_GRACE", 0.2), \
                mock.patch.object(br.signal, "pidfd_send_signal", side_effect=PermissionError):
            br._stop_below([br._Seen(self.other.pid, self.start)])
        self.assertTrue(alive(self.other.pid))
        self.assertEqual(self.fds(), before)

    def test_a_process_that_is_gone_is_not_an_error(self):
        gone = subprocess.Popen(["true"])
        gone.wait()
        br._stop_below([br._Seen(gone.pid, "1")])


class CommandLine(Base):
    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(HERE / "boss_review.py"), *args],
                              cwd=str(cwd or self.sb.work), env=dict(os.environ),
                              capture_output=True, text=True, timeout=120)

    def full(self, **over):
        args = {"--repo": REPO, "--pr": str(PR), "--checkout": str(self.checkout), "--author": AUTHOR}
        args.update(over)
        return [x for pair in args.items() if pair[1] is not None for x in pair]

    def test_the_command_exits_with_the_results_code_and_names_the_round_on_stdout(self):
        for exit_code, answer in ((0, "VERDICT: GO"), (3, "VERDICT: NO-GO"), (4, RAMBLE)):
            with self.subTest(exit_code=exit_code):
                self.setUp_clean()
                self.codex(answer=answer)
                r = self.run_cli(*self.full())
                self.assertEqual(r.returncode, exit_code, r.stderr)
                self.assertIn(str(self.round_file(1)), r.stdout)
                self.assertEqual(r.stdout.count("\n"), 1)

    def test_a_url_that_does_not_parse_is_infrastructure_for_the_command_not_a_usage_mistake(self):
        self.gh.set_pr(url="https://[broken")
        r = self.run_cli(*self.full())
        self.assertEqual((r.returncode, r.stdout), (7, ""), r.stderr)

    def test_a_failure_before_any_round_prints_nothing_on_stdout_and_says_why_on_stderr(self):
        self.gh.configure(view=[{"rc": 1}])
        r = self.run_cli(*self.full())
        self.assertEqual((r.returncode, r.stdout), (7, ""))
        self.assertIn("gh pr view", r.stderr)

    def test_a_usage_mistake_is_exit_two_with_nothing_claimed_posted_or_asked(self):
        bad = [{"--repo": None}, {"--pr": None}, {"--checkout": None}, {"--author": None},
               {"--repo": "../x"}, {"--repo": "x/.."}, {"--repo": "./x"}, {"--repo": "a/b/c"},
               {"--author": "a b"}, {"--pr": "0"}, {"--pr": "-3"}, {"--pr": "abc"}, {"--pr": "\u0665"},
               {"--checkout": str(self.sb.work / "nope")}]
        cases = [self.full(**over) for over in bad] + [self.full() + ["--waive"]]
        for args in cases:
            with self.subTest(args=args):
                r = self.run_cli(*args)
                self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertFalse(self.reviews.exists())

    def test_the_repo_is_never_inferred_from_the_working_directory(self):
        git(self.sb, self.checkout, "remote", "add", "origin", "https://github.com/Owner/Repo.git")
        r = self.run_cli(*self.full(**{"--repo": None}), cwd=self.checkout)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.sb.calls_of("gh"), [])


if __name__ == "__main__":
    unittest.main()
