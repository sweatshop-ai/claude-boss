#!/usr/bin/env python3
"""Review one PR head with Codex, keep the round on disk, post a minimal comment.

    review(repo, pr, checkout, author) -> ReviewResult      the logic
    boss_review.py --repo OWNER/REPO --pr N --checkout DIR --author NAME   the command

Exit codes (5 belongs to a later ticket and is never used here):

    0 GO posted        3 NO-GO posted       4 Codex gave no verdict (absent, timeout, error, noverdict)
    2 usage, the PR is not the one asked for, or the checkout is not on its head
    6 the PR's head or base (or the checkout's head) moved during the review: nothing posted
    7 infrastructure: gh, the chain or a write failed

The order: read the PR, ask Codex (01's chain, Codex only, in a child process started in the
checkout), then under the PR's lock read the PR again, claim the next round, append the attempts,
write the answer, post, and replace the claimed file by the full record. A failure before the
claim leaves nothing; one after it leaves the claimed file empty. Rounds live under
$CLAUDE_CONFIG_DIR/pm/reviews/<owner>/<repo>/pr<N>/ (round<NN>.json and .out), never in the
checkout; the record, not the comment, is what a gate reads. Standard library only.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import boss_store
import policy
from reviewer_chain import STDERR_TAIL, _snapshot, _stop

HERE = Path(__file__).resolve().parent
CHAIN = HERE / "reviewer_chain.py"

REVIEW_EFFORT = "high"     # Codex reasoning effort: a PR review is the gate, not a quick check

EXIT_GO, EXIT_USAGE, EXIT_NO_GO, EXIT_NO_VERDICT, EXIT_MOVED, EXIT_INFRA = 0, 2, 3, 4, 6, 7
EXIT_FOR_VERDICT = {"GO": EXIT_GO, "NO-GO": EXIT_NO_GO}


@dataclass(frozen=True)
class ReviewResult:
    exit_code: int
    round: int | None
    status: str | None
    verdict: str | None
    record: Path | None


NAME = re.compile(r"[A-Za-z0-9._-]+")      # fullmatch: `$` would let a trailing newline through


def check_name(name: str, what: str) -> str:
    """`name` itself when it is a plain name, else ValueError."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("%s must match %s: %r" % (what, NAME.pattern, name))
    return name


def repo_key(repo: str) -> str:
    """`<owner>/<repo>` lowercased, for the directory, the lock and every record of the PR.

    GitHub treats the two names case-insensitively, so this is the one spelling kept on disk. It
    raises ValueError for anything but two plain names, so nothing built from it can leave
    the reviews directory: callers never build a path from --repo as typed.
    """
    parts = repo.split("/") if isinstance(repo, str) else []
    if len(parts) != 2:
        raise ValueError("repo must be OWNER/REPO: %r" % (repo,))
    for part in parts:
        check_name(part, "owner and repo")
        if part in (".", ".."):
            raise ValueError("owner and repo cannot be %r: %r" % (part, repo))
    return repo.lower()


class _Infra(Exception):
    """A tool or a file did not do its part: exit 7."""


def _say(message: str) -> None:
    print("boss_review: " + message, file=sys.stderr)


# ----------------------------------------------------------------------- processes ----
class _Out(NamedTuple):
    code: int | None     # None after a timeout and when the program could not be started
    out: bytes
    err: str
    timed_out: bool


def _spawn(argv: list[str], timeout: float, cwd: str | None = None) -> _Out:
    """Run one program with a closed stdin, its output in temporary files, and stop it and
    everything it started when it outlasts `timeout` (the same discipline as the chain's)."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=True)
        except OSError as exc:
            return _Out(None, b"", str(exc), False)
        try:
            code, timed_out = proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            _stop(proc)
            code, timed_out = None, True
        except BaseException:
            _stop(proc)
            raise
        return _Out(code, _snapshot(out), _snapshot(err, STDERR_TAIL).decode("utf-8", "replace"), timed_out)


# ---------------------------------------------------------------------- the PR (gh) ----
class _Job(NamedTuple):
    """What one review is about: the repo as typed, its key, the PR, the checkout, who runs it,
    and how long gh and git may take."""
    repo: str
    key: str
    pr: int
    checkout: str
    author: str
    io_timeout: float


class _Pr(NamedTuple):
    number: int
    url: str
    head: str
    base: str


_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def _read_pr(job: _Job) -> _Pr:
    run = _spawn(["gh", "pr", "view", str(job.pr), "--repo", job.repo, "--json",
                  "number,url,headRefOid,baseRefName"], job.io_timeout)
    if run.timed_out:
        raise _Infra("gh pr view ran past %ss" % job.io_timeout)
    if run.code != 0:
        raise _Infra("gh pr view failed (%s): %s" % (run.code, run.err.strip()[-300:]))
    try:
        data = json.loads(run.out.decode("utf-8"))
        number, url, head, base = (data[k] for k in ("number", "url", "headRefOid", "baseRefName"))
    except (ValueError, KeyError, TypeError) as exc:
        raise _Infra("gh pr view gave no PR I can read: %s: %s" % (type(exc).__name__, exc))
    if (type(number) is not int or not all(isinstance(v, str) for v in (url, head, base))
            or not _SHA.fullmatch(head) or not base):
        raise _Infra("gh pr view gave a field of the wrong kind")
    return _Pr(number, url, head, base)


def _is_the_pr(seen: _Pr, job: _Job) -> bool:
    """The PR gh answered with is the one asked for: its number, and a URL path of
    /<owner>/<repo>/pull/<N> (the names compared without case)."""
    path = urllib.parse.urlparse(seen.url).path.lower()
    return seen.number == job.pr and path == "/%s/pull/%d" % (job.key, job.pr)


def _checkout_head(job: _Job) -> str | None:
    """The commit the checkout stands on, or None when it is not a git checkout. A git that cannot
    be run or outlasts the wait is _Infra: that says nothing about which commit it stands on."""
    run = _spawn(["git", "-C", job.checkout, "rev-parse", "HEAD"], job.io_timeout)
    if run.timed_out or run.code is None:
        raise _Infra("git rev-parse %s" % ("ran past %ss" % job.io_timeout if run.timed_out
                                           else "could not be run: %s" % run.err.strip()[-300:]))
    return run.out.decode("utf-8", "replace").strip() if run.code == 0 else None


def build_brief(head_sha: str, base: str) -> str:
    """The fixed brief: no PR title, body or diff (the fenced PR text is a later ticket's)."""
    return (
        "You are reviewing a pull request. Read only: change nothing in this checkout and run "
        "nothing that writes.\n"
        "The checked-out HEAD is commit %s. The pull request merges it into the base branch "
        "`%s`.\n"
        "Review that head against the base: read the diff (for example `git diff origin/%s...HEAD`, "
        "or `git diff %s...HEAD` when there is no origin) and the files it touches. Report real "
        "defects: wrong behaviour, missed cases, broken tests, security or privacy problems. "
        "Not style.\n"
        "Answer with one `FINDING:` line per defect (file, line, what is wrong), then, as the "
        "last line, exactly one of `VERDICT: GO` or `VERDICT: NO-GO`. Say NO-GO when any finding "
        "must be fixed before the merge, GO otherwise.\n" % (head_sha, base, base, base))


_ATTEMPT_KEYS = ("reviewer", "reason", "output", "exit_code", "stderr_tail", "model")


def _chain_result(run: _Out) -> dict:
    """The chain's JSON, once it is plainly a Codex-only result; else _Infra. A child that
    crashed, was killed or printed something else says nothing about Codex, so it is no outage."""
    if run.timed_out:
        raise _Infra("the chain ran past its time and was stopped")
    if run.code not in (0, 1):
        raise _Infra("the chain exited %s: %s" % (run.code, run.err.strip()[-300:]))
    try:
        data = json.loads(run.out.decode("utf-8"))
        reviewer, output, parsed, attempts = (data[k] for k in ("reviewer", "output", "parsed", "attempts"))
        word = None if parsed is None else parsed["word"]
        sound = (reviewer in ("codex", "none") and isinstance(output, str)
                 and (word is None) == (reviewer == "none") and (word is None or word in EXIT_FOR_VERDICT)
                 and isinstance(attempts, list) and attempts
                 and all(isinstance(a, dict) and all(k in a for k in _ATTEMPT_KEYS) for a in attempts))
    except (ValueError, KeyError, TypeError) as exc:
        raise _Infra("the chain printed no result I can read: %s: %s" % (type(exc).__name__, exc))
    if not sound:
        raise _Infra("the chain printed a result that is not a Codex-only one")
    return data


def _ask_codex(checkout: str, head: str, base: str, codex_timeout: int) -> dict:
    """01's chain in a child process whose working directory is the checkout, so every reviewer
    it starts inherits that directory (`run_chain` has no parameter for one)."""
    with tempfile.TemporaryDirectory(prefix="boss-review-") as tmp:
        prompt = Path(tmp) / "prompt.txt"
        prompt.write_text(build_brief(head, base), encoding="utf-8")
        run = _spawn([sys.executable, str(CHAIN), "--prompt-file", str(prompt), "--words", "GO,NO-GO",
                      "--match", "token", "--strict", "--no-fallback", "--effort", REVIEW_EFFORT,
                      "--codex-timeout", str(codex_timeout)],
                     codex_timeout + policy.REVIEW_CHAIN_SLACK, cwd=checkout)
    return _chain_result(run)


# ------------------------------------------------------------------- writing rounds ----
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _private_dir(path: Path) -> None:
    """`path` is a real directory of mode 0700: made so if missing, tightened if wider. A symlink
    is refused: chmod would follow it and change someone else's directory."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise OSError("%s is not a directory" % path)
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(path, 0o700)


def open_lock(reviews: Path, pr_dir: Path, timeout: float) -> int:
    """Make `reviews` and each directory down to `pr_dir` private (0700), open `pr_dir`'s `.lock`
    (0600) and take it, waiting at most `timeout`. Returns the descriptor that holds the lock.
    The `pm` directory above `reviews` is made 0700 if missing, never tightened: it is not ours."""
    reviews.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    here = reviews
    _private_dir(here)
    for part in pr_dir.relative_to(reviews).parts:
        here = here / part
        _private_dir(here)
    fd = os.open(pr_dir / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("the lock on %s is held" % pr_dir)
                time.sleep(0.05)
    except BaseException:
        os.close(fd)
        raise


_ROUND_FILE = re.compile(r"round(\d+)\.(?:json|out)")


def claim_round(pr_dir: Path) -> tuple[int, Path]:
    """Create `round<NN>.json`, empty, one past the highest round file, and return its number and
    path. Never a free number below a higher one: numbers follow the order rounds were claimed."""
    taken = [int(m.group(1)) for entry in pr_dir.iterdir() if (m := _ROUND_FILE.fullmatch(entry.name))]
    n = max(taken, default=0) + 1
    while True:
        path = pr_dir / ("round%02d.json" % n)
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            n += 1
            continue
        return n, path


def append_attempts(path: Path, entries: list[dict]) -> None:
    """One O_APPEND write for the whole run."""
    data = "".join(json.dumps(entry) + "\n" for entry in entries).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        if os.write(fd, data) != len(data):
            raise OSError("short write to %s" % path)
    finally:
        os.close(fd)


def write_out(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(text.encode("utf-8", "replace"))


def replace_record(path: Path, record: dict) -> None:
    """The claimed file becomes the full record: temp file, then rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".round-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write((json.dumps(record, indent=2) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _out_text(chain: dict) -> str:
    """The answering attempt's full output; when nobody answered, every attempt's raw output
    under a `--- <reviewer> <reason> ---` line."""
    if chain["reviewer"] != "none":
        return chain["output"]
    sections = []
    for a in chain["attempts"]:
        text = a["output"]
        sections.append("--- %s %s ---\n%s" % (a["reviewer"], a["reason"],
                                               text if not text or text.endswith("\n") else text + "\n"))
    return "".join(sections)


def _reviews_dir() -> Path:
    return boss_store.pm_dir() / "reviews"


# --------------------------------------------------------------------------- review ----
def comment_body(number: int, author: str, head_sha: str, verdict: str) -> str:
    """The comment: fixed words, the round, a validated name, the head reviewed and the verdict."""
    return "Codex review %d (run by %s)\nHead: %s\nVerdict: %s" % (number, author, head_sha, verdict)


def _nothing(exit_code: int) -> ReviewResult:
    """A result with no round: the command ended before it claimed one."""
    return ReviewResult(exit_code, None, None, None, None)


def _failed(message: str) -> ReviewResult:
    _say(message)
    return _nothing(EXIT_INFRA)


def _refused(message: str) -> ReviewResult:
    _say(message)
    return _nothing(EXIT_USAGE)


def _prepare(job: _Job) -> _Pr | ReviewResult:
    """The PR as gh describes it, once it is the PR asked for and the checkout stands on its head;
    else the result that ends the command before anything is claimed."""
    try:
        seen = _read_pr(job)
        if not _is_the_pr(seen, job):
            return _refused("gh answered with %s (number %d), not pull request %d of %s"
                            % (seen.url, seen.number, job.pr, job.repo))
        if _checkout_head(job) != seen.head:
            return _refused("the HEAD of %s is not the head of the PR, %s" % (job.checkout, seen.head))
    except _Infra as exc:
        return _failed(str(exc))
    if Path(os.path.realpath(_reviews_dir())).is_relative_to(os.path.realpath(job.checkout)):
        return _failed("the reviews directory %s is inside the checkout %s" % (_reviews_dir(), job.checkout))
    return seen


def _post(job: _Job, body: str) -> bool:
    run = _spawn(["gh", "pr", "comment", str(job.pr), "--repo", job.repo, "--body", body], job.io_timeout)
    if run.code != 0:
        _say("gh pr comment %s" % ("ran past %ss" % job.io_timeout if run.timed_out
                                   else "failed (%s): %s" % (run.code, run.err.strip()[-300:])))
    return run.code == 0


def _keep_and_post(job: _Job, seen: _Pr, chain: dict) -> ReviewResult:
    """Under the PR's lock: look at the PR and the checkout again, claim the next round, keep what
    the review said, post, and make the claimed file the full record."""
    reviews = _reviews_dir()
    pr_dir = reviews / job.key / ("pr%d" % job.pr)
    try:
        lock = open_lock(reviews, pr_dir, job.io_timeout)
    except OSError as exc:
        return _failed("cannot take the lock of %s: %s" % (pr_dir, exc))
    try:
        try:
            live = _read_pr(job)
            standing_on = _checkout_head(job)
            number, path = claim_round(pr_dir)
        except (_Infra, OSError) as exc:
            return _failed("nothing claimed: %s" % exc)
        ts = _now()           # the claim's time: it rises with the round number, whoever waited for the lock
        attempts = [{k: a[k] for k in ("reviewer", "reason", "exit_code", "stderr_tail", "model")}
                    for a in chain["attempts"]]
        verdict = (chain["parsed"] or {}).get("word")
        try:
            append_attempts(reviews / "attempts.jsonl",
                            [{"ts": ts, "repo": job.key, "pr": job.pr, "round": number,
                              "reviewer": a["reviewer"], "reason": a["reason"], "exit_code": a["exit_code"]}
                             for a in attempts])
            write_out(path.with_suffix(".out"), _out_text(chain))
            if (live.head, live.base, standing_on) != (seen.head, seen.base, seen.head):
                # the PR moved, or the checkout did: either way the head named is not the head read
                status, exit_code = "head-moved", EXIT_MOVED
            elif verdict is None:
                status, exit_code = "no-verdict", EXIT_NO_VERDICT
            elif _post(job, comment_body(number, job.author, seen.head, verdict)):
                status, exit_code = "posted", EXIT_FOR_VERDICT[verdict]
            else:
                status, exit_code = "post-failed", EXIT_INFRA
            replace_record(path, {
                "repo": job.key, "pr": job.pr, "round": number, "head_sha": seen.head, "base": seen.base,
                "reviewer": chain["reviewer"], "model": None, "kind": "codex", "verdict": verdict,
                "status": status, "author": job.author, "ts": ts, "attempts": attempts})
        except OSError as exc:
            _say("round %d is left empty: %s" % (number, exc))
            return ReviewResult(EXIT_INFRA, number, None, verdict, path)
        return ReviewResult(exit_code, number, status, verdict, path)
    finally:
        os.close(lock)


def review(repo: str, pr: int, checkout: str, author: str, *,
           codex_timeout: int = policy.REVIEW_CODEX_TIMEOUT,
           io_timeout: int = policy.REVIEW_IO_TIMEOUT) -> ReviewResult:
    key = repo_key(repo)
    check_name(author, "author")
    if type(pr) is not int or pr < 1:
        raise ValueError("pr must be a positive integer: %r" % (pr,))
    if not os.path.isdir(checkout):
        raise ValueError("checkout is not a directory: %r" % (checkout,))
    job = _Job(repo, key, pr, checkout, author, io_timeout)
    seen = _prepare(job)
    if isinstance(seen, ReviewResult):
        return seen
    try:
        chain = _ask_codex(checkout, seen.head, seen.base, codex_timeout)
    except _Infra as exc:
        return _failed(str(exc))
    return _keep_and_post(job, seen, chain)


def _pr_number(text: str) -> int:
    if not re.fullmatch(r"[0-9]+", text) or int(text) < 1:      # not int(): it takes Arabic-Indic digits too
        raise argparse.ArgumentTypeError("must be a positive integer: %r" % text)
    return int(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="boss_review.py",
        description="Review one PR head with Codex and post the verdict. Exit 0: GO posted. 2: usage, "
                    "wrong PR or wrong checkout. 3: NO-GO posted. 4: Codex gave no verdict. 6: the head "
                    "or base moved. 7: infrastructure failure.")
    ap.add_argument("--repo", required=True, metavar="OWNER/REPO", help="never inferred from the directory")
    ap.add_argument("--pr", required=True, type=_pr_number, metavar="N")
    ap.add_argument("--checkout", required=True, metavar="DIR", help="a checkout standing on the PR head")
    ap.add_argument("--author", required=True, metavar="NAME",
                    help="who runs the review, as the comment says")
    args = ap.parse_args(argv)
    try:
        result = review(args.repo, args.pr, args.checkout, args.author)
    except ValueError as exc:
        print("boss_review: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    if result.round is not None:
        print("Codex review %d: %s (%s) %s" % (result.round, result.verdict or "no verdict",
                                               result.status or "round left empty", result.record))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
