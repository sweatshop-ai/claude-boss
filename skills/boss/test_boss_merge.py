#!/usr/bin/env python3
"""Tests for boss_merge.py (ticket 04): the merge gate, hermetically.

Run: python3 -m pytest skills/boss/test_boss_merge.py

Every test goes through hermetic.Sandbox as test_boss_review.py does: `codex`, `claude`, `gh` and `boss-alert` are
stubs that log their argv, stdin and working directory; HOME and CLAUDE_CONFIG_DIR are temporary; TypeSafe has no
key to find. The `gh` stub keeps a PR in side/pr.json and answers `pr view`, `pr merge`, `pr comment`, `pr diff`
and `api` from side/gh.json (per kind, a list of per-call entries, the last one repeating). Round files are written
by hand for the rows of `decide`, and by the real writers (`review(..., allow_fallback=True, track=...)` and
`waive`) for the two end-to-end tests. Each test fails if `codex`, `claude` or `gh` resolves outside the stub
directory, if a `gh` call is not scoped to the repo, and if `codex` or `claude` was called at all.
"""
import base64
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_merge as bm  # noqa: E402
import boss_review as br  # noqa: E402
from boss_merge import Round  # noqa: E402
from hermetic import Sandbox  # noqa: E402
from test_boss_review import AUTHOR, BODY, DIFF, PR, REPO, TITLE  # noqa: E402
from test_boss_review_provisional import Base as ProvBase  # noqa: E402
import test_waiver  # noqa: E402

KEY = "owner/repo"
OWNER = (KEY, PR)
HEAD = "a" * 40
OTHER = "b" * 40
BASE_SHA = "d" * 40      # the base branch's tip when the gate reads it
MOVED_SHA = "e" * 40     # the tip after the base moved
MERGE_SHA = "f" * 40     # the merge commit
GONE = object()         # a field removed from a record

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


def patched(e, default=None):
    state = json.loads(state_file.read_text())
    change = e["patch"] if "patch" in e else (default or {})
    if change:
        state.update(change)
        state_file.write_text(json.dumps(state))
    return state


def finish(e):
    time.sleep(e.get("sleep", 0))
    sys.stderr.write(e.get("err", ""))
    sys.exit(e.get("rc", 0))


if argv[:2] == ["pr", "view"]:
    e = entry("view")
    state = patched(e)
    time.sleep(e.get("sleep", 0))
    if "raw" in e:
        sys.stdout.write(e["raw"])
    else:
        fields = argv[argv.index("--json") + 1].split(",")
        sys.stdout.write(json.dumps({f: state[f] for f in fields if f not in e.get("drop", [])}))
    finish({"rc": e.get("rc", 0), "err": e.get("err", "")})
if argv[:2] == ["pr", "merge"]:
    e = entry("merge")
    if e.get("probe"):       # what the gate holds while it merges: the PR's lock, and a line saying it is about to
        import fcntl
        try:
            fcntl.flock(open(e["probe"], "rb"), fcntl.LOCK_EX | fcntl.LOCK_NB)
            (side / "probe-lock").write_text("free")
        except BlockingIOError:
            (side / "probe-lock").write_text("held")
        log = Path(e["log"])
        (side / "probe-log").write_text(log.read_text() if log.exists() else "")
    patched(e, {"state": "MERGED"})
    finish(e)
if argv[:2] == ["pr", "diff"]:
    e = entry("diff")
    sys.stdout.write(patched(e)["diff"])
    finish(e)
if argv[:2] == ["pr", "comment"]:
    e = entry("comment")
    patched(e)
    finish(e)
if argv[0] == "api" and "/rules/branches/" in argv[1]:       # the base's rules (ticket 54): none unless a test says
    e = entry("rules")
    sys.stdout.write(e.get("raw", "[]"))
    finish(e)
if argv[:2] == ["api", "graphql"]:        # the base's merge queue and the PR's auto-merge state: none unless a test says
    e = entry("graphql")
    sys.stdout.write(e.get("raw", json.dumps({"data": {"repository": {"mergeQueue": None, "pullRequest": {
        "autoMergeRequest": None, "isInMergeQueue": False}}}})))
    finish(e)
if argv[0] == "api" and "/git/ref/heads/" in argv[1]:       # the base branch's tip (ticket 54)
    e = entry("ref")
    state = patched(e)
    sys.stdout.write(e["raw"] if "raw" in e else json.dumps({"object": {"sha": state["baseSha"]}}))
    finish(e)
if argv[0] == "api" and "/commits/" in argv[1] and "/check-runs" not in argv[1]:     # the merge commit's parents
    e = entry("commit")
    state = patched(e)
    sys.stdout.write(e["raw"] if "raw" in e else json.dumps({"parents": [{"sha": state["mergeParent"]}, {"sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}))
    finish(e)
if argv[0] == "api":
    e = entry("api")
    sys.stdout.write(e.get("raw", ""))
    finish(e)
sys.stderr.write("gh stub: no handler for %r\n" % (argv,))
sys.exit(64)
'''


def deploy_answer(conf, **extra):
    """What `gh api .../contents/.boss/deploy.json` prints for a file holding `conf` (JSON text, or an object)."""
    text = conf if isinstance(conf, str) else json.dumps(conf)
    return json.dumps(dict({"type": "file", "encoding": "base64",
                            "content": base64.encodebytes(text.encode()).decode()}, **extra))


GOOD_DEPLOY = {"version": 1, "non_deploying": ["main"], "test_paths": ["tests/*"]}
VALID_B64 = base64.b64encode(json.dumps({"version": 1, "non_deploying": ["main"]}).encode()).decode()


class MergeGh:
    """The `gh` stub and the PR it serves."""

    def __init__(self, sb, head):
        self.side = sb.side
        (self.side / "gh_handler.py").write_text(GH_HANDLER, encoding="utf-8")
        self.set_pr(number=PR, url="https://github.com/%s/pull/%d" % (REPO, PR), headRefOid=head,
                    baseRefName="main", state="OPEN", title=TITLE, body=BODY, diff=DIFF, baseSha=BASE_SHA,
                    mergeParent=BASE_SHA, mergeCommit={"oid": MERGE_SHA})
        self.configure()
        sb.stub_script("gh", 'exec python3 "$R/side/gh_handler.py" "$R/side" "$@"')

    def set_pr(self, **fields):
        path = self.side / "pr.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        state.update(fields)
        path.write_text(json.dumps(state), encoding="utf-8")

    def configure(self, **kinds):
        cfg = {"api": [{"raw": deploy_answer(GOOD_DEPLOY)}]}
        cfg.update(kinds)
        for counter in self.side.glob("count-*"):      # a new setting starts its lists from the first entry
            counter.unlink()
        (self.side / "gh.json").write_text(json.dumps(cfg), encoding="utf-8")


class Gate:
    """What the merge tests share: the sandbox, the stubs, the record writers and the calls to read back."""

    def setup_gate(self):
        self.reviews = self.sb.cfg / "pm" / "reviews"
        self.pr_dir = self.reviews / "owner" / "repo" / ("pr%d" % PR)
        self.alert = self.sb.stubs / "boss-alert"
        if not self.alert.exists():
            self.sb.stub("boss-alert")
        patcher = mock.patch.dict(os.environ, {"BOSS_ALERT": str(self.alert)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def gate_teardown(self):
        self.sb.guard()
        self.assertEqual(self.sb.calls_of("codex"), [], "codex was called")
        for call in self.sb.calls_of("gh"):
            argv = call.argv
            if argv[:2] == ["api", "graphql"]:
                continue
            if argv[0] == "pr":
                self.assertEqual(argv[argv.index("--repo") + 1].lower() if "--repo" in argv else None, KEY, argv)
            else:
                self.assertEqual(argv[0], "api", argv)
                self.assertTrue(argv[1].lower().startswith("repos/owner/repo/"), argv)

    # ------------------------------------------------------------------ records ----
    def make_record(self, n, **over):
        rec = {"repo": KEY, "pr": PR, "round": n, "head_sha": HEAD, "base": "main", "reviewer": "codex",
               "model": None, "kind": "codex", "verdict": "GO", "status": "posted", "author": AUTHOR,
               "ts": "2026-11-12T10:00:00Z", "attempts": []}
        rec.update(over)
        return {k: v for k, v in rec.items() if v is not GONE}

    def put(self, n, **over):
        self.pr_dir.mkdir(parents=True, exist_ok=True)
        (self.pr_dir / ("round%02d.json" % n)).write_text(json.dumps(self.make_record(n, **over)), encoding="utf-8")

    def raw(self, n, text):
        self.pr_dir.mkdir(parents=True, exist_ok=True)
        (self.pr_dir / ("round%02d.json" % n)).write_text(text, encoding="utf-8")

    # ------------------------------------------------------------------- calls ----
    def run_gate(self, dry_run=False, repo=REPO, pr=PR, **kw):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = bm.merge(repo, pr, dry_run=dry_run, **kw)
        self.err = err.getvalue()
        return code

    @staticmethod
    def _base_call(call):
        return call.argv[0] == "api" and (call.argv[1] == "graphql" or "/git/ref/heads/" in call.argv[1]
                                          or "/rules/branches/" in call.argv[1]
                                          or call.argv[1].endswith("/commits/" + MERGE_SHA))

    def gh_calls(self, *prefix):
        """The calls that start with `prefix`; the reads of the base's tip and of the merge commit are `base_calls`."""
        return [c for c in self.sb.calls_of("gh") if c.argv[:len(prefix)] == list(prefix) and not self._base_call(c)]

    def base_calls(self):
        return [c.argv[1] for c in self.sb.calls_of("gh") if self._base_call(c)]

    def merges(self):
        return self.gh_calls("pr", "merge")

    def log(self):
        path = self.reviews / "merges.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def last(self):
        return self.log()[-1]

    def alerts(self):
        return self.sb.calls_of("boss-alert")


class Base(Gate, unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        env = dict(self.sb.env, BOSS_TYPESAFE_ENV=str(self.sb.root / "no-typesafe.env"))
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(tempfile, "tempdir", str(self.sb.tmp))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gh = MergeGh(self.sb, HEAD)
        self.setup_gate()

    def tearDown(self):
        self.gate_teardown()
        self.assertEqual(self.sb.calls_of("claude"), [], "claude was called")


# ------------------------------------------------------------------------------ decide ----
def rounds(*records):
    return [Round(r.get("round", 1), r) for r in records]


class DecideRows(unittest.TestCase):
    """One test per row of the decision, on `decide` itself: no files, no `gh`."""

    def rec(self, n, **over):
        return Gate.make_record(self, n, **over)

    def decide(self, *records, head=HEAD, base="main", non_deploying=("main",)):
        return bm.decide(rounds(*records), head, base, frozenset(non_deploying), OWNER)

    def assertDecides(self, got, exit_code, reason, round_=None):
        self.assertEqual((got.exit, got.reason), (exit_code, reason), got)
        if round_ is not None:
            self.assertEqual(got.round, round_)

    def test_no_round_refuses(self):
        self.assertDecides(self.decide(), 3, "no-round")

    def test_a_codex_go_allows_on_any_base(self):
        for base in ("main", "release", "x"):
            with self.subTest(base=base):
                self.assertDecides(self.decide(self.rec(1, base=base), base=base, non_deploying=()), 0, "codex-go", 1)

    def test_a_codex_no_go_refuses(self):
        self.assertDecides(self.decide(self.rec(1, verdict="NO-GO")), 3, "no-go", 1)

    def test_an_older_go_under_a_newer_no_go_refuses(self):
        self.assertDecides(self.decide(self.rec(1), self.rec(2, verdict="NO-GO")), 3, "no-go", 2)

    def test_a_late_no_go_that_finished_after_a_go_is_numbered_higher_and_refuses(self):
        # two reviews ran at once; the NO-GO finished last, so it claimed the higher number
        self.assertDecides(self.decide(self.rec(2, verdict="NO-GO"), self.rec(1)), 3, "no-go", 2)

    def test_an_older_no_go_under_a_newer_go_allows(self):
        self.assertDecides(self.decide(self.rec(1, verdict="NO-GO"), self.rec(2)), 0, "codex-go", 2)

    def test_the_rounds_need_not_come_in_order(self):
        self.assertDecides(self.decide(self.rec(3, verdict="NO-GO"), self.rec(1), self.rec(2)), 3, "no-go", 3)

    def test_a_round_for_another_head_or_base_is_passed_over(self):
        self.assertDecides(self.decide(self.rec(1, head_sha=OTHER)), 3, "no-round")
        self.assertDecides(self.decide(self.rec(1, base="release")), 3, "no-round")      # retargeted after the review

    def test_a_go_on_the_live_head_under_a_round_for_another_head_still_decides(self):
        self.assertDecides(self.decide(self.rec(1), self.rec(2, head_sha=OTHER, verdict="NO-GO")), 0, "codex-go", 1)

    def test_head_moved_no_verdict_and_list_failed_rounds_are_passed_over(self):
        for status in ("head-moved", "no-verdict", "list-failed"):
            for verdict in ("GO", "NO-GO", None):
                with self.subTest(status=status, verdict=verdict):
                    self.assertDecides(self.decide(self.rec(1), self.rec(2, status=status, verdict=verdict)),
                                       0, "codex-go", 1)
                    self.assertDecides(self.decide(self.rec(2, status=status, verdict=verdict)), 3, "no-round")

    def test_a_post_failed_no_go_on_the_live_head_refuses(self):
        self.assertDecides(self.decide(self.rec(1), self.rec(2, status="post-failed", verdict="NO-GO")),
                           3, "unposted-no-go", 2)

    def test_a_later_round_supersedes_a_post_failed_no_go(self):
        self.assertDecides(self.decide(self.rec(1, status="post-failed", verdict="NO-GO"), self.rec(2)),
                           0, "codex-go", 2)

    def test_a_post_failed_no_go_on_another_head_is_passed_over(self):
        self.assertDecides(self.decide(self.rec(1), self.rec(2, head_sha=OTHER, status="post-failed",
                                                              verdict="NO-GO")), 0, "codex-go", 1)

    def test_a_post_failed_go_is_passed_over(self):
        self.assertDecides(self.decide(self.rec(1), self.rec(2, status="post-failed")), 0, "codex-go", 1)
        self.assertDecides(self.decide(self.rec(1, status="post-failed")), 3, "no-round")

    # ---------------------------------------------------------------- bad records ----
    def test_an_unreadable_newer_file_refuses_and_is_never_skipped(self):
        got = bm.decide([Round(1, self.rec(1)), Round(2, None)], HEAD, "main", frozenset(), OWNER)
        self.assertDecides(got, 3, "bad-record", 2)

    def test_a_bad_file_below_the_deciding_round_is_never_met(self):
        got = bm.decide([Round(1, None), Round(2, self.rec(2))], HEAD, "main", frozenset(), OWNER)
        self.assertDecides(got, 0, "codex-go", 2)

    def test_a_record_that_is_not_an_object_refuses(self):
        for junk in (None, [], "GO", 3, True):
            with self.subTest(junk=junk):
                self.assertDecides(bm.decide([Round(1, junk)], HEAD, "main", frozenset(), OWNER), 3, "bad-record")

    def test_a_record_missing_any_of_the_eight_fields_refuses(self):
        self.assertEqual(bm.FIELDS, ("repo", "pr", "round", "head_sha", "base", "kind", "verdict", "status"))
        for field in bm.FIELDS:
            with self.subTest(field=field):
                self.assertDecides(self.decide(self.rec(1, **{field: GONE})), 3, "bad-record", 1)

    def test_round_or_pr_that_is_not_an_exact_integer_refuses(self):
        for field in ("round", "pr"):
            for value in (str(1 if field == "round" else PR), float(1 if field == "round" else PR), True, None):
                with self.subTest(field=field, value=value):
                    got = bm.decide([Round(1, self.rec(1, **{field: value}))], HEAD, "main", frozenset(), OWNER)
                    self.assertDecides(got, 3, "bad-record")

    def test_a_bool_is_not_the_round_one(self):
        got = bm.decide([Round(1, self.rec(1, round=True))], HEAD, "main", frozenset(), OWNER)
        self.assertDecides(got, 3, "bad-record")

    def test_a_round_that_differs_from_its_file_name_refuses(self):
        got = bm.decide([Round(2, self.rec(1))], HEAD, "main", frozenset(), OWNER)
        self.assertDecides(got, 3, "bad-record")

    def test_a_record_of_another_repo_or_pr_refuses(self):
        self.assertDecides(self.decide(self.rec(1, repo="other/repo")), 3, "bad-record")
        self.assertDecides(self.decide(self.rec(1, repo="Owner/Repo")), 3, "bad-record")      # the key is lowercase
        self.assertDecides(self.decide(self.rec(1, pr=PR + 1)), 3, "bad-record")

    def test_a_head_or_base_that_is_not_a_string_refuses(self):
        self.assertDecides(self.decide(self.rec(1, head_sha=5)), 3, "bad-record")
        self.assertDecides(self.decide(self.rec(1, base=None)), 3, "bad-record")

    def test_an_unknown_verdict_kind_or_status_refuses(self):
        for field, value in (("verdict", "MAYBE"), ("verdict", "go"), ("verdict", ["GO"]), ("kind", "tests"),
                             ("kind", ["codex"]), ("kind", None), ("status", "done"), ("status", None),
                             ("status", ["posted"])):
            with self.subTest(field=field, value=value):
                self.assertDecides(self.decide(self.rec(1, **{field: value})), 3, "bad-record")

    def test_a_posted_round_with_a_null_verdict_refuses(self):
        self.assertDecides(self.decide(self.rec(1, verdict=None)), 3, "bad-record")

    def test_a_post_failed_round_with_a_null_verdict_refuses(self):
        self.assertDecides(self.decide(self.rec(1, status="post-failed", verdict=None)), 3, "bad-record")

    def test_a_file_name_of_4301_digits_is_a_round_with_no_number_and_raises_nothing(self):
        # such a name cannot be created on the target filesystems (ticket 25), so the parser is tested alone
        self.assertEqual(bm.file_round("round" + "9" * 4301 + ".json"), (True, None))
        self.assertEqual(bm.file_round("round" + "9" * 4300 + ".json")[0], True)
        self.assertDecides(bm.decide([Round(None, None), Round(1, self.rec(1))], HEAD, "main", frozenset(), OWNER),
                           3, "bad-record")

    def test_only_round_json_files_are_rounds(self):
        for name in ("round01.out", "round.json", ".round-abc", "round01.json.tmp", "xround01.json", "round-1.json",
                     "round٣.json"):
            with self.subTest(name=name):
                self.assertEqual(bm.file_round(name), (False, None))
        self.assertEqual(bm.file_round("round07.json"), (True, 7))
        self.assertEqual(bm.file_round("round100.json"), (True, 100))

    # ---------------------------------------------------- provisional and waived GO ----
    def test_a_provisional_or_waived_go_allows_only_on_a_listed_base(self):
        for kind in ("provisional", "waived"):
            with self.subTest(kind=kind):
                self.assertDecides(self.decide(self.rec(1, kind=kind)), 0, kind + "-go-non-deploying", 1)
                self.assertDecides(self.decide(self.rec(1, kind=kind), non_deploying=()), 4, "deploying-base", 1)
                self.assertDecides(self.decide(self.rec(1, kind=kind), non_deploying=("release",)),
                                   4, "deploying-base", 1)

    def test_a_provisional_no_go_refuses_on_any_base(self):
        self.assertDecides(self.decide(self.rec(1, kind="provisional", verdict="NO-GO")), 3, "no-go", 1)

    def test_a_provisional_go_that_a_later_round_of_any_status_supersedes_refuses(self):
        for status in ("head-moved", "no-verdict", "list-failed"):
            for kind in ("provisional", "waived"):
                with self.subTest(status=status, kind=kind):
                    self.assertDecides(self.decide(self.rec(1, kind=kind), self.rec(2, status=status, kind=kind)),
                                       3, "superseded-go", 1)

    def test_a_later_round_on_another_base_supersedes_a_provisional_go(self):
        # a provisional GO on main (round 1), then a round for the same head on a release base (a retarget)
        for kind in ("provisional", "waived"):
            with self.subTest(kind=kind):
                got = self.decide(self.rec(1, kind=kind), self.rec(2, kind=kind, base="release"))
                self.assertDecides(got, 3, "superseded-go", 1)

    def test_a_later_post_failed_go_on_the_same_head_supersedes_a_provisional_go(self):
        for kind in ("provisional", "waived"):
            with self.subTest(kind=kind):
                got = self.decide(self.rec(1, kind=kind), self.rec(2, kind=kind, status="post-failed"))
                self.assertDecides(got, 3, "superseded-go", 1)

    def test_a_later_post_failed_go_on_another_head_supersedes_a_provisional_go(self):
        # a provisional GO on A (round 1), a provisional GO on B post-failed (round 2), a force-push back to A
        got = self.decide(self.rec(1, kind="provisional"),
                          self.rec(2, kind="provisional", head_sha=OTHER, status="post-failed"))
        self.assertDecides(got, 3, "superseded-go", 1)

    def test_a_codex_go_on_another_head_supersedes_a_provisional_go(self):
        got = self.decide(self.rec(1, kind="provisional"), self.rec(2, head_sha=OTHER))
        self.assertDecides(got, 3, "superseded-go", 1)

    def test_a_later_round_does_not_supersede_a_codex_go(self):
        for status in ("head-moved", "no-verdict", "list-failed"):
            with self.subTest(status=status):
                self.assertDecides(self.decide(self.rec(1), self.rec(2, head_sha=OTHER), self.rec(3, status=status)),
                                   0, "codex-go", 1)

    def test_a_provisional_go_above_a_codex_go_decides_first_and_the_codex_go_is_never_met(self):
        # intended, fail closed: a later provisional or waived round means the PR was judged again by something weaker
        base = [self.rec(1), self.rec(2, kind="provisional")]
        self.assertDecides(self.decide(*base, self.rec(3, status="head-moved")), 3, "superseded-go", 2)
        self.assertDecides(self.decide(*base), 0, "provisional-go-non-deploying", 2)
        self.assertDecides(self.decide(*base, non_deploying=()), 4, "deploying-base", 2)


# --------------------------------------------------------------------------- the files ----
class ReadRounds(Base):
    def test_files_are_read_with_their_numbers(self):
        self.put(1)
        self.put(10, verdict="NO-GO")
        (self.pr_dir / "round01.out").write_text("raw", encoding="utf-8")
        (self.pr_dir / ".lock").write_text("", encoding="utf-8")
        got = sorted(bm.read_rounds(self.pr_dir), key=lambda r: r.number)
        self.assertEqual([r.number for r in got], [1, 10])
        self.assertEqual(got[1].record["verdict"], "NO-GO")

    def test_no_directory_holds_no_round(self):
        self.assertEqual(bm.read_rounds(self.pr_dir), [])

    def test_a_directory_that_cannot_be_listed_is_one_bad_round(self):
        with mock.patch.object(bm.os, "listdir", side_effect=PermissionError("no")):
            self.assertEqual(bm.read_rounds(self.pr_dir), [Round(None, None)])

    def test_empty_not_json_and_deeply_nested_files_are_bad_records(self):
        for text in ("", "not json", "[" * 200000, "\xff", "null", "{"):
            with self.subTest(text=text[:10]):
                self.raw(1, text)
                (r,) = bm.read_rounds(self.pr_dir)
                self.assertEqual(r.number, 1)
                self.assertIsNone(bm._valid(r, OWNER))

    def test_bytes_that_are_not_utf8_are_a_bad_record(self):
        self.pr_dir.mkdir(parents=True)
        (self.pr_dir / "round01.json").write_bytes(b"\xff\xfe{}")
        (r,) = bm.read_rounds(self.pr_dir)
        self.assertIsNone(r.record)

    def test_a_directory_or_a_link_named_like_a_round_is_a_bad_record(self):
        self.pr_dir.mkdir(parents=True)
        (self.pr_dir / "round01.json").mkdir()
        self.put(2)
        (self.pr_dir / "round02.json").rename(self.sb.side / "elsewhere.json")
        (self.pr_dir / "round02.json").symlink_to(self.sb.side / "elsewhere.json")
        got = {r.number: r.record for r in bm.read_rounds(self.pr_dir)}
        self.assertEqual(got, {1: None, 2: None})

    def test_two_files_for_one_number_are_neither_read(self):
        self.put(1)
        (self.pr_dir / "round1.json").write_text(json.dumps(self.make_record(1, verdict="NO-GO")), encoding="utf-8")
        got = bm.read_rounds(self.pr_dir)
        self.assertEqual(sorted((r.number, r.record) for r in got), [(1, None), (1, None)])
        self.assertEqual(self.run_gate(dry_run=True), 3)
        self.assertEqual(self.last()["reason"], "bad-record")

    def test_a_round_file_in_the_gate_is_refused_with_no_traceback(self):
        self.put(1)
        self.raw(2, "[" * 200000)
        self.assertEqual(self.run_gate(dry_run=True), 3)
        self.assertEqual(self.last()["reason"], "bad-record")
        self.assertNotIn("Traceback", self.err)
        self.assertEqual(self.merges(), [])


# ----------------------------------------------------------------------- the deploy list ----
class DeployList(Base):
    def answer(self, raw=None, rc=0, err=""):
        entry = {"rc": rc, "err": err}
        if raw is not None:
            entry["raw"] = raw
        self.gh.configure(api=[entry])

    def provisional(self):
        self.put(1, kind="provisional")

    def test_the_line_breaks_github_puts_in_the_encoding_are_fine(self):
        names = ["branch-%02d" % i for i in range(40)] + ["main"]
        answer = deploy_answer({"version": 1, "non_deploying": names})
        self.assertGreater(json.loads(answer)["content"].count("\n"), 3)
        self.assertEqual(bm.parse_deploy(answer.encode()).non_deploying, frozenset(names))

    def test_a_good_file_lists_main(self):
        got = bm.parse_deploy(deploy_answer(GOOD_DEPLOY).encode())
        self.assertEqual((got.state, got.non_deploying, got.test_paths), ("ok", frozenset({"main"}), ("tests/*",)))
        got = bm.parse_deploy(deploy_answer({"version": 1, "non_deploying": []}).encode())
        self.assertEqual((got.state, got.non_deploying, got.test_paths), ("ok", frozenset(), None))
        self.assertIsNone(got.required_checks)
        got = bm.parse_deploy(deploy_answer(dict(GOOD_DEPLOY, required_checks=["test", "lint"])).encode())
        self.assertEqual(got.required_checks, ("test", "lint"))

    def test_every_failure_mode_makes_every_branch_deploy(self):
        conf = lambda **kw: deploy_answer(dict(GOOD_DEPLOY, **kw))       # noqa: E731
        cases = [
            ("unreadable", dict(rc=1, err="HTTP 500")),
            ("missing", dict(rc=1, err="gh: Not Found (HTTP 404)")),
            ("bad-content", dict(raw="")),
            ("bad-content", dict(raw="not json")),
            ("bad-content", dict(raw="[" * 200000)),
            ("bad-content", dict(raw=json.dumps([{"name": "deploy.json", "type": "file"}]))),      # a directory listing
            ("bad-content", dict(raw=json.dumps({"type": "dir"}))),                                # no content
            ("bad-content", dict(raw=json.dumps({"content": 5}))),
            ("bad-content", dict(raw=json.dumps({"content": "!!!not base64!!!"}))),
            ("bad-content", dict(raw=json.dumps({"content": base64.b64encode(b"\xff\xfe").decode()}))),
            # a corrupted answer that still holds a whole, valid file once its stray characters are dropped
            ("bad-content", dict(raw=json.dumps({"content": VALID_B64[:12] + "!" + VALID_B64[12:]}))),
            ("bad-content", dict(raw=json.dumps({"content": VALID_B64[:12] + " " + VALID_B64[12:]}))),
            ("bad-content", dict(raw=json.dumps({"content": VALID_B64[:12] + "-_" + VALID_B64[12:]}))),
            ("bad-content", dict(raw=json.dumps({"content": VALID_B64[:12] + "\r\n" + VALID_B64[12:]}))),
            ("not-json", dict(raw=deploy_answer("not json"))),
            ("not-json", dict(raw=deploy_answer("[" * 200000))),
            ("bad-version", dict(raw=deploy_answer(["main"]))),
            ("bad-version", dict(raw=deploy_answer({"non_deploying": ["main"]}))),
            ("bad-version", dict(raw=conf(version=2))),
            ("bad-version", dict(raw=conf(version="1"))),
            ("bad-version", dict(raw=conf(version=True))),
            ("bad-version", dict(raw=conf(version=1.0))),
            ("bad-non-deploying", dict(raw=conf(non_deploying="main"))),
            ("bad-non-deploying", dict(raw=conf(non_deploying=["main", 3]))),
            ("bad-non-deploying", dict(raw=conf(non_deploying={"main": True}))),
            ("bad-non-deploying", dict(raw=deploy_answer({"version": 1}))),
            ("bad-test-paths", dict(raw=conf(test_paths="tests/*"))),
            ("bad-test-paths", dict(raw=conf(test_paths=["tests/*", 1]))),
            ("bad-test-paths", dict(raw=conf(test_paths=None))),
            ("bad-required-checks", dict(raw=conf(required_checks="ci0"))),
            ("bad-required-checks", dict(raw=conf(required_checks=["ci0", 1]))),
            ("bad-required-checks", dict(raw=conf(required_checks=None))),
        ]
        for state, kw in cases:
            with self.subTest(state=state, answer=str(kw)[:60]):
                self.answer(**kw)
                self.provisional()
                before = len(self.log())
                self.assertEqual(self.run_gate(dry_run=True), 4, self.err)
                self.assertEqual((self.last()["config"], self.last()["reason"]), (state, "deploying-base"))
                self.assertEqual(len(self.log()), before + 1)
        self.assertEqual(self.merges(), [])

    def test_a_branch_is_non_deploying_by_exact_name_only(self):
        for listed in (["ma*"], ["Main"], ["main "], ["release/*"], ["origin/main"], []):
            with self.subTest(listed=listed):
                self.answer(raw=deploy_answer({"version": 1, "non_deploying": listed}))
                self.provisional()
                self.assertEqual(self.run_gate(dry_run=True), 4)

    def test_an_invalid_file_does_not_stop_a_codex_go(self):
        self.answer(rc=1, err="HTTP 404")
        self.put(1)
        self.assertEqual(self.run_gate(), 0, self.err)
        self.assertEqual((self.last()["config"], self.last()["decision"]), ("missing", "merged"))
        self.assertEqual(len(self.merges()), 1)

    def test_a_listed_base_allows_a_provisional_go(self):
        self.provisional()
        self.assertEqual(self.run_gate(dry_run=True), 0, self.err)
        self.assertEqual(self.last()["config"], "ok")

    def test_a_base_with_a_slash_is_one_percent_encoded_value(self):
        self.gh.set_pr(baseRefName="release/1.0")
        self.answer(raw=deploy_answer({"version": 1, "non_deploying": ["release/1.0"]}))
        self.put(1, kind="waived", base="release/1.0")
        self.assertEqual(self.run_gate(dry_run=True), 0, self.err)
        (call,) = self.gh_calls("api")
        self.assertEqual(call.argv, ["api", "repos/%s/contents/.boss/deploy.json?ref=release%%2F1.0" % REPO])

    def test_odd_branch_names_are_encoded_whole(self):
        self.gh.set_pr(baseRefName="a b#c?d&e=f%g")
        self.put(1, base="a b#c?d&e=f%g")
        self.assertEqual(self.run_gate(dry_run=True), 0, self.err)
        (call,) = self.gh_calls("api")
        self.assertTrue(call.argv[1].endswith("?ref=a%20b%23c%3Fd%26e%3Df%25g"), call.argv)

    def test_only_the_base_branch_is_asked_for_and_the_heads_own_file_changes_nothing(self):
        # the PR's head holds a deploy.json that lists its base; the stub serves only what the base holds (nothing)
        self.answer(rc=1, err="HTTP 404")
        self.provisional()
        self.assertEqual(self.run_gate(dry_run=True), 4)
        (call,) = self.gh_calls("api")
        self.assertEqual(call.argv, ["api", "repos/%s/contents/.boss/deploy.json?ref=main" % REPO])
        self.assertNotIn(HEAD, " ".join(call.argv))

    def test_a_slow_gh_api_is_unreadable_not_a_hang(self):
        self.gh.configure(api=[{"raw": deploy_answer(GOOD_DEPLOY), "sleep": 3}])
        self.provisional()
        self.assertEqual(self.run_gate(dry_run=True, io_timeout=0.4), 4)
        self.assertEqual(self.last()["config"], "unreadable")


# -------------------------------------------------------------------------- the command ----
class Command(Base):
    def test_a_codex_go_merges_with_the_exact_gh_call(self):
        self.put(1)
        self.assertEqual(self.run_gate(), 0, self.err)
        (call,) = self.merges()
        self.assertEqual(call.argv, ["pr", "merge", str(PR), "--repo", REPO, "--merge", "--match-head-commit", HEAD])
        self.assertNotIn("--delete-branch", call.argv)
        self.assertEqual(self.alerts(), [])
        self.assertEqual([c.argv[:2] for c in self.sb.calls_of("gh")],
                         [["pr", "view"], ["api", "repos/%s/git/ref/heads/main" % REPO],
                          ["api", self.gh_calls("api")[0].argv[1]], ["api", "repos/%s/rules/branches/main" % REPO],
                          ["api", "graphql"], ["api", "repos/%s/git/ref/heads/main" % REPO], ["pr", "merge"], ["pr", "view"], ["api", "repos/%s/commits/%s" % (REPO, MERGE_SHA)]])

    def test_the_gh_pr_view_reads_the_five_fields_once_and_the_three_after_the_merge(self):
        self.put(1)
        self.run_gate()
        first, second = self.gh_calls("pr", "view")
        self.assertEqual(first.argv[first.argv.index("--json") + 1], "number,url,headRefOid,baseRefName,state")
        self.assertEqual(second.argv[second.argv.index("--json") + 1], "baseRefName,state,mergeCommit")

    def test_dry_run_decides_and_logs_but_never_merges(self):
        self.put(1)
        self.assertEqual(self.run_gate(dry_run=True), 0, self.err)
        self.assertEqual(self.merges(), [])
        line = self.last()
        self.assertEqual((line["decision"], line["exit"], line["dry_run"]), ("allowed", 0, True))

    def test_the_repo_may_be_typed_in_any_case_and_the_directory_is_the_key(self):
        self.put(1)
        self.assertEqual(self.run_gate(repo="OWNER/Repo"), 0, self.err)
        (call,) = self.merges()
        self.assertEqual(call.argv[call.argv.index("--repo") + 1], "OWNER/Repo")      # gh gets it as typed
        self.assertEqual(self.last()["repo"], KEY)

    def test_no_round_a_no_go_and_a_bad_record_never_merge(self):
        for setup, reason in ((lambda: None, "no-round"), (lambda: self.put(1, verdict="NO-GO"), "no-go"),
                              (lambda: self.raw(2, ""), "bad-record")):
            with self.subTest(reason=reason):
                setup()
                self.assertEqual(self.run_gate(), 3)
                self.assertEqual((self.last()["decision"], self.last()["reason"], self.last()["exit"]),
                                 ("refused", reason, 3))
        self.assertEqual(self.merges(), [])

    def test_a_provisional_go_on_a_deploying_base_exits_4_and_never_merges(self):
        self.gh.configure(api=[{"raw": deploy_answer({"version": 1, "non_deploying": ["staging"]})}])
        self.put(1, kind="provisional")
        self.assertEqual(self.run_gate(), 4)
        self.assertEqual(self.merges(), [])

    def test_a_provisional_go_on_a_listed_base_merges(self):
        self.put(1, kind="waived")
        self.assertEqual(self.run_gate(), 0, self.err)
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual((self.last()["kind"], self.last()["round"]), ("waived", 1))

    def test_superseded_go_after_a_force_push_back_never_merges(self):
        self.put(1, kind="provisional")
        self.put(2, kind="provisional", head_sha=OTHER, status="post-failed")
        self.assertEqual(self.run_gate(), 3)
        self.assertEqual(self.last()["reason"], "superseded-go")
        self.put(3, kind="provisional", head_sha=OTHER)
        self.assertEqual(self.run_gate(), 3)

    def test_a_codex_go_on_another_head_supersedes_a_provisional_go_and_no_merge_is_logged(self):
        self.put(1, kind="provisional")
        self.put(2, head_sha=OTHER)
        self.assertEqual(self.run_gate(), 3)
        self.assertEqual(self.last()["reason"], "superseded-go")
        self.assertEqual(self.merges(), [])

    # -------------------------------------------------------------------- identity ----
    def test_a_repo_that_is_not_plain_is_exit_2_and_asks_gh_nothing(self):
        for repo in ("owner", "a/b/c", "a/..", "../b", "./b", "a/.", "own er/repo", "o/r\n", "o/r$", "", "/", "a/",
                     "/b", "o/ré"):
            with self.subTest(repo=repo):
                with self.assertRaises(ValueError):
                    bm.merge(repo, PR)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.assertEqual(self.log(), [])

    def test_main_turns_a_bad_repo_or_pr_into_exit_2(self):
        for argv in (["--repo", "owner", "--pr", "5"], ["--repo", REPO, "--pr", "0"], ["--repo", REPO, "--pr", "x"],
                     ["--repo", REPO, "--pr", "-1"], ["--pr", "5"], ["--repo", REPO], []):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        code = bm.main(argv)
                    except SystemExit as exc:
                        code = exc.code
                self.assertEqual(code, 2)
        self.assertEqual(self.sb.calls_of("gh"), [])

    def test_a_pr_gh_answers_with_another_number_or_url_is_exit_2(self):
        for fields in ({"number": PR + 1}, {"url": "https://github.com/owner/repo/pull/%d" % (PR + 1)},
                       {"url": "https://github.com/other/repo/pull/%d" % PR},
                       {"url": "https://github.com/owner/other/pull/%d" % PR}):
            with self.subTest(fields=fields):
                self.gh.set_pr(**fields)
                self.put(1)
                self.assertEqual(self.run_gate(), 2)
                self.assertEqual(self.last()["reason"], "identity")
                self.gh.set_pr(number=PR, url="https://github.com/%s/pull/%d" % (REPO, PR))
        self.assertEqual(self.merges(), [])

    def test_the_url_may_differ_in_case(self):
        self.gh.set_pr(url="https://github.com/OWNER/Repo/pull/%d" % PR)
        self.put(1)
        self.assertEqual(self.run_gate(), 0, self.err)

    def test_a_pr_that_is_not_open_is_exit_2(self):
        for state in ("CLOSED", "MERGED", "DRAFT", ""):
            with self.subTest(state=state):
                self.gh.set_pr(state=state)
                self.put(1)
                self.assertEqual(self.run_gate(), 2)
                self.assertEqual(self.last()["reason"], "not-open")
        self.assertEqual(self.merges(), [])

    def test_a_gh_read_that_fails_or_gives_nothing_usable_is_exit_7(self):
        for entry in ({"rc": 1, "err": "boom"}, {"raw": ""}, {"raw": "[]"}, {"raw": "null"}, {"raw": "{"},
                      {"raw": json.dumps({"number": PR})}, {"drop": ["state"]},
                      {"patch": {"headRefOid": "nothex"}}, {"patch": {"headRefOid": ""}},
                      {"patch": {"baseRefName": ""}}, {"patch": {"baseRefName": None}},
                      {"patch": {"number": "5"}}, {"patch": {"number": True}}, {"patch": {"url": 5}},
                      {"patch": {"state": None}}):
            with self.subTest(entry=entry):
                self.gh.configure(view=[entry])
                self.gh.set_pr(number=PR, url="https://github.com/%s/pull/%d" % (REPO, PR), headRefOid=HEAD,
                               baseRefName="main", state="OPEN")
                self.put(1)
                self.assertEqual(self.run_gate(), 7, self.err)
                self.assertEqual(self.last()["reason"], "gh-read-failed")
        self.assertEqual(self.merges(), [])

    def test_a_slow_gh_read_is_exit_7_not_a_hang(self):
        self.gh.configure(view=[{"sleep": 3}])
        self.put(1)
        self.assertEqual(self.run_gate(io_timeout=0.4), 7)
        self.assertEqual(self.merges(), [])

    # ------------------------------------------------------------ the merge itself ----
    def test_a_gh_pr_merge_that_fails_is_exit_5_without_an_alert(self):
        # a head that moved after the check is refused by gh through --match-head-commit
        self.gh.configure(merge=[{"rc": 1, "err": "Head branch was modified. Review and try the merge again."}],
                          api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.put(1)
        self.assertEqual(self.run_gate(), 5)
        self.assertEqual((self.last()["decision"], self.last()["reason"]), ("failed", "merge-failed"))
        self.assertIn("Head branch was modified", self.err)
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual(len(self.gh_calls("pr", "view")), 1)       # nothing to verify: it did not merge
        self.assertEqual(self.alerts(), [])

    def test_a_gh_pr_merge_that_runs_past_the_timeout_is_exit_5_and_an_alert(self):
        self.gh.configure(merge=[{"sleep": 3}], api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.put(1)
        self.assertEqual(self.run_gate(io_timeout=0.5), 5)
        self.assertEqual(self.last()["reason"], "merge-timeout")
        (alert,) = self.alerts()
        self.assertEqual(alert.argv[0], "0")

    def test_a_base_retargeted_between_the_check_and_the_merge_is_found_after_and_alerted(self):
        self.gh.configure(view=[{}, {"patch": {"baseRefName": "release"}}], api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.put(1)
        self.assertEqual(self.run_gate(), 5)
        self.assertEqual((self.last()["decision"], self.last()["reason"]), ("failed", "base-changed"))
        (alert,) = self.alerts()
        self.assertEqual(alert.argv[0], "0")
        self.assertIn("base-changed", alert.argv[1])
        self.assertIn("owner/repo#5", alert.argv[1])

    def test_gh_pr_merge_returning_0_with_the_pr_still_open_is_exit_5_not_merged(self):
        for state in ("OPEN", "CLOSED"):
            with self.subTest(state=state):
                self.gh.configure(merge=[{"patch": {"state": state}}], api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
                self.gh.set_pr(state="OPEN")
                self.put(1)
                before = len(self.alerts())
                self.assertEqual(self.run_gate(), 5)
                self.assertEqual(self.last()["reason"], "merge-not-completed")
                self.assertEqual(len(self.alerts()), before + 1)
                self.assertEqual(self.alerts()[-1].argv[0], "0")

    def test_a_pr_that_cannot_be_read_after_the_merge_is_unverified_and_alerted(self):
        for entry in ({"rc": 1, "err": "boom"}, {"raw": "garbage"}, {"raw": json.dumps({"state": "MERGED"})},
                      {"raw": json.dumps({"state": "MERGED", "baseRefName": 5})},
                      {"raw": json.dumps({"state": 1, "baseRefName": "main"})}):
            with self.subTest(entry=entry):
                self.gh.configure(view=[{}, entry], api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
                self.gh.set_pr(state="OPEN")
                self.put(1)
                before = len(self.alerts())
                self.assertEqual(self.run_gate(), 5)
                self.assertEqual(self.last()["reason"], "unverified")
                self.assertEqual(len(self.alerts()), before + 1)

    def test_an_alert_that_fails_is_said_and_the_exit_code_stands(self):
        self.sb.stub("boss-alert", rc=1, err="no slack")
        self.gh.configure(merge=[{"patch": {"state": "OPEN"}}], api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.put(1)
        self.assertEqual(self.run_gate(), 5)
        self.assertIn("boss-alert 0 failed (1)", self.err)
        self.assertEqual(self.last()["reason"], "merge-not-completed")

    def test_an_alert_that_cannot_be_started_is_said_and_the_exit_code_stands(self):
        with mock.patch.dict(os.environ, {"BOSS_ALERT": str(self.sb.root / "nope")}):
            self.gh.configure(merge=[{"patch": {"state": "OPEN"}}], api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
            self.put(1)
            self.assertEqual(self.run_gate(), 5)
        self.assertIn("boss-alert 0 failed", self.err)

    # ----------------------------------------------------------------- merges.jsonl ----
    def test_every_decision_appends_one_line_with_the_fields_of_the_ticket(self):
        self.put(1)
        with mock.patch.object(br, "append_attempts", wraps=br.append_attempts) as append:
            self.run_gate(dry_run=True)
            self.run_gate()
        self.assertEqual([len(c.args[1]) for c in append.call_args_list], [1, 1, 1])      # one write, one line, each
        first, intent, second = self.log()
        self.assertEqual((intent["decision"], intent["exit"], intent["reason"]), ("merging", None, "codex-go"))
        for line in (first, intent, second):
            self.assertEqual(set(line), {"ts", "repo", "pr", "head", "base", "round", "kind", "decision", "exit",
                                         "reason", "config", "dry_run", "base_sha"})
        self.assertEqual((first["repo"], first["pr"], first["head"], first["base"], first["round"], first["kind"],
                          first["decision"], first["exit"], first["reason"], first["config"], first["dry_run"]),
                         (KEY, PR, HEAD, "main", 1, "codex", "allowed", 0, "codex-go", "ok", True))
        self.assertEqual((second["decision"], second["dry_run"]), ("merged", False))
        self.assertEqual(stat.S_IMODE(os.stat(self.reviews / "merges.jsonl").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.reviews).st_mode), 0o700)

    def test_the_intent_line_is_on_disk_before_gh_pr_merge_runs_and_the_pr_lock_is_held_then(self):
        lock = str(self.pr_dir / ".lock")
        self.gh.configure(merge=[{"probe": lock, "log": str(self.reviews / "merges.jsonl")}],
                          api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.put(1)
        self.assertEqual(self.run_gate(), 0, self.err)
        self.assertEqual((self.sb.side / "probe-lock").read_text(), "held")
        (seen,) = [json.loads(x) for x in (self.sb.side / "probe-log").read_text().splitlines()]
        self.assertEqual((seen["decision"], seen["exit"], seen["round"], seen["head"]), ("merging", None, 1, HEAD))
        self.assertEqual([x["decision"] for x in self.log()], ["merging", "merged"])
        fd = br.open_lock(self.reviews, self.pr_dir, 0.5)      # and it is let go again
        os.close(fd)

    def test_no_line_no_merge(self):
        self.put(1)
        with mock.patch.object(br, "append_attempts", side_effect=OSError("disk full")):
            self.assertEqual(self.run_gate(), 5)
        self.assertEqual(self.merges(), [])
        self.assertIn("merges.jsonl was not written: disk full", self.err)
        self.assertIn("log-failed", self.err)

    def test_a_pr_whose_lock_is_held_is_not_checked_and_not_merged(self):
        # a review is claiming a round: whatever it writes, this read must not race it
        self.put(1)
        fd = br.open_lock(self.reviews, self.pr_dir, 0.5)
        try:
            for dry in (True, False):
                self.assertEqual(self.run_gate(dry_run=dry, io_timeout=0.3), 7, self.err)
                self.assertEqual(self.last()["reason"], "lock-failed")
        finally:
            os.close(fd)
        self.assertEqual(self.merges(), [])
        self.assertEqual(self.run_gate(), 0, self.err)

    def test_a_refusal_is_logged_too_and_a_write_that_fails_is_said_and_changes_no_exit(self):
        self.put(1, verdict="NO-GO")
        self.assertEqual(self.run_gate(), 3)
        self.assertEqual(self.last()["decision"], "refused")
        with mock.patch.object(br, "append_attempts", side_effect=OSError("disk full")):
            self.assertEqual(self.run_gate(), 3)
        self.assertIn("merges.jsonl was not written: disk full", self.err)

    def test_the_command_line_runs_and_returns_the_exit_code(self):
        import subprocess
        self.put(1)
        run = subprocess.run([sys.executable, str(HERE / "boss_merge.py"), "--repo", REPO, "--pr", str(PR),
                              "--dry-run"], capture_output=True, text=True, env=dict(os.environ), cwd=str(self.sb.work))
        self.assertEqual((run.returncode, run.stderr), (0, ""), run.stdout)
        self.assertIn("would merge owner/repo#5", run.stdout)
        run = subprocess.run([sys.executable, str(HERE / "boss_merge.py"), "--repo", "owner", "--pr", "5"],
                             capture_output=True, text=True, env=dict(os.environ), cwd=str(self.sb.work))
        self.assertEqual(run.returncode, 2)
        self.assertEqual(self.merges(), [])


# --------------------------------------------------------------- the test-only exception (11b) ----
SINCE = "c" * 40            # the head of the last GO
PRODUCTION = "skills/boss/boss_merge.py"
DEPLOYING = {"version": 1, "non_deploying": ["staging"], "test_paths": ["tests/*"],
             "required_checks": ["ci0"]}      # `main` deploys


def compare_answer(*files, status="ahead", **extra):
    """What `gh api .../compare/<SINCE>...<head>` prints. A file is a name, or a (name, previous name) pair."""
    listed = [{"filename": f[0], "previous_filename": f[1], "status": "renamed"} if isinstance(f, tuple)
              else {"filename": f, "status": "modified"} for f in files]
    return json.dumps(dict({"status": status, "files": listed}, **extra))


class TestOnlySince(Base):
    """`--test-only-since SHA`: the fixes after the last GO that touch only tests need no new review."""

    def setUp(self):
        super().setUp()
        self.deploy = {"raw": deploy_answer(GOOD_DEPLOY)}       # non_deploying main, test_paths tests/*

    def since(self, *compare, deploy=None, sha=SINCE, **kw):
        """The gate with the flag on; `compare` are the entries of the compare calls (the api calls after the first)."""
        self.gh.configure(api=[deploy or self.deploy, *compare])
        return self.run_gate(since=sha, **kw)

    def old_go(self, n=1, **over):
        self.put(n, **dict({"head_sha": SINCE}, **over))

    def compares(self):
        return [c for c in self.gh_calls("api") if "/compare/" in c.argv[1]]

    def refused(self, reason, *compare, code=3, **kw):
        self.assertEqual(self.since(*compare, **kw), code, self.err)
        self.assertEqual(self.merges(), [])
        self.assertEqual((self.last()["decision"], self.last()["exit"], self.last()["reason"]),
                         ("refused", code, reason))
        self.assertEqual(self.last()["since"], kw.get("sha", SINCE))

    # ---------------------------------------------------------------- what it allows ----
    def test_a_codex_go_on_since_and_only_test_files_since_merges_and_the_line_says_so(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py", "tests/b/c.py")}), 0, self.err)
        self.assertEqual([c.argv for c in self.merges()],
                         [["pr", "merge", str(PR), "--repo", REPO, "--merge", "--match-head-commit", HEAD]])
        intent, done = self.log()
        self.assertEqual((done["decision"], done["exit"], done["reason"], done["round"], done["kind"], done["head"]),
                         ("merged", 0, "codex-go-test-only", 1, "codex", HEAD))
        self.assertEqual((intent["decision"], intent["since"], done["since"]), ("merging", SINCE, SINCE))

    def test_the_compare_is_asked_for_since_and_the_live_head_and_nothing_else(self):
        self.old_go()
        self.since({"raw": compare_answer("tests/a.py")})
        self.assertEqual([c.argv for c in self.compares()],
                         [["api", "repos/%s/compare/%s...%s" % (REPO, SINCE, HEAD)]])

    def test_a_line_without_the_flag_has_no_since_key(self):
        self.put(1)
        self.run_gate()
        self.assertNotIn("since", self.last())

    def test_dry_run_decides_and_logs_the_exception_but_never_merges(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")}, dry_run=True), 0, self.err)
        self.assertEqual(self.merges(), [])
        self.assertEqual((self.last()["decision"], self.last()["reason"]), ("allowed", "codex-go-test-only"))

    def test_no_file_changed_since_is_allowed_only_when_identical(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer(status="identical")}), 0, self.err)

    def test_a_rename_inside_the_test_paths_is_allowed(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer(("tests/new.py", "tests/old.py"))}), 0, self.err)

    def test_a_provisional_go_on_a_listed_base_qualifies(self):
        self.old_go(kind="provisional")
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")}), 0, self.err)
        self.assertEqual(self.last()["reason"], "provisional-go-non-deploying-test-only")

    def test_a_codex_go_on_since_qualifies_on_a_deploying_base(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")},
                                    deploy={"raw": deploy_answer(DEPLOYING)}), 0, self.err)

    def test_patterns_are_fnmatchcase_on_the_whole_path(self):
        deploy = {"raw": deploy_answer({"version": 1, "non_deploying": ["main"],
                                        "test_paths": ["skills/*/test_*.py", "fixtures/*"]})}
        self.old_go()
        for names, code in ((("skills/boss/test_x.py", "fixtures/a/b.json"), 0), (("skills/boss/Test_x.py",), 3),
                            (("other/skills/boss/test_x.py",), 3)):
            with self.subTest(names):
                self.assertEqual(self.since({"raw": compare_answer(*names)}, deploy=deploy, dry_run=True), code)

    # ------------------------------------------------------------ what it refuses (3) ----
    def test_any_other_file_refuses(self):
        self.old_go()
        self.refused("not-test-only", {"raw": compare_answer("tests/a.py", PRODUCTION)})
        self.assertIn(PRODUCTION, self.err)

    def test_a_rename_out_of_the_test_paths_refuses_by_either_name(self):
        self.old_go()
        self.refused("not-test-only", {"raw": compare_answer(("src/new.py", "tests/old.py"))})
        self.refused("not-test-only", {"raw": compare_answer(("tests/new.py", "src/old.py"))})

    def test_a_deploy_json_without_test_paths_or_not_valid_refuses_without_a_compare(self):
        self.old_go()
        for answer in (deploy_answer({"version": 1, "non_deploying": ["main"]}), "not json"):
            with self.subTest(answer):
                self.refused("no-test-paths", {"raw": compare_answer("tests/a.py")}, deploy={"raw": answer})
                self.assertEqual(self.compares(), [])

    def test_an_empty_test_paths_refuses_any_file(self):
        self.old_go()
        empty = {"raw": deploy_answer({"version": 1, "non_deploying": ["main"], "test_paths": []})}
        self.refused("not-test-only", {"raw": compare_answer("tests/a.py")}, deploy=empty)

    def test_a_compare_that_fails_or_is_not_a_comparison_refuses_and_is_not_exit_7(self):
        self.old_go()
        answers = [{"rc": 1, "err": "HTTP 404"}, {"raw": "not json"}, {"raw": "[]"},
                   {"raw": json.dumps({"status": "ahead"})},
                   {"raw": json.dumps({"status": "ahead", "files": "tests/a.py"})},
                   {"raw": json.dumps({"status": "ahead", "files": [{"status": "added"}]})},
                   {"raw": json.dumps({"status": "ahead", "files": [{"filename": 5}]})},
                   {"raw": json.dumps({"status": "ahead", "files": [{"filename": "tests/a.py",
                                                                        "previous_filename": 7}]})}]
        for answer in answers:
            with self.subTest(answer):
                self.refused("compare-failed", answer)

    def test_a_slow_compare_refuses_and_does_not_hang(self):
        self.old_go()
        self.refused("compare-failed", {"sleep": 5, "raw": compare_answer("tests/a.py")}, io_timeout=0.5)

    def test_behind_diverged_and_anything_else_refuse(self):
        self.old_go()
        for status in ("behind", "diverged", "ahead ", "AHEAD", None, 3):
            with self.subTest(status):
                self.refused("compare-not-ahead", {"raw": compare_answer("tests/a.py", status=status)})

    def test_identical_is_accepted_as_a_status(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py", status="identical")}), 0, self.err)

    def test_ahead_with_no_file_listed_refuses_whatever_ahead_by_says(self):
        self.old_go()
        for extra in ({}, {"ahead_by": 0}, {"ahead_by": 2}, {"ahead_by": "2"}, {"ahead_by": True}):
            with self.subTest(extra):
                self.refused("compare-no-files", {"raw": compare_answer(**extra)})
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")}, dry_run=True), 0, self.err)

    def test_a_page_of_300_files_is_not_known_to_be_all_of_them(self):
        self.old_go()
        tests = ["tests/f%d.py" % i for i in range(300)]
        self.refused("compare-truncated", {"raw": compare_answer(*tests)})
        self.assertEqual(self.since({"raw": compare_answer(*tests[:299])}), 0, self.err)

    # -------------------------------------------------- what counts as the last GO ----
    def test_a_since_that_is_the_head_of_no_round_refuses_without_a_compare(self):
        self.old_go(head_sha=OTHER)
        self.refused("no-round", {"raw": compare_answer("tests/a.py")})
        self.assertEqual(self.compares(), [])

    def test_a_since_whose_round_is_a_no_go_refuses(self):
        self.old_go(verdict="NO-GO")
        self.refused("no-go", {"raw": compare_answer("tests/a.py")})
        self.old_go(verdict="NO-GO", status="post-failed")
        self.refused("unposted-no-go", {"raw": compare_answer("tests/a.py")})

    def test_a_since_whose_go_never_posted_or_decided_nothing_refuses(self):
        for status, verdict in (("post-failed", "GO"), ("head-moved", None), ("no-verdict", None),
                                ("list-failed", None)):
            with self.subTest(status):
                self.old_go(status=status, verdict=verdict)
                self.refused("no-round", {"raw": compare_answer("tests/a.py")})

    def test_a_no_go_after_since_on_any_head_refuses(self):
        self.old_go()
        for status in ("posted", "post-failed"):
            with self.subTest(status):
                self.put(2, head_sha=OTHER, verdict="NO-GO", status=status)
                self.refused("no-go-after-since", {"raw": compare_answer("tests/a.py")})
                self.assertEqual(self.compares(), [])

    def test_a_no_go_on_the_live_head_stays_a_no_go(self):
        self.old_go()
        self.put(2, verdict="NO-GO")
        self.refused("no-go", {"raw": compare_answer("tests/a.py")})

    def test_a_no_go_below_since_does_not_matter(self):
        self.put(1, head_sha=OTHER, verdict="NO-GO")
        self.old_go(2)
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")}), 0, self.err)

    def test_a_malformed_since_raises_before_gh_is_asked_anything(self):
        self.old_go()
        for sha in ("c" * 39, "c" * 41, "C" * 40, "", "main", "c" * 39 + "g", " " + "c" * 39, "c" * 40 + "\n",
                    "../" + "c" * 37, "c" * 40 + "?x=1", 5):
            with self.subTest(sha):
                with self.assertRaises(ValueError):
                    self.run_gate(since=sha)
        self.assertEqual(self.sb.calls_of("gh"), [])
        self.assertEqual(self.log(), [])

    # ------------------------------------- provisional and waived rounds (04's rules) ----
    def test_a_provisional_or_waived_go_on_a_deploying_base_does_not_qualify(self):
        for kind in ("provisional", "waived"):
            with self.subTest(kind):
                self.old_go(kind=kind)
                self.refused("deploying-base", {"raw": compare_answer("tests/a.py")}, code=4,
                             deploy={"raw": deploy_answer(DEPLOYING)})
                self.assertEqual(self.compares(), [])

    def test_a_later_round_on_the_new_head_supersedes_a_provisional_go_on_since(self):
        self.old_go(kind="provisional")
        self.put(2, status="head-moved", verdict=None)
        self.refused("superseded-go", {"raw": compare_answer("tests/a.py")})
        self.assertEqual(self.compares(), [])

    def test_a_codex_go_on_since_survives_that_later_round(self):
        self.old_go()
        self.put(2, status="head-moved", verdict=None)
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")}), 0, self.err)

    def test_a_codex_go_above_a_provisional_go_on_since_decides_for_the_codex_one(self):
        self.old_go(kind="provisional")
        self.put(2, head_sha=SINCE)
        self.assertEqual(self.since({"raw": compare_answer("tests/a.py")}), 0, self.err)
        self.assertEqual((self.last()["round"], self.last()["kind"]), (2, "codex"))

    # ---------------------------------------------------- the live head decides first ----
    def test_a_live_head_that_is_already_allowed_merges_without_the_exception(self):
        self.put(1)
        self.assertEqual(self.since({"raw": compare_answer(PRODUCTION)}), 0, self.err)
        self.assertEqual(self.compares(), [])
        self.assertEqual(self.last()["reason"], "codex-go")

    def test_a_refusal_on_the_live_head_other_than_no_round_is_not_overridden(self):
        self.old_go(kind="provisional")
        self.put(2, kind="provisional")
        self.put(3, status="head-moved", verdict=None, head_sha=OTHER)
        self.refused("superseded-go", {"raw": compare_answer("tests/a.py")})
        self.assertEqual(self.compares(), [])

    def test_a_bad_record_refuses_before_the_compare(self):
        self.old_go()
        self.raw(2, "not json")
        self.refused("bad-record", {"raw": compare_answer("tests/a.py")})
        self.assertEqual(self.compares(), [])

    # ---------------------------------------------------------------- the command line ----
    def test_the_flag_reaches_the_gate_from_the_command_line_and_a_bad_one_is_exit_2(self):
        self.old_go()
        self.gh.configure(api=[self.deploy, {"raw": compare_answer("tests/a.py")}])
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bm.main(["--repo", REPO, "--pr", str(PR), "--dry-run", "--test-only-since", SINCE]), 0)
            self.assertEqual(bm.main(["--repo", REPO, "--pr", str(PR), "--test-only-since", "main"]), 2)
        self.assertIn("40 lowercase hex", err.getvalue())
        self.assertEqual(len(self.compares()), 1)
        self.assertEqual(self.merges(), [])


# ------------------------------------------------------------- review by risk (ticket 50) ----
def merge_compare(*files, parents=(1, 2), **extra):
    """A compare answer that lists its commits (one entry per parent count) as well as its files."""
    commits = [{"sha": "%040x" % i, "parents": [{}] * n} for i, n in enumerate(parents)]
    return compare_answer(*files, **dict({"commits": commits, "total_commits": len(commits)}, **extra))


def checks_answer(*conclusions, total=None, status="completed"):
    runs = [{"name": "ci%d" % i, "status": status, "conclusion": c} for i, c in enumerate(conclusions)]
    return json.dumps({"total_count": len(runs) if total is None else total, "check_runs": runs})


class DocsAndTests(unittest.TestCase):
    """The pure part of rule 2: which files are docs, and which names are neither docs nor tests."""

    def test_the_narrow_docs_set(self):
        for name in ("README.md", "CHANGELOG.md", "docs/a.md", "docs/deep/b.md"):
            self.assertTrue(bm.is_doc(name), name)

    def test_what_an_agent_acts_on_is_never_docs(self):
        for name in ("skills/boss/SKILL.md", "SKILL.md", "docs/SKILL.md", "docs/skill.md", "AGENTS.md", "CLAUDE.md",
                     "docs/CLAUDE.md", "docs/skills/x.md", "docs/hooks/x.md", "docs/.claude/x.md", "docs/agents/x.md",
                     "docs/commands/x.md", "docs/.github/x.md", "notes.md", "docs/a.txt", "src/README.md",
                     "xdocs/a.md", "README.md.py"):
            self.assertFalse(bm.is_doc(name), name)

    def test_files_problem_is_the_file_condition_of_rule_2_alone(self):
        """Ticket 52: `boss_review.py --opus-direct` asks it too, so the review and the gate share one answer."""
        tests = bm.Deploy("ok", frozenset(), ("tests/*",))
        self.assertIsNone(bm.files_problem(("tests/a.py", "README.md", "docs/x.md"), tests))
        self.assertEqual(bm.files_problem(("tests/a.py", "src/b.py", "SKILL.md"), tests),
                         "not docs or tests: src/b.py, SKILL.md")
        self.assertEqual(bm.files_problem((), tests), "not docs or tests: (no file)")
        self.assertEqual(bm.files_problem(("tests/a.py",), bm.Deploy("ok", frozenset(), None)),
                         "no test_paths in the deploy list")
        self.assertEqual(bm.files_problem(("tests/SKILL.md",), bm.Deploy("ok", frozenset(), ("tests/*",))),
                         "not docs or tests: tests/SKILL.md")

    def test_stray_names_are_those_that_are_neither(self):
        self.assertEqual(bm.not_docs_or_tests(("tests/a.py", "README.md", "docs/x.md"), ("tests/*",)), [])
        self.assertEqual(bm.not_docs_or_tests(("tests/a.py", "src/b.py", "SKILL.md"), ("tests/*",)),
                         ["src/b.py", "SKILL.md"])

    def test_an_instruction_file_is_refused_even_where_test_paths_match_it(self):
        self.assertEqual(bm.not_docs_or_tests(("tests/SKILL.md", "hooks/x.py", "tests/a.py"), ("tests/*", "hooks/*")),
                         ["tests/SKILL.md", "hooks/x.py"])

    def test_no_file_is_not_a_docs_or_tests_pr(self):
        self.assertEqual(bm.not_docs_or_tests((), ("tests/*",)), ["(no file)"])

    def test_the_pr_files_that_differ_since_the_go(self):
        self.assertEqual(bm.touched_by_the_pr(("a", "b"), ("x", "b", "y")), ["b"])
        self.assertEqual(bm.touched_by_the_pr(("a",), ("x", "y")), [])


class DocsTestsOnly(Base):
    """Rule 2: a provisional GO on a deploying base merges when the PR is docs and tests only, with green CI."""

    def setUp(self):
        super().setUp()
        self.deploy = {"raw": deploy_answer(DEPLOYING)}     # `main` deploys

    def go(self, own, checks=None, deploy=None, **over):
        self.put(1, **dict({"kind": "provisional", "reviewer": "opus"}, **over))
        self.gh.configure(api=[deploy or self.deploy, {"raw": compare_answer(*own, status="diverged")},
                               {"raw": checks if checks is not None else checks_answer("success", "skipped")}])
        return self.run_gate()

    def refused(self, own, reason_in_err, code=4, **kw):
        self.assertEqual(self.go(own, **kw), code, self.err)
        self.assertEqual(self.merges(), [])
        self.assertIn(reason_in_err, self.err)
        self.assertEqual(self.last()["decision"], "refused")

    def test_docs_and_tests_with_green_checks_merge_on_a_deploying_base(self):
        self.assertEqual(self.go(["tests/a.py", "docs/x.md", "CHANGELOG.md"]), 0, self.err)
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual((self.last()["reason"], self.last()["kind"], self.last()["round"]),
                         ("provisional-go-docs-tests-only", "provisional", 1))

    def test_the_calls_are_the_files_of_the_pr_against_its_base_and_then_the_checks_of_the_head(self):
        self.go(["tests/a.py"])
        self.assertEqual([c.argv[1] for c in self.gh_calls("api")][1:],
                         ["repos/%s/compare/%s...%s" % (REPO, BASE_SHA, HEAD),
                          "repos/%s/commits/%s/check-runs?per_page=100" % (REPO, HEAD)])

    def test_one_code_file_among_the_tests_keeps_the_refusal(self):
        self.refused(["tests/a.py", PRODUCTION], PRODUCTION)

    def test_skill_md_is_code_and_keeps_the_refusal(self):
        self.refused(["skills/boss/SKILL.md"], "SKILL.md")

    def test_a_rename_out_of_docs_and_tests_refuses_by_either_name(self):
        self.put(1, kind="provisional")
        self.gh.configure(api=[self.deploy, {"raw": compare_answer(("docs/new.md", "src/old.py"), status="ahead")},
                               {"raw": checks_answer("success")}])
        self.assertEqual(self.run_gate(), 4, self.err)

    def test_red_pending_or_no_checks_keep_the_refusal(self):
        for label, answer in (("failure", checks_answer("success", "failure")),
                              ("pending", checks_answer("success", status="in_progress")),
                              ("cancelled", checks_answer("cancelled")), ("none", checks_answer()),
                              ("more than listed", checks_answer("success", total=2)),
                              ("not json", "nope"), ("no list", "{}")):
            with self.subTest(label):
                self.refused(["tests/a.py"], "docs/tests-only rule", checks=answer)

    def test_checks_that_were_all_skipped_or_neutral_are_not_green(self):
        self.refused(["tests/a.py"], "no check run succeeded", checks=checks_answer("skipped", "neutral"))

    def test_the_checks_the_deploy_list_requires_must_all_have_run_and_succeeded(self):
        two = {"raw": deploy_answer(dict(DEPLOYING, required_checks=["ci0", "build"]))}
        self.refused(["tests/a.py"], "required check 'build'", deploy=two, checks=checks_answer("success", "success"))
        named = json.dumps({"total_count": 2, "check_runs": [
            {"name": "ci0", "status": "completed", "conclusion": "success"},
            {"name": "build", "status": "completed", "conclusion": "skipped"}]})
        self.refused(["tests/a.py"], "required check 'build'", deploy=two, checks=named)
        named = named.replace("skipped", "success")
        self.assertEqual(self.go(["tests/a.py"], deploy=two, checks=named), 0, self.err)

    def test_a_deploy_list_with_no_required_checks_keeps_the_refusal_and_reads_no_check_run(self):
        for conf in (dict(DEPLOYING, required_checks=[]), {k: v for k, v in DEPLOYING.items() if k != "required_checks"}):
            with self.subTest(conf=sorted(conf)):
                self.refused(["tests/a.py"], "no required_checks", deploy={"raw": deploy_answer(conf)})
                self.assertEqual([c for c in self.gh_calls("api") if "/check-runs" in c.argv[1]], [])

    def test_a_waived_go_never_qualifies(self):
        self.refused(["tests/a.py"], "deploy list ok", kind="waived")
        self.assertEqual(len(self.gh_calls("api")), 1, "the compare is not even read")

    def test_without_a_go_nothing_merges_whatever_the_files_are(self):
        self.gh.configure(api=[self.deploy, {"raw": compare_answer("tests/a.py")}, {"raw": checks_answer("success")}])
        self.assertEqual(self.run_gate(), 3, self.err)
        self.assertEqual(self.last()["reason"], "no-round")

    def test_a_provisional_go_a_later_round_supersedes_still_refuses(self):
        self.put(1, kind="provisional")
        self.put(2, status="head-moved", verdict=None)
        self.gh.configure(api=[self.deploy, {"raw": compare_answer("tests/a.py")}, {"raw": checks_answer("success")}])
        self.assertEqual(self.run_gate(), 3, self.err)
        self.assertEqual(self.last()["reason"], "superseded-go")

    def test_a_deploy_json_without_test_paths_or_a_failing_compare_keeps_the_refusal(self):
        self.refused(["tests/a.py"], "no test_paths", deploy={"raw": deploy_answer({"version": 1,
                                                                                  "non_deploying": ["staging"]})})
        self.put(1, kind="provisional")
        self.gh.configure(api=[self.deploy, {"rc": 1, "err": "boom"}])
        self.assertEqual(self.run_gate(), 4, self.err)
        self.assertIn("compare-failed", self.err)

    def test_an_empty_or_truncated_pr_does_not_pass(self):
        self.refused([], "compare-no-files")
        self.put(1, kind="provisional")
        many = ["tests/f%d.py" % i for i in range(bm.COMPARE_FILES)]
        self.gh.configure(api=[self.deploy, {"raw": compare_answer(*many)}, {"raw": checks_answer("success")}])
        self.assertEqual(self.run_gate(), 4, self.err)
        self.assertIn("compare-truncated", self.err)

    def test_a_codex_go_does_not_read_the_files_at_all(self):
        self.put(1)
        self.gh.configure(api=[self.deploy])
        self.assertEqual(self.run_gate(), 0, self.err)
        self.assertEqual(len(self.gh_calls("api")), 1)

    def test_a_non_deploying_base_does_not_need_the_rule(self):
        self.put(1, kind="provisional")
        self.gh.configure(api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.assertEqual(self.run_gate(), 0, self.err)
        self.assertEqual(self.last()["reason"], "provisional-go-non-deploying")


class MergedBase(Base):
    """Rule 4: the live head is the GO'd head plus a merge of the base, and the PR's own files are the same."""

    def setUp(self):
        super().setUp()
        self.deploy = {"raw": deploy_answer(DEPLOYING)}     # `main` deploys: only a Codex GO qualifies
        self.put(1, head_sha=SINCE)

    def run_merged(self, changed, own_live, own_since, deploy=None, sha=SINCE, base_side=None, **kw):
        """The entries after the deploy list, in call order: SINCE...head, base...head, base...SINCE, SINCE...base (what
        the base changed since the GO'd head left it; by default, files the PR does not own)."""
        base_side = base_side or compare_answer("src/other.py", status="diverged")
        self.gh.configure(api=[deploy or self.deploy, {"raw": changed}, {"raw": own_live}, {"raw": own_since},
                               {"raw": base_side}])
        return self.run_gate(merged_since=sha, **kw)

    def calls(self):
        return [c.argv[1] for c in self.gh_calls("api") if "/compare/" in c.argv[1]]

    def refused(self, reason, *args, code=3, **kw):
        self.assertEqual(self.run_merged(*args, **kw), code, self.err)
        self.assertEqual(self.merges(), [])
        self.assertEqual((self.last()["decision"], self.last()["exit"], self.last()["reason"]),
                         ("refused", code, reason))

    def test_a_merge_of_main_that_leaves_the_pr_files_alone_merges_and_the_line_says_which_rule(self):
        code = self.run_merged(merge_compare("src/other.py", "docs/b.md"), compare_answer("src/mine.py", status="ahead"),
                               compare_answer("src/mine.py", status="diverged"))
        self.assertEqual(code, 0, self.err)
        self.assertEqual(len(self.merges()), 1)
        intent, done = self.log()
        self.assertEqual((done["reason"], done["since"], done["round"], done["head"]),
                         ("codex-go-merged-base", SINCE, 1, HEAD))
        self.assertEqual(intent["decision"], "merging")

    def test_the_four_compares_are_asked_in_order(self):
        self.run_merged(merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"))
        self.assertEqual(self.calls(), ["repos/%s/compare/%s...%s" % (REPO, SINCE, HEAD),
                                        "repos/%s/compare/%s...%s" % (REPO, BASE_SHA, HEAD),
                                        "repos/%s/compare/%s...%s" % (REPO, BASE_SHA, SINCE),
                                        "repos/%s/compare/%s...%s" % (REPO, SINCE, BASE_SHA)])

    def test_dry_run_decides_but_never_merges(self):
        self.assertEqual(self.run_merged(merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"),
                                         dry_run=True), 0, self.err)
        self.assertEqual((self.merges(), self.last()["decision"]), ([], "allowed"))

    def test_a_pr_file_that_differs_since_the_go_refuses(self):
        self.refused("pr-files-changed", merge_compare("x.py", "src/mine.py"), compare_answer("src/mine.py"),
                     compare_answer("src/mine.py"))
        self.assertIn("src/mine.py", self.err)

    def test_a_file_the_pr_had_at_the_go_and_dropped_since_refuses(self):
        self.refused("pr-files-changed", merge_compare("src/gone.py"), compare_answer("src/mine.py"),
                     compare_answer("src/mine.py", "src/gone.py"))

    def test_a_file_the_pr_added_since_the_go_refuses(self):
        self.refused("pr-files-changed", merge_compare("src/new.py"), compare_answer("src/mine.py", "src/new.py"),
                     compare_answer("src/mine.py"))

    def test_a_merge_that_undoes_a_change_of_main_refuses(self):
        # src/f.py: main changed it, the merge kept the old text. SHA...head does not list it, base...head now does
        self.refused("pr-file-set-changed", merge_compare("x.py"), compare_answer("src/mine.py", "src/f.py"),
                     compare_answer("src/mine.py"))
        self.assertIn("src/f.py", self.err)

    def test_a_file_that_left_the_pr_set_without_a_difference_since_refuses_too(self):
        self.refused("pr-file-set-changed", merge_compare("x.py"), compare_answer("src/mine.py"),
                     compare_answer("src/mine.py", "src/other.py"))

    def test_a_rename_is_matched_by_either_name(self):
        self.refused("pr-files-changed", merge_compare("src/old.py"), compare_answer(("src/new.py", "src/old.py")),
                     compare_answer("src/mine.py"))

    def test_plain_commits_with_no_merge_commit_refuse(self):
        self.refused("no-merge-commit", merge_compare("x.py", parents=(1, 1)), compare_answer("m.py"),
                     compare_answer("m.py"))

    def test_commits_that_are_not_all_listed_or_not_listed_at_all_refuse(self):
        self.refused("compare-commits", compare_answer("x.py"), compare_answer("m.py"), compare_answer("m.py"))
        self.refused("compare-commits", merge_compare("x.py", total_commits=300), compare_answer("m.py"),
                     compare_answer("m.py"))

    def test_a_compare_since_that_is_not_ahead_refuses(self):
        self.refused("compare-not-ahead", merge_compare("x.py", status="diverged"), compare_answer("m.py"),
                     compare_answer("m.py"))

    def test_a_failed_or_truncated_own_compare_refuses(self):
        self.refused("compare-failed", merge_compare("x.py"), "nope", compare_answer("m.py"))
        self.refused("compare-truncated", merge_compare("x.py"),
                     compare_answer(*["f%d.py" % i for i in range(bm.COMPARE_FILES)]), compare_answer("m.py"))
        self.refused("compare-not-ahead", merge_compare("x.py"), compare_answer("m.py", status="behind"),
                     compare_answer("m.py"))

    def test_a_pr_that_owns_no_file_at_either_head_refuses_whatever_the_status(self):
        for status in ("ahead", "diverged", "identical"):
            for live, since in (([], ["m.py"]), (["m.py"], []), ([], [])):
                with self.subTest(status=status, live=live, since=since):
                    self.run_merged(merge_compare("x.py"), compare_answer(*live, status=status),
                                    compare_answer(*since, status=status))
                    self.assertEqual(self.merges(), [])
                    self.assertEqual(self.last()["decision"], "refused")
                    self.assertIn(self.last()["reason"], ("compare-no-files", "pr-owns-nothing"))

    def test_a_base_with_a_slash_goes_into_the_compare_path_percent_encoded(self):
        self.gh.set_pr(baseRefName="release/1.0")
        self.put(1, head_sha=SINCE, base="release/1.0")
        self.assertEqual(self.run_merged(merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py")), 0,
                         self.err)
        self.assertEqual(self.calls(), ["repos/%s/compare/%s...%s" % (REPO, SINCE, HEAD),
                                        "repos/%s/compare/%s...%s" % (REPO, BASE_SHA, HEAD),
                                        "repos/%s/compare/%s...%s" % (REPO, BASE_SHA, SINCE),
                                        "repos/%s/compare/%s...%s" % (REPO, SINCE, BASE_SHA)])

    # ticket 54: a conflict resolved by keeping the reviewed version hides the base's change from SHA...head
    def test_a_pr_file_that_the_base_changed_since_the_go_refuses_even_when_the_merge_kept_the_reviewed_text(self):
        # SHA...head lists nothing of src/mine.py (the merge kept SHA's text), base...head and base...SHA both list it
        for base_side in (compare_answer("src/mine.py", "src/other.py", status="diverged"),
                          compare_answer("src/mine.py", status="ahead")):
            with self.subTest(base_side):
                self.refused("pr-file-changed-on-base", merge_compare("x.py"), compare_answer("src/mine.py"),
                             compare_answer("src/mine.py"), base_side=base_side)
                self.assertIn("src/mine.py", self.err)

    def test_a_pr_file_the_base_renamed_refuses_by_either_name(self):
        self.refused("pr-file-changed-on-base", merge_compare("x.py"), compare_answer("src/mine.py"),
                     compare_answer("src/mine.py"), base_side=compare_answer(("src/new.py", "src/mine.py"),
                                                                              status="diverged"))

    def test_a_base_that_has_not_moved_since_the_go_merges(self):
        for status in ("behind", "identical"):
            with self.subTest(status):
                self.assertEqual(self.run_merged(merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"),
                                                 base_side=compare_answer(status=status), dry_run=True), 0, self.err)

    def test_a_base_compare_that_cannot_be_trusted_refuses(self):
        for label, base_side, reason in (
                ("failed", "nope", "compare-failed"),
                ("truncated", compare_answer(*["f%d.py" % i for i in range(bm.COMPARE_FILES)], status="diverged"),
                 "compare-truncated"),
                ("no files listed", compare_answer(status="diverged"), "compare-no-files"),
                ("an unexpected status", compare_answer("src/other.py", status="surprise"), "compare-not-ahead")):
            with self.subTest(label):
                self.refused(reason, merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"),
                             base_side=base_side)

    def test_the_combination_refuses_a_pr_file_the_base_changed_before_it_reads_the_checks(self):
        both = compare_answer("tests/a.py", status="diverged")
        self.put(1, head_sha=SINCE, kind="provisional")
        self.gh.configure(api=[self.deploy, {"raw": merge_compare("x.py")}, {"raw": both}, {"raw": both},
                               {"raw": compare_answer("tests/a.py", status="diverged")},
                               {"raw": checks_answer("success")}])
        self.assertEqual(self.run_gate(merged_since=SINCE), 3, self.err)
        self.assertEqual(self.last()["reason"], "pr-file-changed-on-base")
        self.assertNotIn("check-runs", " ".join(c.argv[1] for c in self.gh_calls("api")))

    # rule 2 and rule 4 together: a provisional GO the PR earned as docs/tests-only, then main merged into it
    def combined(self, own_live, own_since, checks=None, deploy=None, **over):
        self.put(1, **dict({"head_sha": SINCE, "kind": "provisional"}, **over))
        self.gh.configure(api=[deploy or self.deploy, {"raw": merge_compare("x.py")}, {"raw": own_live},
                               {"raw": own_since}, {"raw": compare_answer("src/other.py", status="diverged")},
                               {"raw": checks if checks is not None else checks_answer("success", "skipped")}])
        return self.run_gate(merged_since=SINCE)

    def test_a_docs_tests_only_pr_with_a_provisional_go_that_merged_main_merges_on_a_deploying_base(self):
        both = compare_answer("tests/a.py", "docs/x.md", status="diverged")
        self.assertEqual(self.combined(both, both), 0, self.err)
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual(self.last()["reason"], "provisional-go-docs-tests-only-merged-base")
        self.assertEqual([c.argv[1] for c in self.gh_calls("api")][-1],
                         "repos/%s/commits/%s/check-runs?per_page=100" % (REPO, HEAD))

    def test_the_combination_keeps_every_condition_of_both_rules(self):
        both = compare_answer("tests/a.py", status="diverged")
        code_pr = compare_answer("tests/a.py", PRODUCTION, status="diverged")
        for label, args, code, why in (
                ("a code file", (code_pr, code_pr), 4, PRODUCTION),
                ("red checks", (both, both, checks_answer("failure")), 4, "check "),
                ("no required check", (both, both, checks_answer("success"), {"raw": deploy_answer(
                    dict(DEPLOYING, required_checks=["build"]))}), 4, "required check 'build'"),
                ("a pr file touched since", (compare_answer("tests/a.py", "x.py", status="diverged"),) * 2, 3,
                 "x.py")):
            with self.subTest(label):
                before = len(self.merges())
                self.assertEqual(self.combined(*args), code, self.err)
                self.assertEqual(len(self.merges()), before)
                self.assertIn(why, self.err)

    def test_a_waived_go_does_not_combine(self):
        both = compare_answer("tests/a.py", status="diverged")
        self.assertEqual(self.combined(both, both, kind="waived"), 4, self.err)
        self.assertEqual(self.calls(), [])

    def test_the_go_must_be_one_decide_allows(self):
        self.put(1, head_sha=SINCE, kind="waived")           # a waived GO on a deploying base
        self.refused("deploying-base", merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"), code=4)
        self.assertEqual(self.calls(), [])

    def test_a_no_go_above_the_go_refuses(self):
        self.put(2, head_sha=OTHER, verdict="NO-GO")
        self.refused("no-go-after-since", merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"))
        self.assertEqual(self.calls(), [])

    def test_a_sha_that_is_no_go_round_refuses(self):
        self.refused("no-round", merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"), sha=OTHER)

    def test_a_deciding_round_on_the_live_head_stands(self):
        self.put(2, verdict="NO-GO")
        self.refused("no-go", merge_compare("x.py"), compare_answer("m.py"), compare_answer("m.py"))
        self.assertEqual(self.calls(), [])

    def test_the_two_flags_together_and_a_bad_sha_are_usage_errors(self):
        for kw in ({"since": SINCE, "merged_since": SINCE}, {"merged_since": "main"}):
            with self.subTest(kw), self.assertRaises(ValueError):
                self.run_gate(**kw)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(bm.main(["--repo", REPO, "--pr", str(PR), "--merged-base-since", "main"]), 2)
        self.assertEqual(self.merges(), [])


class BaseTip(Base):
    """Ticket 54, the base moving under the gate: the compares are made on one tip, the merge is checked against it."""

    def go(self, **cfg):
        self.put(1)
        self.gh.configure(**dict({"api": [{"raw": deploy_answer(GOOD_DEPLOY)}]}, **cfg))
        return self.run_gate()

    def test_the_compares_use_the_tip_read_at_the_start_not_the_branch_name(self):
        self.put(1, kind="provisional")
        self.gh.configure(api=[{"raw": deploy_answer(DEPLOYING)}, {"raw": compare_answer("tests/a.py")},
                               {"raw": checks_answer("success")}], ref=[{"patch": {"baseSha": OTHER}}])
        self.run_gate()
        self.assertIn("repos/%s/compare/%s...%s" % (REPO, OTHER, HEAD), [c.argv[1] for c in self.gh_calls("api")])
        self.assertEqual(self.last()["base_sha"], OTHER)

    def test_a_base_that_moved_before_the_merge_refuses_as_base_moved_and_merges_nothing(self):
        self.assertEqual(self.go(ref=[{}, {"patch": {"baseSha": MOVED_SHA}}]), 3, self.err)
        self.assertEqual(self.merges(), [])
        self.assertEqual((self.last()["decision"], self.last()["reason"]), ("refused", "base-moved"))
        self.assertIn(BASE_SHA[:12], self.err)
        self.assertIn(MOVED_SHA[:12], self.err)
        self.assertEqual([m["decision"] for m in self.log()], ["refused"], "no intent line for a merge not made")

    def test_the_tip_is_read_again_right_before_the_merge(self):
        self.assertEqual(self.go(), 0, self.err)
        argv = [c.argv[:2] for c in self.sb.calls_of("gh")]
        ref = ["api", "repos/%s/git/ref/heads/main" % REPO]
        self.assertEqual(argv[argv.index(["pr", "merge"]) - 1], ref)
        self.assertEqual(argv.count(ref), 2)

    def test_a_dry_run_reads_the_tip_once_only(self):
        self.put(1)
        self.assertEqual(self.run_gate(dry_run=True), 0, self.err)
        self.assertEqual(len([c for c in self.base_calls() if "/git/ref/" in c]), 1)

    def test_a_tip_that_cannot_be_read_refuses_at_both_reads(self):
        for label, ref in (("first", [{"rc": 1, "err": "boom"}]), ("second", [{}, {"rc": 1, "err": "boom"}]),
                           ("no commit", [{"raw": json.dumps({"object": {}})}]), ("not json", [{"raw": "no"}])):
            with self.subTest(label):
                self.gh.set_pr(state="OPEN")
                self.assertEqual(self.go(ref=ref), bm.EXIT_GH_READ, self.err)
                self.assertEqual(self.merges(), [])
                self.assertEqual(self.last()["reason"], "gh-read-failed")

    def test_a_merge_made_on_the_recorded_tip_is_quiet(self):
        self.assertEqual(self.go(), 0, self.err)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(self.base_calls()[-1], "repos/%s/commits/%s" % (REPO, MERGE_SHA))

    def test_a_merge_whose_first_parent_is_not_the_recorded_tip_is_alerted_loudly(self):
        self.gh.set_pr(mergeParent=MOVED_SHA)
        self.assertEqual(self.go(), 5, self.err)
        self.assertEqual((self.last()["decision"], self.last()["reason"]), ("failed", "base-moved-during-merge"))
        (alert,) = self.alerts()
        self.assertEqual(alert.argv[0], "0")
        for text in ("owner/repo#5", BASE_SHA, MOVED_SHA, HEAD, "by hand"):
            self.assertIn(text, alert.argv[1])

    def test_a_merge_commit_that_cannot_be_read_is_alerted_as_unverified(self):
        for label, cfg, pr in (("no oid", {}, {"mergeCommit": None}),
                               ("commit read fails", {"commit": [{"rc": 1, "err": "boom"}]}, {}),
                               ("no parents", {"commit": [{"raw": json.dumps({"parents": []})}]}, {})):
            with self.subTest(label):
                self.gh.set_pr(**dict({"state": "OPEN", "mergeParent": BASE_SHA, "mergeCommit": {"oid": MERGE_SHA}}, **pr))
                before = len(self.alerts())
                self.assertEqual(self.go(**cfg), 5, self.err)
                self.assertEqual(self.last()["reason"], "unverified")
                self.assertEqual(len(self.alerts()), before + 1)
                self.assertIn("by hand", self.alerts()[-1].argv[1])


class MergeQueue(Base):
    """Ticket 54: a base with a merge queue, or a PR already queued or on auto-merge, is refused before `gh pr merge`;
    the gate never passes `--auto`, so a merge that was made is a merge that completed, or it failed."""

    def go(self, dry_run=False, **cfg):
        self.gh.configure(**dict({"api": [{"raw": deploy_answer(GOOD_DEPLOY)}]}, **cfg))
        self.put(1)
        return self.run_gate(dry_run=dry_run)

    @staticmethod
    def graphql(queue=None, auto=None, in_queue=False):
        return {"raw": json.dumps({"data": {"repository": {"mergeQueue": queue, "pullRequest": {
            "autoMergeRequest": auto, "isInMergeQueue": in_queue}}}})}

    def refused(self, code, reason, **cfg):
        self.assertEqual(self.go(**cfg), code, self.err)
        self.assertEqual(self.merges(), [], "gh pr merge was called")
        self.assertEqual((self.last()["decision"], self.last()["reason"]), ("refused", reason))
        self.assertEqual(self.alerts(), [])

    def test_a_ruleset_of_type_merge_queue_refuses(self):
        self.refused(3, "merge-queue-unsupported", rules=[{"raw": json.dumps([{"type": "deletion"}, {"type": "merge_queue"}])}])
        self.assertIn("merge-queue rule", self.err)

    def test_a_merge_queue_that_github_reports_for_the_branch_refuses(self):
        self.refused(3, "merge-queue-unsupported", graphql=[self.graphql(queue={"id": "MQ_1"})])

    def test_a_pr_with_auto_merge_on_or_already_in_the_queue_refuses(self):
        self.refused(3, "merge-queue-unsupported", graphql=[self.graphql(auto={"enabledAt": "t"})])
        self.gh.set_pr(state="OPEN")
        self.refused(3, "merge-queue-unsupported", graphql=[self.graphql(in_queue=True)])

    def test_whatever_cannot_be_read_refuses_closed(self):
        bad = (("rules fail", {"rules": [{"rc": 1, "err": "boom"}]}),
               ("rules not json", {"rules": [{"raw": "no"}]}),
               ("rules not a list", {"rules": [{"raw": "{}"}]}),
               ("rule without a type", {"rules": [{"raw": "[{}]"}]}),
               ("graphql fails", {"graphql": [{"rc": 1, "err": "boom"}]}),
               ("graphql not json", {"graphql": [{"raw": "no"}]}),
               ("no repository", {"graphql": [{"raw": json.dumps({"data": {"repository": None}})}]}),
               ("no mergeQueue field", {"graphql": [{"raw": json.dumps({"data": {"repository": {"pullRequest": {
                   "autoMergeRequest": None, "isInMergeQueue": False}}}})}]}),
               ("queue flag not a bool", {"graphql": [self.graphql(in_queue="no")]}))
        for label, cfg in bad:
            with self.subTest(label):
                self.gh.set_pr(state="OPEN")
                self.refused(bm.EXIT_GH_READ, "gh-read-failed", **cfg)

    def test_a_refusal_writes_no_merging_line_and_a_dry_run_asks_the_same(self):
        self.assertEqual(self.go(dry_run=True, graphql=[self.graphql(queue={"id": "MQ_1"})]), 3, self.err)
        self.assertEqual([m["decision"] for m in self.log()], ["refused"])

    def test_the_rules_url_carries_a_slash_named_base_as_one_path_segment(self):
        self.gh.set_pr(baseRefName="release/1.0")
        self.put(1, base="release/1.0")
        self.gh.configure(api=[{"raw": deploy_answer(GOOD_DEPLOY)}])
        self.assertEqual(self.run_gate(), 0, self.err)
        rules = [c.argv[1] for c in self.sb.calls_of("gh") if c.argv[0] == "api" and "/rules/branches/" in c.argv[1]]
        self.assertEqual(rules, ["repos/%s/rules/branches/release%%2F1.0" % REPO])

    def test_a_base_without_a_queue_merges_and_the_reads_come_before_the_merge(self):
        self.assertEqual(self.go(), 0, self.err)
        argv = [c.argv[:2] for c in self.sb.calls_of("gh")]
        self.assertLess(argv.index(["api", "graphql"]), argv.index(["pr", "merge"]))
        self.assertEqual(self.alerts(), [])

    def test_the_gate_never_passes_auto_or_tries_to_undo(self):
        for cfg in ({}, {"merge": [{"patch": {"state": "OPEN"}}]}, {"merge": [{"rc": 1, "err": "no"}]}):
            self.gh.set_pr(state="OPEN")
            self.go(**cfg)
        merges = [c.argv for c in self.sb.calls_of("gh") if c.argv[:2] == ["pr", "merge"]]
        self.assertEqual(len(merges), 3)
        for argv in merges:
            self.assertEqual(argv, ["pr", "merge", str(PR), "--repo", REPO, "--merge", "--match-head-commit", HEAD])
        source = Path(bm.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"--auto"', source, "the gate must not pass --auto")
        self.assertNotIn("--disable-auto", source.replace("`--disable-auto`", ""))

    def test_a_merge_that_leaves_the_pr_unmerged_is_refused_and_alerted_with_no_undo(self):
        self.assertEqual(self.go(merge=[{"patch": {"state": "OPEN"}}]), 5, self.err)
        self.assertEqual(self.last()["reason"], "merge-not-completed")
        (alert,) = self.alerts()
        self.assertIn("by hand", alert.argv[1])
        self.assertEqual(len(self.merges()), 1)


# ----------------------------------------------------- end to end, from the real writers ----
class FromTheWriters:
    """Records made by 08's and 09c's own code, then the gate on them. The `gh` stub is the merge gate's."""

    def use_merge_gh(self):
        self.gh = MergeGh(self.sb, self.head)
        self.setup_gate()
        patcher = mock.patch.dict(os.environ, {"BOSS_ALERT": str(self.sb.stubs / "boss-alert")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def gate(self, non_deploying, dry_run=True):
        self.gh.configure(api=[{"raw": deploy_answer({"version": 1, "non_deploying": non_deploying})}])
        before = len(self.merges())
        code = self.run_gate(dry_run=dry_run)
        return code, len(self.merges()) - before

    def assertGateOn(self, kind):
        # a deploying base: exit 4 and no gh pr merge call; a listed base: exit 0
        self.assertEqual(self.gate(["staging"]), (4, 0), self.err)
        self.assertEqual((self.last()["kind"], self.last()["reason"]), (kind, "deploying-base"))
        self.assertEqual(self.gate(["main"]), (0, 0), self.err)
        self.assertEqual((self.last()["kind"], self.last()["decision"]), (kind, "allowed"))
        self.assertEqual(self.gate(["main"], dry_run=False), (0, 1), self.err)
        self.assertEqual(self.last()["decision"], "merged")


class ProvisionalGoFromReview(FromTheWriters, Gate, ProvBase):
    def setUp(self):
        super().setUp()
        self.use_merge_gh()

    def tearDown(self):
        super().tearDown()
        self.gate_teardown()

    def test_a_provisional_go_written_by_the_fallback_review(self):
        self.claude("FINDING: none\nVERDICT: GO\nREASON: fine\n")
        result = self.review(allow_fallback=True, track="t")      # no codex stub: the fallback answers
        self.assertEqual((result.round, result.status, result.kind), (1, "posted", "provisional"))
        self.assertEqual(self.sb.calls_of("codex"), [])
        self.assertGateOn("provisional")

    def test_the_entry_is_superseded_by_a_later_round_the_writer_makes(self):
        self.claude("FINDING: none\nVERDICT: GO\nREASON: fine\n")
        self.review(allow_fallback=True, track="t")
        (self.pr_dir / "round02.json").write_text(
            json.dumps(self.make_record(2, head_sha=OTHER, status="head-moved")), encoding="utf-8")
        self.assertEqual(self.gate(["main"]), (3, 0))
        self.assertEqual(self.last()["reason"], "superseded-go")


class WaivedRoundFromWaive(FromTheWriters, Gate, test_waiver.Base):
    def setUp(self):
        super().setUp()
        self.use_merge_gh()
        self.gh.set_pr(state="OPEN")

    def tearDown(self):
        super().tearDown()
        self.gate_teardown()

    def test_a_waived_round_written_by_waive(self):
        self.gh.set_pr(headRefOid=self.head)
        self.waive()
        (path,) = sorted(self.pr_dir.glob("round*.json"))
        self.assertEqual(json.loads(path.read_text())["kind"], "waived")
        self.assertGateOn("waived")


if __name__ == "__main__":
    unittest.main()
