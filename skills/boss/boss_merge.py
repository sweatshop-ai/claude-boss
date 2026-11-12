#!/usr/bin/env python3
"""The merge gate (ticket 04): check the review record of one PR and merge it only if the record allows it.

    boss_merge.py --repo OWNER/REPO --pr N [--dry-run]       the command
    merge(repo, pr, dry_run=False) -> int                    the same, returning the exit code
    decide(rounds, head, base, non_deploying, owner) -> Decision      the rule, pure
    read_rounds(pr_dir) -> list[Round]            the PR's round<NN>.json files, as 02 wrote them
    read_deploy(repo, base) -> Deploy             the repo's own list of branches that do not deploy

Exit codes:

    0 merged (under --dry-run: would be allowed)
    2 usage, the PR is not the one asked for, or it is not open
    3 refused: no usable GO on the live head (none, a NO-GO, a record that cannot be read, or a provisional
      or waived GO that a later round supersedes)
    4 refused: a provisional or waived GO on a branch not listed as non-deploying
    5 `gh pr merge` failed, or the check after it did (not merged, base changed, unverified), or the line that
      announces the merge could not be written (nothing merged then)
    7 a `gh` read failed, or the PR's lock could not be taken

The rounds are the files `boss_review.py` keeps under $CLAUDE_CONFIG_DIR/pm/reviews/<owner>/<repo>/pr<N>/. They
are walked from the highest number down and the first one that decides, decides: anything the walk meets and cannot
read refuses (it is never skipped), so a crash leftover is replaced by the next round and not before. The list of
branches that do not deploy is `.boss/deploy.json` as committed on the PR's base branch, read through `gh api`, never
from the PR's head; a file that is missing or invalid means every branch deploys. Every decision appends one line to
pm/reviews/merges.jsonl, and a merge writes a `merging` line before it runs `gh pr merge`. The PR's lock (the one a
review takes to claim a round) is held from the read of the rounds to the return of `gh pr merge`. Standard library only (and boss_review, which owns the record).
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import os
import re
import stat
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import NamedTuple

import boss_review
import codex_blocker
import policy

EXIT_MERGED, EXIT_USAGE, EXIT_REFUSED, EXIT_DEPLOYING, EXIT_MERGE_FAILED, EXIT_GH_READ = 0, 2, 3, 4, 5, 7

ALERT_TIMEOUT = 20      # seconds, as codex_blocker's

FIELDS = ("repo", "pr", "round", "head_sha", "base", "kind", "verdict", "status")     # what the walk reads
KINDS = ("codex", "provisional", "waived")
VERDICTS = ("GO", "NO-GO", None)
STATUSES = ("posted", "head-moved", "no-verdict", "post-failed", "list-failed")
NOT_A_REVIEW = ("head-moved", "no-verdict", "list-failed")      # rounds that decide nothing

_ROUND_FILE = re.compile(r"round([0-9]+)\.json")


def _say(message: str) -> None:
    print("boss_merge: " + message, file=sys.stderr)


# ------------------------------------------------------------------------- the rounds ----
class Round(NamedTuple):
    number: int | None      # None: a file name whose number cannot be read
    record: object          # the parsed JSON, or None when the file could not be read as JSON


def file_round(name: str) -> tuple[bool, int | None]:
    """(is it a round file, its number). A name that matches and whose digits `int()` refuses (more than 4300 of
    them) is a round file with no number: a bad record, not an absent one."""
    m = _ROUND_FILE.fullmatch(name)
    if m is None:
        return False, None
    try:
        return True, int(m.group(1))
    except ValueError:
        return True, None


def _load(path: Path) -> object:
    """The parsed JSON of one round file, or None for anything that is not a regular file holding JSON."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):      # a RecursionError: JSON nested too deep for the parser
        return None


def read_rounds(pr_dir: Path) -> list[Round]:
    """Every `round<NN>.json` of the PR. A directory that cannot be listed is one unreadable round, so the gate
    refuses; one that is absent holds none."""
    try:
        names = os.listdir(pr_dir)
    except FileNotFoundError:
        return []
    except OSError:
        return [Round(None, None)]
    rounds = []
    for name in names:
        is_round, number = file_round(name)
        if is_round:
            rounds.append(Round(number, _load(pr_dir / name) if number is not None else None))
    taken = [r.number for r in rounds]
    # two files for one number (round1.json and round01.json) cannot both be that round: neither is read
    return [r if r.number is None or taken.count(r.number) == 1 else Round(r.number, None) for r in rounds]


def _valid(r: Round, owner: tuple[str, int]) -> dict | None:
    """The record when it is one of this PR's, whole and of known values, else None."""
    rec = r.record
    if r.number is None or not isinstance(rec, dict) or any(f not in rec for f in FIELDS):
        return None
    if type(rec["round"]) is not int or type(rec["pr"]) is not int:     # a string, a float or a bool is not one
        return None
    if rec["round"] != r.number or (rec["repo"], rec["pr"]) != owner:
        return None
    if not isinstance(rec["head_sha"], str) or not isinstance(rec["base"], str):
        return None
    if rec["kind"] not in KINDS or rec["verdict"] not in VERDICTS or rec["status"] not in STATUSES:
        return None
    if rec["verdict"] is None and rec["status"] in ("posted", "post-failed"):     # a verdict was posted, or tried
        return None
    return rec


class Decision(NamedTuple):
    exit: int
    reason: str
    round: int | None = None      # the round that decided, when one did
    kind: str | None = None


def decide(rounds: list[Round], head: str, base: str, non_deploying, owner: tuple[str, int]) -> Decision:
    """May the PR merge with this head and this base? `owner` is the (repo key, PR number) the records must name.

    Walk from the highest round down. A record that cannot be trusted refuses (3, `bad-record`). A valid one for
    another head or base, or a round that decided nothing (`head-moved`, `no-verdict`, `list-failed`, a
    `post-failed` GO), is passed over, and a later round that was passed over means a provisional or waived GO below
    it is `superseded-go`: that GO was not the PR's last word. The first valid posted round on the live head decides.
    A Codex GO decides on any base; a provisional or waived GO only on a branch in `non_deploying`. A `post-failed`
    NO-GO on the live head still refuses: the verdict is known, only the comment is missing."""
    later = 0           # valid rounds above the one being looked at, passed over
    for r in sorted(rounds, key=lambda r: math.inf if r.number is None else r.number, reverse=True):
        rec = _valid(r, owner)
        if rec is None:
            return Decision(EXIT_REFUSED, "bad-record", r.number)
        status, verdict, kind = rec["status"], rec["verdict"], rec["kind"]
        if rec["head_sha"] != head or rec["base"] != base or status in NOT_A_REVIEW \
                or (status == "post-failed" and verdict == "GO"):
            later += 1
            continue
        if verdict == "NO-GO":
            return Decision(EXIT_REFUSED, "no-go" if status == "posted" else "unposted-no-go", r.number, kind)
        if kind == "codex":
            return Decision(EXIT_MERGED, "codex-go", r.number, kind)
        if later:
            return Decision(EXIT_REFUSED, "superseded-go", r.number, kind)
        if base in non_deploying:
            return Decision(EXIT_MERGED, "%s-go-non-deploying" % kind, r.number, kind)
        return Decision(EXIT_DEPLOYING, "deploying-base", r.number, kind)
    return Decision(EXIT_REFUSED, "no-round")


# ------------------------------------------------------------------- the deploy list ----
class Deploy(NamedTuple):
    state: str                       # "ok", or why the file counts as invalid
    non_deploying: frozenset
    test_paths: tuple | None         # for ticket 11


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def parse_deploy(answer: bytes) -> Deploy:
    """What `gh api .../contents/.boss/deploy.json` answered, as a Deploy; invalid is every branch deploying."""
    def invalid(state: str) -> Deploy:
        return Deploy(state, frozenset(), None)

    try:
        data = json.loads(answer.decode("utf-8"))
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, str):            # absent, or a directory listing
            return invalid("bad-content")
        # GitHub breaks the encoding into lines; any other character that is not base64 is not a file we wrote
        text = base64.b64decode(content.replace("\n", ""), validate=True).decode("utf-8")
    except (ValueError, RecursionError, binascii.Error):
        return invalid("bad-content")
    try:
        conf = json.loads(text)
    except (ValueError, RecursionError):
        return invalid("not-json")
    if not isinstance(conf, dict) or type(conf.get("version")) is not int or conf["version"] != 1:
        return invalid("bad-version")
    if not _strings(conf.get("non_deploying")):
        return invalid("bad-non-deploying")
    if "test_paths" in conf and not _strings(conf["test_paths"]):
        return invalid("bad-test-paths")
    return Deploy("ok", frozenset(conf["non_deploying"]),
                  tuple(conf["test_paths"]) if "test_paths" in conf else None)


def read_deploy(repo: str, base: str, io_timeout: float = policy.REVIEW_IO_TIMEOUT) -> Deploy:
    """`.boss/deploy.json` on `base`, as committed there. The branch is percent-encoded, so `release/1.0` is one value."""
    endpoint = "repos/%s/contents/.boss/deploy.json?ref=%s" % (repo, urllib.parse.quote(base, safe=""))
    run = boss_review._spawn(["gh", "api", endpoint], io_timeout)
    if run.timed_out or run.code is None:
        return Deploy("unreadable", frozenset(), None)
    if run.code != 0:
        return Deploy("missing" if "404" in run.err else "unreadable", frozenset(), None)
    return parse_deploy(run.out)


# ------------------------------------------------------------------------- the PR ----
class GhRead(Exception):
    """A `gh` read gave nothing I can use: exit 7."""


class Pr(NamedTuple):
    number: int
    path: str       # the url's path, lowercased
    head: str
    base: str
    state: str


def _gh_json(args: list[str], io_timeout: float) -> dict:
    run = boss_review._spawn(["gh", *args], io_timeout)
    if run.timed_out:
        raise GhRead("gh %s ran past %ss" % (" ".join(args[:2]), io_timeout))
    if run.code != 0:
        raise GhRead("gh %s failed (%s): %s" % (" ".join(args[:2]), run.code, run.err.strip()[-300:]))
    try:
        data = json.loads(run.out.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise GhRead("gh %s gave no JSON: %s" % (" ".join(args[:2]), type(exc).__name__))
    if not isinstance(data, dict):
        raise GhRead("gh %s gave no JSON object" % " ".join(args[:2]))
    return data


def read_pr(repo: str, pr: int, io_timeout: float) -> Pr:
    data = _gh_json(["pr", "view", str(pr), "--repo", repo, "--json", "number,url,headRefOid,baseRefName,state"],
                    io_timeout)
    try:
        number, url, head, base, state = (data[k] for k in ("number", "url", "headRefOid", "baseRefName", "state"))
        path = urllib.parse.urlparse(url).path.lower()
    except (KeyError, ValueError, AttributeError):
        raise GhRead("gh pr view gave no PR I can read")
    if (type(number) is not int or not all(isinstance(v, str) for v in (url, head, base, state))
            or not boss_review._SHA.fullmatch(head) or not base):
        raise GhRead("gh pr view gave a field of the wrong kind")
    return Pr(number, path, head, base, state)


# ----------------------------------------------------------------------- the command ----
def _alert(text: str) -> None:
    """`boss-alert 0 text`, as codex_blocker does it: a failure of it is said and changes nothing."""
    try:
        run = subprocess.run([codex_blocker.default_alert(), "0", text], capture_output=True, text=True,
                             timeout=ALERT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _say("boss-alert 0 failed: %s" % exc)
        return
    if run.returncode != 0:
        _say("boss-alert 0 failed (%s): %s" % (run.returncode, run.stderr.strip()[-200:]))


def _log(fields: dict) -> bool:
    """One line to pm/reviews/merges.jsonl, in a single O_APPEND write. False, said on stderr, when it was not written."""
    reviews = boss_review._reviews_dir()
    try:
        os.makedirs(reviews, mode=0o700, exist_ok=True)
        boss_review._private_dir(reviews)
        boss_review.append_attempts(reviews / "merges.jsonl", [fields])
    except OSError as exc:
        _say("merges.jsonl was not written: %s" % exc)
        return False
    return True


def merge(repo: str, pr: int, *, dry_run: bool = False, io_timeout: float = policy.REVIEW_IO_TIMEOUT) -> int:
    """Check, then merge. Raises ValueError for a `repo` or `pr` that is not a plain one (the command says exit 2)."""
    key = boss_review.repo_key(repo)
    if type(pr) is not int or pr < 1:
        raise ValueError("pr must be a positive integer: %r" % (pr,))
    line = {"ts": boss_review._now(), "repo": key, "pr": pr, "head": None, "base": None, "round": None,
            "kind": None, "decision": None, "exit": None, "reason": None, "config": None, "dry_run": dry_run}

    def finish(code: int, reason: str, decision: str, note: str = "") -> int:
        line.update(decision=decision, exit=code, reason=reason)
        _log(line)
        if code == EXIT_MERGED:
            print("%s %s#%d on %s (round %s, %s)" % ("would merge" if dry_run else "merged", key, pr, line["head"],
                                                       line["round"], line["kind"]))
        else:
            _say("%s: %s#%d: %s%s" % (decision, key, pr, reason, ": " + note if note else ""))
        return code

    try:
        seen = read_pr(repo, pr, io_timeout)
    except GhRead as exc:
        return finish(EXIT_GH_READ, "gh-read-failed", "refused", str(exc))
    line.update(head=seen.head, base=seen.base)
    if seen.number != pr or seen.path != "/%s/pull/%d" % (key, pr):
        return finish(EXIT_USAGE, "identity", "refused", "gh answered with another PR")
    if seen.state != "OPEN":
        return finish(EXIT_USAGE, "not-open", "refused", "the PR is %s" % seen.state)

    deploy = read_deploy(repo, seen.base, io_timeout)
    line["config"] = deploy.state
    reviews = boss_review._reviews_dir()
    pr_dir = reviews / key / ("pr%d" % pr)
    # the PR's lock, as a review takes it to claim a round: no round is claimed between this read of the rounds and the
    # return of `gh pr merge`, so a later round cannot be missed by a merge that is already under way
    try:
        lock = boss_review.open_lock(reviews, pr_dir, io_timeout)
    except OSError as exc:
        return finish(EXIT_GH_READ, "lock-failed", "refused", "cannot take the lock of %s: %s" % (pr_dir, exc))
    try:
        got = decide(read_rounds(pr_dir), seen.head, seen.base, deploy.non_deploying, (key, pr))
        line.update(round=got.round, kind=got.kind)
        if got.exit != EXIT_MERGED:
            return finish(got.exit, got.reason, "refused",
                          "deploy list " + deploy.state if got.exit == EXIT_DEPLOYING else "")
        if dry_run:
            return finish(EXIT_MERGED, got.reason, "allowed")
        # the intent first: a merge that GitHub accepted and a crash then hid would leave no line at all; no line, no merge
        if not _log(dict(line, decision="merging", reason=got.reason)):
            return finish(EXIT_MERGE_FAILED, "log-failed", "refused", "nothing merged")
        run = boss_review._spawn(["gh", "pr", "merge", str(pr), "--repo", repo, "--merge",
                                  "--match-head-commit", seen.head], io_timeout)
    finally:
        os.close(lock)
    if run.timed_out:
        _alert("boss_merge: gh pr merge of %s#%d ran past %ss; whether it merged is not known" % (key, pr, io_timeout))
        return finish(EXIT_MERGE_FAILED, "merge-timeout", "failed")
    if run.code != 0:
        return finish(EXIT_MERGE_FAILED, "merge-failed", "failed",
                      "gh pr merge exited %s: %s" % (run.code, run.err.strip()[-300:]))
    # `gh pr merge` can return 0 and leave the PR open or queued; no gh option pins the base, so a retarget in
    # the window is found here, after the fact
    try:
        after = _gh_json(["pr", "view", str(pr), "--repo", repo, "--json", "baseRefName,state"], io_timeout)
        state, now_base = after["state"], after["baseRefName"]
        if not isinstance(state, str) or not isinstance(now_base, str):
            raise GhRead("wrong kind")
        problem = None if state == "MERGED" and now_base == seen.base else \
            "not-merged" if state != "MERGED" else "base-changed"
    except (GhRead, KeyError):
        state, now_base, problem = None, None, "unverified"
    if problem:
        _alert("boss_merge: %s#%d (head %s) after gh pr merge: %s (state %s, base %s, checked on %s)"
               % (key, pr, seen.head, problem, state, now_base, seen.base))
        return finish(EXIT_MERGE_FAILED, problem, "failed")
    return finish(EXIT_MERGED, got.reason, "merged")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="boss_merge.py",
        description="Merge one PR if its review record allows it. Exit 0: merged (or allowed, with --dry-run). "
                    "2: usage, wrong PR, or the PR is not open. 3: no usable GO on the live head. 4: a provisional "
                    "or waived GO on a branch not listed as non-deploying. 5: the merge or the check after it "
                    "failed. 7: a gh read failed.")
    ap.add_argument("--repo", metavar="OWNER/REPO", required=True, help="never inferred from the directory")
    ap.add_argument("--pr", type=boss_review._pr_number, metavar="N", required=True)
    ap.add_argument("--dry-run", action="store_true", help="decide and log, but do not run gh pr merge")
    args = ap.parse_args(argv)
    try:
        return merge(args.repo, args.pr, dry_run=args.dry_run)
    except ValueError as exc:
        _say(str(exc))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
