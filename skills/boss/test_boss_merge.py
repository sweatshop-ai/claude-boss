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


class MergeGh:
    """The `gh` stub and the PR it serves."""

    def __init__(self, sb, head):
        self.side = sb.side
        (self.side / "gh_handler.py").write_text(GH_HANDLER, encoding="utf-8")
        self.set_pr(number=PR, url="https://github.com/%s/pull/%d" % (REPO, PR), headRefOid=head,
                    baseRefName="main", state="OPEN", title=TITLE, body=BODY, diff=DIFF)
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

    def gh_calls(self, *prefix):
        return [c for c in self.sb.calls_of("gh") if c.argv[:len(prefix)] == list(prefix)]

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

    def test_a_good_file_lists_main(self):
        got = bm.parse_deploy(deploy_answer(GOOD_DEPLOY).encode())
        self.assertEqual((got.state, got.non_deploying, got.test_paths), ("ok", frozenset({"main"}), ("tests/*",)))
        got = bm.parse_deploy(deploy_answer({"version": 1, "non_deploying": []}).encode())
        self.assertEqual((got.state, got.non_deploying, got.test_paths), ("ok", frozenset(), None))

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
                         [["pr", "view"], ["api", self.gh_calls("api")[0].argv[1]], ["pr", "merge"], ["pr", "view"]])

    def test_the_gh_pr_view_reads_the_five_fields_once_and_the_two_after_the_merge(self):
        self.put(1)
        self.run_gate()
        first, second = self.gh_calls("pr", "view")
        self.assertEqual(first.argv[first.argv.index("--json") + 1], "number,url,headRefOid,baseRefName,state")
        self.assertEqual(second.argv[second.argv.index("--json") + 1], "baseRefName,state")

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
                self.assertEqual(self.last()["reason"], "not-merged")
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
        self.assertEqual(self.last()["reason"], "not-merged")

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
        self.assertEqual([len(c.args[1]) for c in append.call_args_list], [1, 1])      # one write, one line, each
        first, second = self.log()
        for line in (first, second):
            self.assertEqual(set(line), {"ts", "repo", "pr", "head", "base", "round", "kind", "decision", "exit",
                                         "reason", "config", "dry_run"})
        self.assertEqual((first["repo"], first["pr"], first["head"], first["base"], first["round"], first["kind"],
                          first["decision"], first["exit"], first["reason"], first["config"], first["dry_run"]),
                         (KEY, PR, HEAD, "main", 1, "codex", "allowed", 0, "codex-go", "ok", True))
        self.assertEqual((second["decision"], second["dry_run"]), ("merged", False))
        self.assertEqual(stat.S_IMODE(os.stat(self.reviews / "merges.jsonl").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.reviews).st_mode), 0o700)

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
