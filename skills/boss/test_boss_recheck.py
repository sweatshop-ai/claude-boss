#!/usr/bin/env python3
"""Tests for boss_recheck.py (ticket 10a): the pass that has Codex review again every PR on the list of
provisional GOs, and the blocker a Codex NO-GO on a merged PR becomes.

Run: python3 -m pytest skills/boss/test_boss_recheck.py

Real `git` on throwaway repos with a local bare origin (a PR's head is `refs/pull/<N>/head` there, as on GitHub),
and hermetic.Sandbox's stubs: `codex` answers by the HEAD of the directory it is started in, `gh` serves several
PRs (state, head, base) and logs every call, `boss-alert` logs its calls, `claude` must never be called. Each test
asserts the stub call logs; tearDown fails if `codex`, `claude` or `gh` resolves outside the stub directory
(Sandbox.guard) or if the `claude` log is not empty.
"""
import contextlib
import fcntl
import io
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_recheck as rk  # noqa: E402
import boss_review as br  # noqa: E402
import tracker  # noqa: E402
from hermetic import Sandbox  # noqa: E402
from test_boss_review import git  # noqa: E402

LADDER = HERE.parent.parent / "routines" / "boss_ladder_core.py"
REPO = "owner/repo"
GO = "FINDING: none\nVERDICT: GO\nREASON: fine\n"
NOGO = "FINDING: [P1] a defect\nVERDICT: NO-GO\nREASON: broken\n"
AT = "2026-11-12T10:00:00Z"
TRACKER = "# t\n\n## Open blockers\n"

# A `gh` that serves several PRs from side/prs.json ({"<N>": {state, headRefOid, baseRefName, ...}}), fails
# `pr view` for the PRs listed in side/fail-view.json, and does nothing for `pr comment` (the prologue has logged it).
GH = r'''
import json, sys
from pathlib import Path
side, argv = Path(sys.argv[1]), sys.argv[2:]
prs = json.loads((side / "prs.json").read_text())
fail = json.loads((side / "fail-view.json").read_text())
if argv[:2] == ["pr", "view"]:
    if argv[2] in fail:
        sys.stderr.write("gh: could not resolve to a PullRequest\n")
        sys.exit(1)
    pr = prs[argv[2]]
    fields = argv[argv.index("--json") + 1].split(",")
    sys.stdout.write(json.dumps({f: pr[f] for f in fields}))
    sys.exit(0)
if argv[:2] == ["pr", "diff"]:
    sys.stdout.write(prs[argv[2]]["diff"])
    sys.exit(0)
if argv[:2] == ["pr", "comment"]:
    sys.exit(0)
sys.stderr.write("gh stub: no handler for %r\n" % (argv,))
sys.exit(64)
'''

# A `codex` that notes the HEAD of the directory it is told to work in (`-C DIR`) and answers as side/answer-<HEAD> says
# (a file holding the answer; side/hang-<HEAD> makes it outlast the timeout; neither: it fails).
CODEX = r'''
prev=""; dest=""; dir=""
for a in "$@"; do [ "$prev" = "-o" ] && dest=$a; [ "$prev" = "-C" ] && dir=$a; prev=$a; done
head=$(git -C "$dir" rev-parse HEAD)
echo "$head" >> "$R/side/codex-heads"
echo "$dir" >> "$R/side/codex-dirs"
git -C "$dir" status --porcelain >> "$R/side/codex-dirty"
[ -e "$R/side/hang-$head" ] && sleep 300
if [ -e "$R/side/answer-$head" ]; then cat "$R/side/answer-$head" > "$dest"; exit 0; fi
echo "codex stub: no answer for $head" >&2
exit 1
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(extra_tools=("git",))
        self.addCleanup(self.sb.cleanup)
        self.alert = self.sb.stub("boss-alert")
        pm = self.sb.cfg / "pm"
        pm.mkdir()
        env = dict(self.sb.env, BOSS_TYPESAFE_ENV=str(self.sb.root / "no-typesafe.env"), BOSS_ALERT=str(self.alert),
                   BOSS_LADDER_PM=str(pm), BOSS_LADDER_STATE=str(self.sb.side / "ladder.json"))
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(rk.tempfile, "tempdir", str(self.sb.tmp))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tracker = pm / "t.md"
        self.tracker.write_text(TRACKER, encoding="utf-8")
        self.reviews = self.sb.cfg / "pm" / "reviews"
        self.origin = self.sb.work / "origin.git"
        self.dev = self.sb.work / "dev"
        self.checkout = self.sb.work / "checkout"
        git(self.sb, self.sb.work, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.dev.mkdir()
        git(self.sb, self.dev, "init", "-q", "-b", "main")
        (self.dev / "f.txt").write_text("main\n")
        git(self.sb, self.dev, "add", "f.txt")
        git(self.sb, self.dev, "commit", "-q", "-m", "main")
        git(self.sb, self.dev, "remote", "add", "origin", str(self.origin))
        git(self.sb, self.dev, "push", "-q", "origin", "main")
        git(self.sb, self.sb.work, "clone", "-q", str(self.origin), str(self.checkout))
        self.base_sha = git(self.sb, self.dev, "rev-parse", "HEAD")
        (self.sb.side / "prs.json").write_text("{}")
        (self.sb.side / "fail-view.json").write_text("[]")
        (self.sb.side / "gh_handler.py").write_text(GH, encoding="utf-8")
        self.sb.stub_script("gh", 'exec python3 "$R/side/gh_handler.py" "$R/side" "$@"')
        self.sb.stub_script("codex", CODEX)
        self.sb.stub("claude", answer="VERDICT: GO")           # there is no fallback here: it must never run
        self.checkout_head = git(self.sb, self.checkout, "rev-parse", "HEAD")

    def tearDown(self):
        self.sb.guard()
        self.assertEqual(self.sb.calls_of("claude"), [], "claude was called: a recheck never falls back")
        for call in self.sb.calls_of("gh"):
            self.assertIn("--repo", call.argv)
            self.assertEqual(call.argv[call.argv.index("--repo") + 1].lower(), REPO)

    # ----------------------------------------------------------------- fixtures ----
    def pr(self, n, label, state="OPEN", answer=None, pull_ref=True):
        """PR `n` at a new commit; Codex answers `answer` on that head. Returns the head."""
        git(self.sb, self.dev, "checkout", "-q", "--detach", self.base_sha)
        git(self.sb, self.dev, "commit", "-q", "--allow-empty", "-m", label)
        sha = git(self.sb, self.dev, "rev-parse", "HEAD")
        if pull_ref:
            git(self.sb, self.dev, "push", "-q", "origin", "%s:refs/pull/%d/head" % (sha, n), "--force")
        self.set_pr(n, headRefOid=sha, state=state)
        if answer:
            (self.sb.side / ("answer-" + sha)).write_text(answer, encoding="utf-8")
        return sha

    def set_pr(self, n, **fields):
        path = self.sb.side / "prs.json"
        prs = json.loads(path.read_text())
        pr = prs.setdefault(str(n), {"number": n, "url": "https://github.com/%s/pull/%d" % (REPO, n),
                                     "baseRefName": "main", "title": "T", "body": "B", "diff": "diff\n",
                                     "state": "OPEN"})
        pr.update(fields)
        path.write_text(json.dumps(prs))

    def fail_view(self, *prs):
        (self.sb.side / "fail-view.json").write_text(json.dumps([str(n) for n in prs]))

    def hang_on(self, sha):
        (self.sb.side / ("hang-" + sha)).write_text("")

    def prov(self, n, head, round=1, repo=REPO):
        return "- [prov %s#%d] head=%s round=%02d base=main at=%s" % (repo, n, head, round, AT)

    def put(self, *lines, blockers=""):
        self.tracker.write_text(TRACKER + blockers + "\n## Provisional GO\n" + "".join(l + "\n" for l in lines),
                                encoding="utf-8")

    def rounds(self, n, *rounds):
        """Round records (number, head, verdict, {overrides}) as `_keep_and_post` writes them."""
        d = self.reviews / "owner" / "repo" / ("pr%d" % n)
        d.mkdir(parents=True, exist_ok=True)
        for number, head, verdict, *more in rounds:
            record = {"repo": REPO, "pr": n, "round": number, "head_sha": head, "base": "main", "reviewer": "codex",
                      "model": None, "kind": "codex", "verdict": verdict, "status": "posted",
                      "author": "worker-a", "ts": AT, "attempts": []}
            record.update(more[0] if more else {})
            (d / ("round%02d.json" % number)).write_text(json.dumps(record), encoding="utf-8")
            (d / ("round%02d.out" % number)).write_text("the review\n", encoding="utf-8")

    def text(self):
        return self.tracker.read_text(encoding="utf-8")

    def entries(self):
        return br.provisional_entries(self.text())

    def blockers(self):
        return [ln for ln in tracker.blocker_lines(self.text()) if ln.startswith("- ")]

    def alerts(self):
        return [c.argv for c in self.sb.calls_of("boss-alert")]

    def codex_heads(self):
        path = self.sb.side / "codex-heads"
        return path.read_text().split() if path.exists() else []

    def run_pass(self, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            lines = rk.recheck("t", REPO, str(self.checkout), **kw)
        self.stderr = err.getvalue()
        return lines

    def worktrees(self):
        return [ln for ln in git(self.sb, self.checkout, "worktree", "list", "--porcelain").splitlines()
                if ln.startswith("worktree ")]

    def assertCheckoutUntouched(self):
        self.assertEqual(git(self.sb, self.checkout, "rev-parse", "HEAD"), self.checkout_head)
        self.assertEqual(git(self.sb, self.checkout, "status", "--porcelain"), "")
        self.assertEqual((self.checkout / "f.txt").read_text(), "main\n")
        self.assertEqual(len(self.worktrees()), 1, "the temporary worktree is gone")
        self.assertEqual(list(self.sb.tmp.glob("boss-recheck-*")), [])


class ThePass(Base):
    def test_three_entries_where_the_middle_review_times_out(self):
        heads = [self.pr(n, "pr%d" % n, answer=GO) for n in (5, 6, 7)]
        self.hang_on(heads[1])
        self.put(*(self.prov(n, h) for n, h in zip((5, 6, 7), heads)))
        for n, h in zip((5, 6, 7), heads):
            self.rounds(n, (1, h, None, {"kind": "provisional"}))
        lines = self.run_pass(codex_timeout=2)
        self.assertEqual(lines, [])
        self.assertEqual([e.pr for e in self.entries()], [6], self.stderr)      # 5 and 7 were cleared, 6 stays
        self.assertEqual(sorted(self.codex_heads()), sorted(heads))
        for n in (5, 7):
            self.assertEqual(json.loads((self.reviews / "owner/repo" / ("pr%d" % n) / "round02.json").read_text())
                             ["verdict"], "GO")
        self.assertEqual(self.sb.calls_of("claude"), [])
        self.assertCheckoutUntouched()

    def test_a_merged_pr_whose_branch_moved_is_reviewed_at_its_merged_head_in_a_detached_worktree(self):
        merged = self.pr(5, "merged head", state="MERGED", answer=GO)
        self.put(self.prov(5, merged))
        self.rounds(5, (1, merged, None, {"kind": "provisional"}))
        # the source branch is advanced after the merge: the commits exist in origin and nowhere in the PR's ref
        git(self.sb, self.dev, "checkout", "-q", "-b", "feature", merged)
        git(self.sb, self.dev, "commit", "-q", "--allow-empty", "-m", "after the merge")
        git(self.sb, self.dev, "push", "-q", "origin", "feature")
        self.run_pass()
        self.assertEqual(self.codex_heads(), [merged])
        (where,) = (self.sb.side / "codex-dirs").read_text().split()
        self.assertNotEqual(os.path.realpath(where), os.path.realpath(self.checkout))
        self.assertFalse(Path(where).is_relative_to(self.checkout))
        self.assertEqual(self.entries(), [])
        self.assertCheckoutUntouched()
        self.assertEqual((self.sb.side / "codex-dirty").read_text(), "")
        comments = [c for c in self.sb.calls_of("gh") if c.argv[:2] == ["pr", "comment"]]
        self.assertEqual(len(comments), 1)
        self.assertIn("Head: " + merged, comments[0].argv[-1])

    def test_the_worktree_is_gone_when_the_review_fails(self):
        head = self.pr(5, "no answer")
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        self.run_pass()
        self.assertEqual(self.codex_heads(), [head])
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertCheckoutUntouched()

    def test_a_fetch_that_fails_leaves_the_entry_and_goes_on(self):
        a = self.pr(5, "no pull ref", answer=GO, pull_ref=False)
        b = self.pr(6, "has one", answer=GO)
        self.put(self.prov(5, a), self.prov(6, b))
        self.rounds(5, (1, a, None, {"kind": "provisional"}))
        self.rounds(6, (1, b, None, {"kind": "provisional"}))
        self.run_pass()
        self.assertEqual(self.codex_heads(), [b])
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertIn("#5", self.stderr)
        self.assertCheckoutUntouched()

    def test_a_pr_closed_without_a_merge_is_not_reviewed_and_keeps_its_entry(self):
        head = self.pr(5, "closed", state="CLOSED", answer=GO)
        other = self.pr(6, "open", answer=GO)
        self.put(self.prov(5, head), self.prov(6, other))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        self.rounds(6, (1, other, None, {"kind": "provisional"}))
        self.run_pass()
        self.assertEqual(self.codex_heads(), [other])
        self.assertEqual([e.pr for e in self.entries()], [5])

    def test_a_state_that_cannot_be_read_makes_no_review_and_the_pass_goes_on(self):
        a = self.pr(5, "unreadable", answer=GO)
        b = self.pr(6, "readable", answer=GO)
        self.put(self.prov(5, a), self.prov(6, b))
        self.rounds(5, (1, a, None, {"kind": "provisional"}))
        self.rounds(6, (1, b, None, {"kind": "provisional"}))
        self.fail_view(5)
        self.run_pass()
        self.assertEqual(self.codex_heads(), [b])
        self.assertEqual([e.pr for e in self.entries()], [5])

    def test_a_merged_pr_is_reviewed_at_the_merged_head_not_the_entrys(self):
        a = self.pr(5, "head A", state="MERGED", answer=GO)
        b = self.pr(5, "head B", state="MERGED", answer=NOGO)    # b is what the entry names; the PR merged a
        self.set_pr(5, headRefOid=a)
        git(self.sb, self.dev, "push", "-q", "origin", "%s:refs/pull/5/head" % a, "--force")
        self.put(self.prov(5, b, round=2))
        self.rounds(5, (1, a, None, {"kind": "provisional"}), (2, b, None, {"kind": "provisional"}))
        self.run_pass()
        self.assertEqual(self.codex_heads(), [a])
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.blockers(), [])

    def test_an_open_pr_whose_head_moves_before_the_review_ends_with_the_reviews_refusal(self):
        head = self.pr(5, "will move", answer=GO)
        later = self.pr(6, "later", answer=GO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        self.set_pr(5, headRefOid=head)
        real = rk._worktree

        @contextlib.contextmanager
        def moving(*args, **kw):
            with real(*args, **kw) as path:
                self.set_pr(5, headRefOid=later)
                yield path

        with mock.patch.object(rk, "_worktree", moving):
            self.run_pass()
        self.assertEqual(self.codex_heads(), [])
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertIn("not the head of the PR", self.stderr)
        self.assertCheckoutUntouched()

    def test_another_repos_entries_are_left_alone(self):
        head = self.pr(5, "mine", answer=GO)
        other = "- [prov owner/other#9] head=%s round=01 base=main at=%s" % ("c" * 40, AT)
        self.put(self.prov(5, head), other)
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        self.run_pass()
        self.assertEqual([e.repo for e in self.entries()], ["owner/other"])
        self.assertEqual(self.codex_heads(), [head])

    def test_leftover_worktrees_of_an_earlier_pass_are_pruned_first(self):
        leftover = self.sb.tmp / "boss-recheck-old"
        git(self.sb, self.checkout, "worktree", "add", "-q", "--detach", str(leftover))
        self.assertEqual(len(self.worktrees()), 2)
        self.run_pass()
        self.assertEqual(len(self.worktrees()), 1)
        self.assertFalse(leftover.exists())

    def test_a_worktree_that_is_not_the_recheck_s_is_not_touched(self):
        mine = self.sb.work / "someone-elses"
        git(self.sb, self.checkout, "worktree", "add", "-q", "--detach", str(mine))
        self.run_pass()
        self.assertEqual(len(self.worktrees()), 2)
        self.assertTrue(mine.exists())

    def test_an_exception_inside_the_review_removes_the_worktree_and_the_pass_goes_on(self):
        a = self.pr(5, "raises", answer=GO)
        b = self.pr(6, "fine", answer=GO)
        self.put(self.prov(5, a), self.prov(6, b))
        self.rounds(5, (1, a, None, {"kind": "provisional"}))
        self.rounds(6, (1, b, None, {"kind": "provisional"}))
        real = br.review

        def review(repo, pr, *args, **kw):
            if pr == 5:
                raise RuntimeError("boom")
            return real(repo, pr, *args, **kw)

        with mock.patch.object(br, "review", review):
            self.run_pass()
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertIn("RuntimeError: boom", self.stderr)
        self.assertEqual(self.codex_heads(), [b])
        self.assertCheckoutUntouched()

    def test_a_second_pass_on_the_same_repo_does_nothing_and_removes_no_worktree(self):
        head = self.pr(5, "good", answer=GO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        running = self.sb.tmp / "boss-recheck-running"
        git(self.sb, self.checkout, "worktree", "add", "-q", "--detach", str(running))
        self.reviews.mkdir(parents=True, exist_ok=True)
        with open(self.reviews / ".recheck-owner-repo.lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            lines = self.run_pass()
        self.assertEqual(lines, [])
        self.assertIn("another recheck", self.stderr)
        self.assertTrue(running.exists())
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertEqual(self.sb.calls_of("gh") + self.sb.calls_of("codex"), [])
        self.run_pass()                                  # the lock is let go: the pass runs
        self.assertEqual(self.entries(), [])
        self.assertFalse(running.exists())

    def test_a_pass_with_no_list_does_nothing(self):
        self.assertEqual(self.run_pass(), [])
        self.assertEqual(self.sb.calls_of("gh") + self.sb.calls_of("codex"), [])


class TheNoGo(Base):
    def test_a_no_go_on_an_open_pr_is_printed_and_keeps_the_entry(self):
        head = self.pr(5, "bad", answer=NOGO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional", "author": "worker-z"}))
        lines = self.run_pass()
        self.assertEqual(lines, ["NO-GO owner/repo#5 round 02 author=worker-z"])
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertEqual((self.blockers(), self.alerts()), ([], []))
        self.assertEqual(json.loads((self.reviews / "owner/repo/pr5/round02.json").read_text())["author"], "recheck")

    def test_a_no_go_on_a_merged_pr_is_a_blocker_the_ladder_raises_and_a_dispatch_line(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional", "author": "worker-z"}))
        lines = self.run_pass()
        self.assertEqual(lines, ["DISPATCH owner/repo#5 author=worker-z round=02"])
        self.assertEqual(self.entries(), [])
        (line,) = self.blockers()
        token, fields = tracker.scan_marker(line)
        marker = tracker.validate(fields)
        self.assertTrue(re.fullmatch(r"fx[0-9a-f]{8}", marker["id"]), marker["id"])
        self.assertTrue(line.startswith("- Codex NO-GO on merged owner/repo#5 (round 02) - T+0 "), line)
        self.assertEqual(marker["next"] - marker["t0"], timedelta(minutes=5))
        self.assertEqual((marker["last"], marker["cleared"]), (0, ""))
        self.assertIn("pm/reviews/owner/repo/pr5/round02.out", marker["ask"])
        self.assertIn("worker-z", marker["ask"])
        self.assertEqual(len(tracker.open_blockers(self.text())), 1)
        lo, hi = tracker.blockers_range(self.text().split("\n"))
        self.assertTrue(lo <= self.text().split("\n").index(line) < hi)
        self.assertEqual([a[0] for a in self.alerts()], ["0"])
        self.assertIn("owner/repo#5", self.alerts()[0][1])
        # the ladder raises it at rung 5 with no boss turn
        (self.sb.cfg / "pm" / "t.goal.md").write_text("# Objective - t\n_Status: OPEN_\n", encoding="utf-8")
        ladder_alert = self.sb.stub("boss-alert-ladder")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
        env.update(BOSS_ALERT=str(ladder_alert), CLAUDE_CONFIG_DIR=str(self.sb.cfg), HOME=str(self.sb.home))
        run = subprocess.run([sys.executable, str(LADDER), "--now", (marker["t0"] + timedelta(minutes=6)).isoformat()],
                             env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual([c.argv[0] for c in self.sb.calls_of("boss-alert-ladder")], ["5"], run.stdout)
        self.assertEqual(self.sb.calls_of("claude"), [])

    def blocker_id(self, n, round):
        return rk.blocker_id(REPO, n, round)

    def blocker_line(self, n, round, cleared=False):
        t0 = tracker.parse_ts("2026-11-12T10:00+00:00", "t0")
        marker = tracker.render_marker(self.blocker_id(n, round), t0, t0 + timedelta(minutes=5), ask="x")
        line = "- Codex NO-GO on merged owner/repo#%d (round %02d) - T+0 2026-11-12T10:00+00:00 %s" % (n, round, marker)
        return tracker.mark_cleared(line, t0 + timedelta(minutes=30)) if cleared else line

    def test_the_id_is_per_round_and_per_pr(self):
        ids = {self.blocker_id(5, 2), self.blocker_id(5, 3), self.blocker_id(6, 2)}
        self.assertEqual(len(ids), 3)
        self.assertTrue(all(re.fullmatch(r"fx[0-9a-f]{8}", i) for i in ids))

    def crashed(self, n, head, no_go_status="posted", blocker=None):
        """A pass that wrote its NO-GO round (2) and died before the entry was removed."""
        self.put(self.prov(n, head), blockers=(blocker or "") and blocker + "\n")
        self.rounds(n, (1, head, None, {"kind": "provisional", "author": "worker-z"}),
                    (2, head, "NO-GO", {"status": no_go_status, "author": "recheck"}))

    def test_a_crash_after_the_blocker_and_before_the_removal_adds_no_second_one(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.crashed(5, head, blocker=self.blocker_line(5, 2))
        lines = self.run_pass()
        self.assertEqual(self.codex_heads(), [])
        self.assertEqual(len(self.sb.calls_of("codex")), 0)
        self.assertEqual(self.entries(), [])
        self.assertEqual(len(self.blockers()), 1)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(lines, ["DISPATCH owner/repo#5 author=worker-z round=02"])
        self.assertEqual(sorted(p.name for p in (self.reviews / "owner/repo/pr5").iterdir()),
                         ["round01.json", "round01.out", "round02.json", "round02.out"])

    def test_a_post_failed_no_go_above_the_entry_with_no_blocker_yet_is_resumed_not_reviewed_again(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.crashed(5, head, no_go_status="post-failed")
        lines = self.run_pass()
        self.assertEqual(len(self.sb.calls_of("codex")), 0)
        self.assertEqual(self.entries(), [])
        (line,) = self.blockers()
        self.assertIn("(round 02)", line)
        self.assertEqual([a[0] for a in self.alerts()], ["0"])
        self.assertEqual(lines, ["DISPATCH owner/repo#5 author=worker-z round=02"])

    def test_the_same_rounds_retry_after_its_blocker_was_cleared_adds_no_line_and_no_alert(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.crashed(5, head, blocker=self.blocker_line(5, 2, cleared=True))
        self.run_pass()
        self.assertEqual(len(self.blockers()), 1)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(self.entries(), [])
        self.assertEqual(len(self.sb.calls_of("codex")), 0)

    def test_a_second_no_go_on_the_pr_after_the_first_was_cleared_is_a_new_blocker_and_an_alert(self):
        head = self.pr(5, "bad again", state="MERGED", answer=NOGO)
        self.put(self.prov(5, head, round=3), blockers=self.blocker_line(5, 2, cleared=True) + "\n")
        self.rounds(5, (1, head, None, {"kind": "provisional"}), (2, head, "NO-GO", {"author": "recheck"}),
                    (3, head, None, {"kind": "provisional", "author": "worker-y"}))
        lines = self.run_pass()
        self.assertEqual(lines, ["DISPATCH owner/repo#5 author=worker-y round=04"])
        found = self.blockers()
        self.assertEqual(len(found), 2)
        self.assertIn("(round 04)", found[1])
        self.assertNotEqual(tracker.scan_marker(found[0])[1]["id"], tracker.scan_marker(found[1])[1]["id"])
        self.assertEqual([a[0] for a in self.alerts()], ["0"])
        self.assertEqual(self.entries(), [])

    def test_an_entry_replaced_between_the_read_and_the_removal_stays(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        newer = self.prov(5, head).replace(AT, "2026-11-12T11:00:00Z")      # differs in at= only: a whole-line compare
        real = rk._add_blocker

        def add_then_replace(*args, **kw):
            got = real(*args, **kw)
            self.tracker.write_text(self.text().replace(self.prov(5, head), newer), encoding="utf-8")
            return got

        with mock.patch.object(rk, "_add_blocker", add_then_replace):
            lines = self.run_pass()
        self.assertEqual([e.line for e in self.entries()], [newer])
        self.assertEqual(len(self.blockers()), 1)
        self.assertEqual(lines, ["DISPATCH owner/repo#5 author=worker-a round=02"])

    def test_a_blocker_write_that_fails_leaves_the_entry(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        with mock.patch.object(tracker, "add_line", return_value="failed: lock held past the deadline"):
            lines = self.run_pass()
        self.assertEqual([e.pr for e in self.entries()], [5])
        self.assertEqual((self.blockers(), self.alerts(), lines), ([], [], []))
        self.assertIn("lock held past the deadline", self.stderr)

    def test_a_failed_alert_does_not_undo_the_blocker(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        self.sb.stub("boss-alert", rc=1)
        self.run_pass()
        self.assertEqual(len(self.blockers()), 1)
        self.assertEqual(self.entries(), [])


class TheCommand(Base):
    def run_cli(self, *args, track="t"):
        return subprocess.run([sys.executable, str(HERE / "boss_recheck.py"), "--track", track, "--repo", REPO,
                               "--checkout", str(self.checkout), *args],
                              env=dict(os.environ), capture_output=True, text=True, timeout=120)

    def test_the_command_prints_the_lines_and_exits_0(self):
        head = self.pr(5, "bad", state="MERGED", answer=NOGO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional", "author": "worker-z"}))
        run = self.run_cli("--author", "rita")
        self.assertEqual((run.returncode, run.stdout), (0, "DISPATCH owner/repo#5 author=worker-z round=02\n"), run.stderr)
        self.assertEqual(json.loads((self.reviews / "owner/repo/pr5/round02.json").read_text())["author"], "rita")

    def test_the_author_defaults_to_recheck(self):
        head = self.pr(5, "good", answer=GO)
        self.put(self.prov(5, head))
        self.rounds(5, (1, head, None, {"kind": "provisional"}))
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(json.loads((self.reviews / "owner/repo/pr5/round02.json").read_text())["author"], "recheck")

    def test_an_unusable_track_is_exit_2_and_says_no_blocker_can_be_rechecked(self):
        run = self.run_cli(track="nope")
        self.assertEqual(run.returncode, 2)
        self.assertIn("no blocker can be rechecked", run.stderr)
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_symlinked_tracker_is_unusable(self):
        real = self.sb.cfg / "pm" / "real.md"
        real.write_text(TRACKER)
        (self.sb.cfg / "pm" / "ln.md").symlink_to(real)
        run = self.run_cli(track="ln")
        self.assertEqual(run.returncode, 2)
        self.assertIn("no blocker can be rechecked", run.stderr)

    def test_bad_arguments_are_exit_2(self):
        base = {"--track": "t", "--repo": REPO, "--checkout": str(self.checkout)}
        for what, change in (("author with a space", {"--author": "a b"}), ("empty author", {"--author": ""}),
                             ("repo not OWNER/REPO", {"--repo": "nope"}),
                             ("a checkout that is no directory", {"--checkout": str(self.sb.work / "missing")}),
                             ("a track that is not plain", {"--track": "../x"})):
            with self.subTest(what=what):
                args = [x for kv in {**base, **change}.items() for x in kv]
                run = subprocess.run([sys.executable, str(HERE / "boss_recheck.py"), *args], env=dict(os.environ),
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 2, run.stderr)

    def test_a_missing_option_is_exit_2(self):
        run = subprocess.run([sys.executable, str(HERE / "boss_recheck.py"), "--track", "t"], env=dict(os.environ),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 2)

    def test_a_tracker_that_cannot_be_read_as_text_is_exit_7(self):
        self.tracker.write_bytes(b"\xff\xfe\x00bad")
        run = self.run_cli()
        self.assertEqual(run.returncode, 7)


class TheList(Base):
    """`--list` (ticket 10b): the entries that count, exit 1 when there is one. It reads each entry's state with
    `_live_state` (the prune reads it too, as the pass does) and makes no `review(...)` call: `codex` is never started."""

    def tearDown(self):
        self.sb.guard()
        self.assertEqual(self.sb.calls_of("claude"), [])
        self.assertEqual(self.sb.calls_of("codex"), [], "--list starts no review")
        for call in self.sb.calls_of("gh"):
            self.assertEqual(call.argv[:2], ["pr", "view"], "--list only reads states")

    def run_list(self, *args, track="t"):
        run = subprocess.run([sys.executable, str(HERE / "boss_recheck.py"), "--track", track, "--list", *args],
                             env=dict(os.environ), capture_output=True, text=True, timeout=120)
        self.assertEqual(self.codex_heads(), [], "--list started codex")
        return run

    def provisional(self, n, state="OPEN", answer=None):
        head = self.pr(n, "pr%d" % n, state=state, answer=answer)
        self.rounds(n, (1, head, None, {"kind": "provisional"}))
        return head

    def test_an_empty_list_exits_0_and_prints_nothing(self):
        self.put()
        run = self.run_list()
        self.assertEqual((run.returncode, run.stdout), (0, ""), run.stderr)
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_tracker_with_no_provisional_section_exits_0(self):
        run = self.run_list()
        self.assertEqual((run.returncode, run.stdout), (0, ""), run.stderr)

    def test_an_open_entry_counts_and_is_printed(self):
        head = self.provisional(5)
        self.put(self.prov(5, head))
        run = self.run_list()
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(run.stdout, "PROVISIONAL owner/repo#5 round 01 state=OPEN head=%s\n" % head)
        self.assertEqual([e.pr for e in self.entries()], [5])

    def test_a_merged_entry_counts(self):
        head = self.provisional(5, state="MERGED")
        self.put(self.prov(5, head))
        run = self.run_list()
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("state=MERGED", run.stdout)

    def test_a_list_holding_only_a_pr_closed_without_a_merge_exits_0_and_makes_no_review_call(self):
        head = self.provisional(5, state="CLOSED", answer=GO)
        self.put(self.prov(5, head))
        run = self.run_list()
        self.assertEqual((run.returncode, run.stdout), (0, ""), run.stderr)
        self.assertEqual([e.pr for e in self.entries()], [5], "the entry stays until the owner deletes the line")
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertEqual([c.argv[:2] for c in self.sb.calls_of("gh") if c.argv[:2] != ["pr", "view"]], [])

    def test_a_closed_entry_beside_an_open_one_prints_only_the_open_one(self):
        a = self.provisional(5, state="CLOSED")
        b = self.provisional(6)
        self.put(self.prov(5, a), self.prov(6, b))
        run = self.run_list()
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.stdout.splitlines(), ["PROVISIONAL owner/repo#6 round 01 state=OPEN head=%s" % b])

    def test_a_state_that_cannot_be_read_counts(self):
        head = self.provisional(5)
        self.put(self.prov(5, head))
        self.fail_view(5)
        run = self.run_list()
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(run.stdout, "PROVISIONAL owner/repo#5 round 01 state=unreadable head=%s\n" % head)
        self.assertEqual([e.pr for e in self.entries()], [5])

    def test_gh_is_only_ever_asked_for_the_state_of_each_entry(self):
        a, b = self.provisional(5), self.provisional(6)
        self.put(self.prov(5, a), self.prov(6, b))
        self.run_list("--repo", REPO)
        calls = [tuple(c.argv[:3]) for c in self.sb.calls_of("gh")]
        self.assertEqual({c[:2] for c in calls}, {("pr", "view")})
        # the prune reads each entry once (as the pass does), the list once more: two reads, never a review or a comment
        self.assertEqual(sorted(c[2] for c in calls), ["5", "5", "6", "6"])

    def test_an_entry_codex_has_since_cleared_does_not_count(self):
        head = self.pr(5, "cleared")
        self.rounds(5, (1, head, None, {"kind": "provisional"}), (2, head, "GO"))
        self.put(self.prov(5, head))
        run = self.run_list()
        self.assertEqual((run.returncode, run.stdout), (0, ""), run.stderr)
        self.assertEqual(self.entries(), [])

    def test_the_repo_option_limits_the_list_to_that_repo(self):
        head = self.provisional(5)
        self.put(self.prov(5, head), self.prov(9, "a" * 40, repo="owner/other"))
        self.set_pr(9, headRefOid="a" * 40)
        run = self.run_list("--repo", "owner/other")
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual([ln.split()[1] for ln in run.stdout.splitlines()], ["owner/other#9"])

    def test_without_repo_it_lists_every_repo_of_the_track(self):
        head = self.provisional(5)
        self.put(self.prov(5, head), self.prov(9, "a" * 40, repo="owner/other"))
        self.set_pr(9, headRefOid="a" * 40)
        run = self.run_list()
        self.assertEqual(sorted(ln.split()[1] for ln in run.stdout.splitlines()), ["owner/other#9", "owner/repo#5"])
        # the stub gh serves owner/repo only; the other repo's call is allowed to fail (state unreadable) and counts

    def test_an_unusable_track_is_exit_2(self):
        run = self.run_list(track="nope")
        self.assertEqual(run.returncode, 2)
        self.assertIn("no blocker can be", run.stderr)

    def test_a_tracker_that_cannot_be_read_as_text_is_exit_7(self):
        self.tracker.write_bytes(b"\xff\xfe\x00bad")
        self.assertEqual(self.run_list().returncode, 7)

    def test_list_takes_no_checkout_but_refuses_a_bad_repo(self):
        self.assertEqual(self.run_list("--repo", "nope").returncode, 2)

    def test_without_list_repo_and_checkout_are_still_required(self):
        run = subprocess.run([sys.executable, str(HERE / "boss_recheck.py"), "--track", "t"], env=dict(os.environ),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 2)


class TheSkillText(unittest.TestCase):
    """SKILL.md tells the boss to run the recheck, to dispatch on a DISPATCH line, and to stop on `--list`."""

    @classmethod
    def setUpClass(cls):
        cls.text = (HERE / "SKILL.md").read_text(encoding="utf-8")
        cls.flat = " ".join(cls.text.split())

    def test_the_trigger_is_named(self):
        self.assertIn("boss_recheck.py", self.text)
        self.assertRegex(self.flat, r"(?i)whenever a Codex review answers")
        self.assertRegex(self.flat, r"and at wrap-up")

    def test_the_dispatch_rule_is_named(self):
        self.assertRegex(self.flat, r"`DISPATCH <repo>#<N>[^`]*` line.{0,200}round file as the brief")

    def test_the_stop_covers_wrap_up_and_every_release_request(self):
        self.assertRegex(self.flat, r"--list` exits 1")
        for word in ("Phase E", "version bump", "tag", "publish", "reinstall"):
            self.assertIn(word, self.flat)

    def test_a_closed_pr_is_not_counted_and_its_entry_stays_until_the_owner_deletes_it(self):
        self.assertRegex(self.flat, r"CLOSED.{0,200}not counted")
        self.assertRegex(self.flat, r"owner deletes its `\[prov\]` line by hand")


if __name__ == "__main__":
    unittest.main()
