#!/usr/bin/env python3
"""The merge gate (ticket 04): check the review record of one PR and merge it only if the record allows it.

    boss_merge.py --repo OWNER/REPO --pr N [--dry-run] [--test-only-since SHA | --merged-base-since SHA]   the command
    merge(repo, pr, dry_run=False, since=None, merged_since=None) -> int      the same, returning the exit code
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

`--test-only-since SHA` (ticket 11b) is the owner's rule that fixes after the last GO which touch only tests need no
new review. It is looked at only when the live head has no round that decides (`no-round`); any other answer for the
live head stands. Then SHA must be the head of a GO that `decide` allows with SHA as the head (so a provisional or
waived GO a later round supersedes, or one on a deploying base, does not qualify), no NO-GO may stand above that
round, and every file `gh api repos/R/compare/SHA...head` lists, a rename by both names, must match an entry of the
base branch's `test_paths` (`fnmatch.fnmatchcase` on the whole path, so `*` also crosses `/`). A compare that fails,
is not `ahead` or `identical`, or fills a page of 300 files refuses (3). A SHA that is not 40 lowercase hex digits is
exit 2. The `merges.jsonl` lines carry `since`, and the reason of a merge ends `-test-only`.

`--merged-base-since SHA` (ticket 50, review-by-risk rule 4) is the owner's rule that a head which differs from the last
GO only by merging the base branch in needs no new review. It is looked at in the same place as `--test-only-since`
(only on `no-round`), SHA is held to the same conditions (a GO `decide` allows, no NO-GO above it), and the two flags
cannot be given together. Three compares are read: SHA...head (the files that differ between the GO'd head and the live
one, and its commits), base...head and base...SHA (the PR's own files, each at its head). It passes only if the first
compare is `ahead`, lists all its commits and holds a merge commit, and none of the PR's own files at either head is
among the files that differ and the PR owns the same set of files at both heads (a merge that kept an old version of a file
main changed would add one to the live head's set). The base-side files of a merge are not the PR's, so they do not count; anything the PR
itself changed since the GO makes the PR's own files differ and refuses. A fourth compare, SHA...base, lists what the
base changed since it left the GO'd head; a PR-owned file among them refuses (`pr-file-changed-on-base`, ticket 54): a
conflict needs both sides to have changed the file, and keeping the reviewed text leaves it out of SHA...head. The reason
of a merge ends `-merged-base`.

Rule 2 (also ticket 50): a provisional GO on a base that deploys (exit 4 above) is let through when every file the PR
changes (base...head, a rename by both names) matches `test_paths` or `DOCS_PATHS`, and the head's check runs are all
complete and green. The GO is still required: no round on file is no merge. Docs are narrow on purpose: `README.md`,
`CHANGELOG.md` and `docs/*.md`, never a file an agent acts on (`SKILL.md`, `AGENTS.md`, `CLAUDE.md`, or anything under
a `skills`, `commands`, `agents`, `hooks`, `.claude` or `.github` directory). A waived GO does not qualify. The reason
of a merge is `provisional-go-docs-tests-only`.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
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

DOCS_PATHS = ("README.md", "CHANGELOG.md", "docs/*.md")     # what counts as docs: nothing an agent acts on
INSTRUCTION_NAMES = ("skill.md", "agents.md", "claude.md")      # compared in lower case, on the file's own name
INSTRUCTION_DIRS = ("skills", "commands", "agents", "hooks", ".claude", ".github")
GREEN = ("success", "neutral", "skipped")       # a check run's conclusions that do not block a merge

ALERT_TIMEOUT = 20      # seconds, as codex_blocker's
COMPARE_FILES = 300     # the most files a compare answers with: a page this long may have more behind it

FIELDS = ("repo", "pr", "round", "head_sha", "base", "kind", "verdict", "status")     # what the walk reads
KINDS = ("codex", "provisional", "waived")
VERDICTS = ("GO", "NO-GO", None)
STATUSES = ("posted", "head-moved", "no-verdict", "post-failed", "list-failed")
NOT_A_REVIEW = ("head-moved", "no-verdict", "list-failed")      # rounds that decide nothing

_ROUND_FILE = re.compile(r"round([0-9]+)\.json")
_SINCE = re.compile(r"[0-9a-f]{40}")        # goes into an endpoint: nothing but a full lowercase SHA-1


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


def no_go_above(rounds: list[Round], number: int, owner: tuple[str, int]) -> int | None:
    """The number of the lowest valid round above `number`, on any head, that holds a NO-GO (posted or not), else None.
    A GO was the last word only if nothing said no after it."""
    found = [r.number for r in rounds if r.number is not None and r.number > number
             and (rec := _valid(r, owner)) is not None and rec["verdict"] == "NO-GO"]
    return min(found) if found else None


# ------------------------------------------------------------------- the deploy list ----
class Deploy(NamedTuple):
    state: str                       # "ok", or why the file counts as invalid
    non_deploying: frozenset
    test_paths: tuple | None         # the patterns of `--test-only-since` (ticket 11b)
    required_checks: tuple | None = None    # the check runs rule 2 waits for (ticket 51), None when the key is absent


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
    if "required_checks" in conf and not _strings(conf["required_checks"]):
        return invalid("bad-required-checks")
    return Deploy("ok", frozenset(conf["non_deploying"]),
                  tuple(conf["test_paths"]) if "test_paths" in conf else None,
                  tuple(conf["required_checks"]) if "required_checks" in conf else None)


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
    base_sha: str = ""      # the base branch's tip the compares are made against (ticket 54), set by `merge`


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


def read_base_sha(repo: str, base: str, io_timeout: float) -> str:
    """The commit the base branch points at now; GhRead when it cannot be read as one."""
    data = _gh_json(["api", "repos/%s/git/ref/heads/%s" % (repo, urllib.parse.quote(base, safe="/"))], io_timeout)
    obj = data.get("object") if isinstance(data, dict) else None
    sha = obj.get("sha") if isinstance(obj, dict) else None
    if not isinstance(sha, str) or not boss_review._SHA.fullmatch(sha):
        raise GhRead("the base branch's ref gave no commit I can read")
    return sha


def read_first_parent(repo: str, commit: str, io_timeout: float) -> str:
    """The first parent of `commit`, the base's tip when a merge commit was made; GhRead when it cannot be read."""
    data = _gh_json(["api", "repos/%s/commits/%s" % (repo, commit)], io_timeout)
    parents = data.get("parents") if isinstance(data, dict) else None
    sha = parents[0].get("sha") if isinstance(parents, list) and parents and isinstance(parents[0], dict) else None
    if not isinstance(sha, str) or not boss_review._SHA.fullmatch(sha):
        raise GhRead("the merge commit lists no parent I can read")
    return sha


_QUEUE_QUERY = ("query($owner:String!,$name:String!,$base:String!,$number:Int!){repository(owner:$owner,name:$name)"
                "{mergeQueue(branch:$base){id} pullRequest(number:$number){autoMergeRequest{enabledAt} isInMergeQueue}}}")


def queue_problem(repo: str, pr: int, base: str, io_timeout: float) -> tuple[str, str] | None:
    """(reason, note) when the merge must not be made because something could be left scheduled: a merge queue on the
    base (a ruleset of type merge_queue, or the queue GitHub reports for the branch, which covers legacy protection too),
    or an auto-merge request or queue entry the PR already has. None when all of that was read and is absent. Fails
    closed: whatever cannot be read refuses (ticket 54: the gate never passes `--auto`, so on a base with no queue
    `gh pr merge` merges or fails and schedules nothing)."""
    run = boss_review._spawn(["gh", "api", "repos/%s/rules/branches/%s" % (repo, urllib.parse.quote(base, safe=""))],
                             io_timeout)
    try:
        if run.timed_out or run.code != 0:
            raise ValueError("the branch rules could not be read")
        rules = json.loads(run.out.decode("utf-8"))
        if not isinstance(rules, list) or not all(isinstance(r, dict) and isinstance(r.get("type"), str) for r in rules):
            raise ValueError("the branch rules are not a list I can read")
        if any(r["type"] == "merge_queue" for r in rules):
            return "merge-queue-unsupported", "%s has a merge-queue rule" % base
        owner, _, name = repo.partition("/")
        run = boss_review._spawn(["gh", "api", "graphql", "-f", "query=" + _QUEUE_QUERY, "-f", "owner=" + owner,
                                  "-f", "name=" + name, "-f", "base=" + base, "-F", "number=%d" % pr], io_timeout)
        if run.timed_out or run.code != 0:
            raise ValueError("the merge queue could not be read")
        repo_node = json.loads(run.out.decode("utf-8"))["data"]["repository"]
        node = repo_node["pullRequest"]
        if "mergeQueue" not in repo_node or "autoMergeRequest" not in node or type(node["isInMergeQueue"]) is not bool:
            raise ValueError("a field is missing")
        if repo_node["mergeQueue"] is not None:
            return "merge-queue-unsupported", "%s has a merge queue" % base
        if node["autoMergeRequest"] is not None or node["isInMergeQueue"]:
            return "merge-queue-unsupported", "the PR already has an auto-merge request or a merge-queue entry"
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        return "gh-read-failed", "merge queues are not supported and cannot be ruled out: %s" % exc
    return None


class Compare(NamedTuple):
    problem: str | None         # None, or the reason the compare cannot be used
    files: tuple = ()           # every name a changed file had, before and after a rename
    note: str = ""
    parents: tuple | None = None    # the number of parents of each commit listed, None when the list is not whole


def read_compare(repo: str, since: str, head: str, io_timeout: float,
                 statuses: tuple = ("ahead", "identical")) -> Compare:
    """The files changed from `since` to `head`. Each is a full SHA or a branch name; the endpoint quotes both."""
    run = boss_review._spawn(["gh", "api", "repos/%s/compare/%s...%s" % (
        repo, urllib.parse.quote(since, safe=""), urllib.parse.quote(head, safe=""))], io_timeout)
    if run.timed_out or run.code != 0:
        why = "ran past %ss" % io_timeout if run.timed_out else "failed (%s): %s" % (run.code, run.err.strip()[-200:])
        return Compare("compare-failed", note="gh api compare " + why)
    try:
        data = json.loads(run.out.decode("utf-8"))
    except (ValueError, RecursionError):
        return Compare("compare-failed", note="gh api compare gave no JSON")
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return Compare("compare-failed", note="gh api compare listed no files")
    if data.get("status") not in statuses:
        return Compare("compare-not-ahead", note="the compare says %r" % (data.get("status"),))
    if not files and data["status"] not in ("identical", "behind"):     # commits on the head and no file listed: not trusted
        return Compare("compare-no-files", note="the compare is %s and lists no file" % data["status"])
    if len(files) >= COMPARE_FILES:
        return Compare("compare-truncated", note="%d files is the API's limit, there may be more" % len(files))
    names = []
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("filename"), str) \
                or not isinstance(f.get("previous_filename", ""), str):
            return Compare("compare-failed", note="a file entry I cannot read")
        names += [f["filename"]] + ([f["previous_filename"]] if f.get("previous_filename") else [])
    return Compare(None, tuple(names), parents=_parents(data))


def _parents(data: dict) -> tuple | None:
    """How many parents each listed commit has; None when the commits are missing, cut short or unreadable."""
    commits, total = data.get("commits"), data.get("total_commits")
    if not isinstance(commits, list) or type(total) is not int or total != len(commits):
        return None
    counts = []
    for c in commits:
        parents = c.get("parents") if isinstance(c, dict) else None
        if not isinstance(parents, list):
            return None
        counts.append(len(parents))
    return tuple(counts)


def read_checks(repo: str, head: str, io_timeout: float, required: tuple = ()) -> tuple[bool, str]:
    """(are the check runs of `head` all complete and green, why not). No check run is not green: it means nothing ran.
    Every name in `required` must be among the runs and have succeeded: a run not created yet is not seen in a list of
    what exists now, so only the names the repo declares say that all of its CI has run."""
    run = boss_review._spawn(["gh", "api", "repos/%s/commits/%s/check-runs?per_page=100" % (repo, head)], io_timeout)
    if run.timed_out or run.code != 0:
        return False, "the check runs could not be read"
    try:
        data = json.loads(run.out.decode("utf-8"))
        runs, total = data["check_runs"], data["total_count"]
    except (ValueError, RecursionError, KeyError, TypeError):
        return False, "the check runs gave no list I can read"
    if not isinstance(runs, list) or type(total) is not int or total != len(runs):
        return False, "the check runs are not all listed"
    if not runs:
        return False, "no check ran on this head"
    if not any(isinstance(r, dict) and r.get("conclusion") == "success" for r in runs):
        return False, "no check run succeeded (all skipped or neutral means nothing ran)"
    for name in required:
        if not any(isinstance(r, dict) and r.get("name") == name and r.get("status") == "completed"
                   and r.get("conclusion") == "success" for r in runs):
            return False, "required check %r has not succeeded on this head" % name
    for r in runs:
        if not isinstance(r, dict) or r.get("status") != "completed" or r.get("conclusion") not in GREEN:
            return False, "check %r is %s/%s" % (r.get("name") if isinstance(r, dict) else None,
                                                  r.get("status") if isinstance(r, dict) else None,
                                                  r.get("conclusion") if isinstance(r, dict) else None)
    return True, ""


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


def test_only(rounds: list[Round], since: str, seen: Pr, deploy: Deploy, owner: tuple[str, int], repo: str,
              io_timeout: float) -> tuple[Decision, str]:
    """The `--test-only-since` rule for a PR whose live head has no deciding round: the decision, and a note for the
    refusal line. Allowed (exit 0) only if SHA is a GO `decide` allows as the head, nothing says no after it, and
    every file changed since matches `test_paths`."""
    got = decide(rounds, since, seen.base, deploy.non_deploying, owner)
    if got.exit != EXIT_MERGED:
        return (got, "") if got.reason != "no-round" else (got, "%s is the head of no GO round" % since)
    no = no_go_above(rounds, got.round, owner)
    if no is not None:
        return Decision(EXIT_REFUSED, "no-go-after-since", got.round, got.kind), "round %d says NO-GO" % no
    if deploy.test_paths is None:
        return Decision(EXIT_REFUSED, "no-test-paths", got.round, got.kind), "deploy list " + deploy.state
    cmp = read_compare(repo, since, seen.head, io_timeout)
    if cmp.problem:
        return Decision(EXIT_REFUSED, cmp.problem, got.round, got.kind), cmp.note
    stray = [n for n in cmp.files if not any(fnmatch.fnmatchcase(n, pat) for pat in deploy.test_paths)]
    if stray:
        return Decision(EXIT_REFUSED, "not-test-only", got.round, got.kind), "outside test_paths: " + ", ".join(stray[:5])
    return Decision(EXIT_MERGED, got.reason + "-test-only", got.round, got.kind), ""


def is_instruction(name: str) -> bool:
    """A file an agent acts on (ticket 50: SKILL.md and its kin are code), whatever pattern would otherwise match it."""
    parts = name.split("/")
    return parts[-1].casefold() in INSTRUCTION_NAMES or any(p.casefold() in INSTRUCTION_DIRS for p in parts[:-1])


def is_doc(name: str) -> bool:
    """A file that is documentation: the narrow docs set, never an instruction file."""
    if is_instruction(name):
        return False
    return any(fnmatch.fnmatchcase(name, pat) for pat in DOCS_PATHS)


def not_docs_or_tests(names: tuple, test_paths: tuple) -> list[str]:
    """The names that are neither docs nor a match of `test_paths`; none at all is a PR with nothing to judge, refused."""
    if not names:
        return ["(no file)"]
    return [n for n in names if is_instruction(n) or not (
        is_doc(n) or any(fnmatch.fnmatchcase(n, pat) for pat in test_paths))]


def touched_by_the_pr(own: tuple, since_changes: tuple) -> list[str]:
    """The PR's own files that differ between the GO'd head and the live one: a merge of the base brings none."""
    return [n for n in since_changes if n in own]


BASE_SIDE_STATUSES = ("ahead", "diverged", "behind", "identical")   # SHA...base: `behind` is a base that has not moved on


OWN_STATUSES = ("ahead", "diverged", "identical")       # a PR's files against a base that may have moved on


def files_problem(files: tuple, deploy: Deploy) -> str | None:
    """Why these files, the PR's own against its base, are not all docs or tests (rule 2's file condition, which
    `boss_review.py --opus-direct` asks too, ticket 52), None when they are. Fails closed: no `test_paths`, no file."""
    if deploy.test_paths is None:
        return "no test_paths in the deploy list"
    stray = not_docs_or_tests(files, deploy.test_paths)
    return "not docs or tests: " + ", ".join(stray[:5]) if stray else None


def docs_tests_problem(files: tuple, head: str, deploy: Deploy, repo: str, io_timeout: float) -> str | None:
    """Why the PR is not a docs/tests-only PR with all its CI green on `head` (rule 2's conditions), None when it is.
    `files` are the PR's own files against its base."""
    if deploy.test_paths is None:
        return "no test_paths in the deploy list"
    if not deploy.required_checks:
        return "no required_checks in the deploy list (the check runs that exist now do not say all of CI has run)"
    why = files_problem(files, deploy)
    if why:
        return why
    green, why = read_checks(repo, head, io_timeout, deploy.required_checks)
    return None if green else why


def docs_tests_only(seen: Pr, got: Decision, deploy: Deploy, repo: str, io_timeout: float) -> tuple[Decision, str]:
    """Review-by-risk rule 2 for a provisional GO that `decide` refused as `deploying-base`: allowed when every file the
    PR changes is docs or a test and every check the deploy list requires has succeeded on the head. Otherwise the
    refusal stands (4), with the reason."""
    def stay(note: str) -> tuple[Decision, str]:
        return got, "deploy list %s; docs/tests-only rule: %s" % (deploy.state, note)

    if deploy.test_paths is None or not deploy.required_checks:       # before any read: the rule cannot pass
        return stay(docs_tests_problem((), seen.head, deploy, repo, io_timeout))
    own = read_compare(repo, seen.base_sha, seen.head, io_timeout, OWN_STATUSES)
    if own.problem:
        return stay("%s: %s" % (own.problem, own.note))
    why = docs_tests_problem(own.files, seen.head, deploy, repo, io_timeout)
    if why:
        return stay(why)
    return Decision(EXIT_MERGED, "provisional-go-docs-tests-only", got.round, got.kind), ""


def merged_base(rounds: list[Round], since: str, seen: Pr, deploy: Deploy, owner: tuple[str, int], repo: str,
                io_timeout: float) -> tuple[Decision, str]:
    """Review-by-risk rule 4 for a PR whose live head has no deciding round: allowed only if SHA is a GO `decide` allows
    as the head, nothing says no after it, and the live head is SHA plus a merge of the base that touches none of the
    PR's own files. A provisional GO on a deploying base qualifies too, as rule 2 allows it (ticket 51): the PR's files are
    then docs and tests only and the required checks have succeeded on the live head."""
    got = decide(rounds, since, seen.base, deploy.non_deploying, owner)
    docs_tests = got.exit == EXIT_DEPLOYING and got.kind == "provisional"
    if got.exit != EXIT_MERGED and not docs_tests:
        return (got, "") if got.reason != "no-round" else (got, "%s is the head of no GO round" % since)
    no = no_go_above(rounds, got.round, owner)
    if no is not None:
        return Decision(EXIT_REFUSED, "no-go-after-since", got.round, got.kind), "round %d says NO-GO" % no

    def refuse(reason: str, note: str) -> tuple[Decision, str]:
        return Decision(EXIT_REFUSED, reason, got.round, got.kind), note

    changed = read_compare(repo, since, seen.head, io_timeout)
    if changed.problem:
        return refuse(changed.problem, changed.note)
    if changed.parents is None:
        return refuse("compare-commits", "the compare does not list its commits whole")
    if not any(p >= 2 for p in changed.parents):
        return refuse("no-merge-commit", "no commit since %s is a merge" % since)
    own_at = {}
    for end in (seen.head, since):
        own = read_compare(repo, seen.base_sha, end, io_timeout, OWN_STATUSES)
        if own.problem:
            return refuse(own.problem, own.note)
        if not own.files:       # a PR that owns nothing has nothing the compare can prove unchanged, whatever its status
            return refuse("pr-owns-nothing", "the PR lists no file against %s at %s" % (seen.base, end[:12]))
        own_at[end] = set(own.files)
    stray = touched_by_the_pr(tuple(own_at[seen.head] | own_at[since]), changed.files)
    if stray:
        return refuse("pr-files-changed", "differ since %s: %s" % (since, ", ".join(sorted(set(stray))[:5])))
    # a merge that keeps an old version of a file main changed leaves that file out of SHA...head and into the PR's own
    # files: the PR must own the same files at both heads, or the merge undid something no review saw
    moved = sorted(own_at[seen.head] ^ own_at[since])
    if moved:
        return refuse("pr-file-set-changed", "owned at one head only: " + ", ".join(moved[:5]))
    # a merge that resolved a conflict in a PR file by keeping the reviewed text drops that file out of SHA...head and
    # leaves it in both own sets, so none of the checks above sees it. A conflict needs both sides to have changed the
    # file: refuse whenever the base changed a PR-owned file since it left the GO'd head, resolved or not (ticket 54)
    on_base = read_compare(repo, since, seen.base_sha, io_timeout, BASE_SIDE_STATUSES)
    if on_base.problem:
        return refuse(on_base.problem, on_base.note)
    clash = touched_by_the_pr(tuple(own_at[seen.head] | own_at[since]), on_base.files)
    if clash:
        return refuse("pr-file-changed-on-base", "the base changed it since %s: %s" % (since[:12], ", ".join(sorted(set(clash))[:5])))
    if docs_tests:      # the PR's files are the same at both heads, so the GO'd head's own files are the live head's
        why = docs_tests_problem(tuple(own_at[seen.head]), seen.head, deploy, repo, io_timeout)
        if why:
            return got, "deploy list %s; docs/tests-only rule: %s" % (deploy.state, why)
        return Decision(EXIT_MERGED, "provisional-go-docs-tests-only-merged-base", got.round, got.kind), ""
    return Decision(EXIT_MERGED, got.reason + "-merged-base", got.round, got.kind), ""


def merge(repo: str, pr: int, *, dry_run: bool = False, since: str | None = None, merged_since: str | None = None,
          io_timeout: float = policy.REVIEW_IO_TIMEOUT) -> int:
    """Check, then merge. Raises ValueError for a `repo`, `pr` or `since` that is not a plain one (the command says
    exit 2). `since` is the head of the last GO, for the test-only exception; `merged_since` is the same for the merge-of-base one,
    and the two are not given together."""
    key = boss_review.repo_key(repo)
    if type(pr) is not int or pr < 1:
        raise ValueError("pr must be a positive integer: %r" % (pr,))
    if since is not None and (not isinstance(since, str) or not _SINCE.fullmatch(since)):
        raise ValueError("--test-only-since must be 40 lowercase hex digits: %r" % (since,))
    line = {"ts": boss_review._now(), "repo": key, "pr": pr, "head": None, "base": None, "round": None,
            "kind": None, "decision": None, "exit": None, "reason": None, "config": None, "dry_run": dry_run,
            "base_sha": None}
    if merged_since is not None and (not isinstance(merged_since, str) or not _SINCE.fullmatch(merged_since)):
        raise ValueError("--merged-base-since must be 40 lowercase hex digits: %r" % (merged_since,))
    if since is not None and merged_since is not None:
        raise ValueError("--test-only-since and --merged-base-since are not given together")
    if since is not None or merged_since is not None:
        line["since"] = since or merged_since

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

    try:        # one tip for every compare below, and the one the merge is checked against (ticket 54)
        seen = seen._replace(base_sha=read_base_sha(repo, seen.base, io_timeout))
    except GhRead as exc:
        return finish(EXIT_GH_READ, "gh-read-failed", "refused", str(exc))
    line["base_sha"] = seen.base_sha
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
        everything = read_rounds(pr_dir)
        got = decide(everything, seen.head, seen.base, deploy.non_deploying, (key, pr))
        note = "deploy list " + deploy.state if got.exit == EXIT_DEPLOYING else ""
        if got.exit == EXIT_DEPLOYING and got.kind == "provisional":        # rule 2; a waived GO never qualifies
            got, note = docs_tests_only(seen, got, deploy, repo, io_timeout)
        if since is not None and got.reason == "no-round":      # any other answer for the live head stands
            got, note = test_only(everything, since, seen, deploy, (key, pr), repo, io_timeout)
        if merged_since is not None and got.reason == "no-round":
            got, note = merged_base(everything, merged_since, seen, deploy, (key, pr), repo, io_timeout)
        line.update(round=got.round, kind=got.kind)
        if got.exit != EXIT_MERGED:
            return finish(got.exit, got.reason, "refused", note)
        queued = queue_problem(repo, pr, seen.base, io_timeout)       # before the dry run too: it must say what the merge would
        if queued:
            return finish(EXIT_GH_READ if queued[0] == "gh-read-failed" else EXIT_REFUSED, queued[0], "refused", queued[1])
        if dry_run:
            return finish(EXIT_MERGED, got.reason, "allowed")
        try:        # no gh option pins the base: if it moved since the compares, they say nothing about this merge
            tip = read_base_sha(repo, seen.base, io_timeout)
        except GhRead as exc:
            return finish(EXIT_GH_READ, "gh-read-failed", "refused", str(exc))
        if tip != seen.base_sha:
            return finish(EXIT_REFUSED, "base-moved", "refused", "%s was %s when read, %s now; run again" % (
                seen.base, seen.base_sha[:12], tip[:12]))
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
    # the window is found here, after the fact, and so is a base that moved: the merge commit's first parent is the
    # tip the merge was made on, and it must be the one the compares were made against
    merged_on = None
    try:
        after = _gh_json(["pr", "view", str(pr), "--repo", repo, "--json", "baseRefName,state,mergeCommit"], io_timeout)
        state, now_base = after["state"], after["baseRefName"]
        if not isinstance(state, str) or not isinstance(now_base, str):
            raise GhRead("wrong kind")
        problem = None if state == "MERGED" and now_base == seen.base else \
            "merge-not-completed" if state != "MERGED" else "base-changed"
        if problem is None:
            oid = (after.get("mergeCommit") or {}).get("oid")
            if not isinstance(oid, str) or not boss_review._SHA.fullmatch(oid):
                raise GhRead("no merge commit")
            merged_on = read_first_parent(repo, oid, io_timeout)
            if merged_on != seen.base_sha:
                problem = "base-moved-during-merge"
    except (GhRead, KeyError, AttributeError):
        state, now_base, problem = None, None, "unverified"
    if problem:
        _alert("boss_merge: %s#%d (head %s) after gh pr merge: %s (state %s, base %s, checked on %s, compares made on %s, "
               "merge made on %s). A merge cannot be undone: the owner must check by hand what was merged"
               % (key, pr, seen.head, problem, state, now_base, seen.base, seen.base_sha, merged_on))
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
    ap.add_argument("--test-only-since", metavar="SHA", dest="since",
                    help="the head of the last GO: allow the merge if every file changed since matches the base "
                         "branch's test_paths (40 lowercase hex digits)")
    ap.add_argument("--merged-base-since", metavar="SHA", dest="merged_since",
                    help="the head of the last GO: allow the merge if the live head is that head plus a merge of the "
                         "base branch that changes none of the PR's own files (40 lowercase hex digits)")
    args = ap.parse_args(argv)
    try:
        return merge(args.repo, args.pr, dry_run=args.dry_run, since=args.since, merged_since=args.merged_since)
    except ValueError as exc:
        _say(str(exc))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
