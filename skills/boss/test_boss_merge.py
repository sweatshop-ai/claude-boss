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
        self.assertEqual([len(c.args[1]) for c in append.call_args_list], [1, 1, 1])      # one write, one line, each
        first, intent, second = self.log()
        self.assertEqual((intent["decision"], intent["exit"], intent["reason"]), ("merging", None, "codex-go"))
        for line in (first, intent, second):
            self.assertEqual(set(line), {"ts", "repo", "pr", "head", "base", "round", "kind", "decision", "exit",
                                         "reason", "config", "dry_run"})
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
DEPLOYING = {"version": 1, "non_deploying": ["staging"], "test_paths": ["tests/*"]}      # `main` deploys


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

    def test_no_file_changed_since_is_allowed(self):
        self.old_go()
        self.assertEqual(self.since({"raw": compare_answer()}), 0, self.err)

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
