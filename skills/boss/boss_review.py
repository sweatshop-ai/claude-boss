#!/usr/bin/env python3
"""Review one PR head with Codex, keep the round on disk, post a minimal comment.

    review(repo, pr, checkout, author) -> ReviewResult      the logic
    boss_review.py --repo OWNER/REPO --pr N --checkout DIR --author NAME   the command
    fallback_spec(timeout=...) -> Fallback       the read-only fallback reviewer (review() does not run it yet)
    boss_review.py --check-fallback --checkout DIR   run that fallback once and check what it was left with

Exit codes (5 belongs to a later ticket and is never used here):

    0 GO posted        3 NO-GO posted       4 Codex gave no verdict (absent, timeout, error, noverdict)
    2 usage, the PR is not the one asked for, or the checkout is not on its head
    6 the PR's head or base (or the checkout's head) moved during the review: nothing posted
    7 infrastructure: gh, the chain or a write failed

--check-fallback uses 0 (the call is confined as specified) and 1 (it is not, or could not be shown to
be), and 2 for usage; it posts nothing and reads no PR.

The order: read the PR, ask Codex (01's chain, Codex only, in a child process started in the
checkout), then under the PR's lock read the PR again, claim the next round, append the attempts,
write the answer, post, and replace the claimed file by the full record. A failure before the
claim leaves nothing; one after it leaves the claimed file empty. Rounds live under
$CLAUDE_CONFIG_DIR/pm/reviews/<owner>/<repo>/pr<N>/ (round<NN>.json and .out), never in the
checkout; the record, not the comment, is what a gate reads. Standard library only.
"""
from __future__ import annotations

import argparse
import dataclasses
import fcntl
import json
import os
import re
import select
import signal
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
from reviewer_chain import (CODEX_FAILURES, GO_NOGO, STDERR_TAIL, TERM_GRACE, Fallback, _parse, _snapshot,
                            _stop, claude_argv)

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


class _Seen(NamedTuple):
    """A process as it was when seen: a pid alone is not one, since a pid is reused once its
    process is gone. `start` is when it started (field 22 of /proc/<pid>/stat, in ticks since boot)."""
    pid: int
    start: str


def _stat_fields(pid: int) -> list[str] | None:
    """The fields of /proc/<pid>/stat after the command name (state first, so field n is [n - 3]);
    None when the process is gone or there is no /proc. Read as bytes: the name may be any bytes,
    and a ")" may be in it, so the fields start after the last one."""
    try:
        raw = Path("/proc/%d/stat" % pid).read_bytes()
    except OSError:
        return None
    _, found, tail = raw.rpartition(b")")
    return tail.decode("ascii", "replace").split() if found else None


def _start_time(pid: int) -> str | None:
    fields = _stat_fields(pid)
    return fields[19] if fields and len(fields) > 19 else None


def _proc_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, start time) of every process, read from /proc ({} where there is none)."""
    try:
        entries = os.listdir("/proc")
    except OSError:
        return {}
    table = {}
    for entry in entries:
        fields = _stat_fields(int(entry)) if entry.isascii() and entry.isdigit() else None
        if fields and len(fields) > 19 and fields[1].isdigit():
            table[int(entry)] = (int(fields[1]), fields[19])
    return table


def _tree_below(table: dict[int, tuple[int, str]], pid: int) -> list[_Seen]:
    """Every process of `table` that descends from `pid`, found with one pass over the table."""
    children: dict[int, list[int]] = {}
    for child, (parent, _) in table.items():
        children.setdefault(parent, []).append(child)
    found, visited, frontier = [], {pid}, [pid]
    while frontier:
        frontier = [c for p in frontier for c in children.get(p, ()) if c not in visited]
        visited.update(frontier)
        found += [_Seen(c, table[c][1]) for c in frontier]
    return found


def _below(pid: int) -> list[_Seen]:
    """Every process below `pid`: the reviewer the chain started lives in a session of its own, so
    the chain's process group does not reach it. Empty where there is no /proc. A process started
    after this read is not in it."""
    return _tree_below(_proc_table(), pid)


def _hold(seen: _Seen) -> int | None:
    """A pidfd for `seen`, only if that process is still the one that was seen. A pidfd names the
    process, not the number, so what is signalled through it cannot be a later holder of the pid;
    the start time read after it was opened says it was the right process when it was."""
    try:
        fd = os.pidfd_open(seen.pid)
    except (AttributeError, OSError):          # no pidfd here, or the process is gone
        return None
    kept = False
    try:
        kept = _start_time(seen.pid) == seen.start
    finally:
        if not kept:
            os.close(fd)
    return fd if kept else None


def _stop_below(seen: list[_Seen]) -> None:
    """TERM, then KILL, each of `seen` that is still the process that was seen."""
    opened: list[int] = []
    try:
        for one in seen:
            fd = _hold(one)
            if fd is not None:
                opened.append(fd)
        held = list(opened)                 # those not yet seen to exit
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for fd in held:
                try:
                    signal.pidfd_send_signal(fd, sig)
                except (ProcessLookupError, PermissionError):     # gone, or not ours to signal
                    pass
            poller = select.poll()
            for fd in held:
                poller.register(fd, select.POLLIN)       # readable once the process has exited
            deadline = time.monotonic() + TERM_GRACE
            while held and (left := deadline - time.monotonic()) > 0:
                gone = {fd for fd, _ in poller.poll(left * 1000)}
                held = [fd for fd in held if fd not in gone]
                for fd in gone:
                    poller.unregister(fd)
    finally:
        for fd in opened:
            os.close(fd)


def _spawn(argv: list[str], timeout: float, cwd: str | None = None) -> _Out:
    """Run one program with a closed stdin, its output in temporary files, and stop it and
    everything it started, in whatever session, when it outlasts `timeout`. A program that cannot
    be started, or whose output cannot be kept, has no exit code: the caller sees `code` None."""
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            return _run_into(argv, timeout, cwd, out, err)
    except OSError as exc:
        return _Out(None, b"", str(exc), False)


def _run_into(argv: list[str], timeout: float, cwd: str | None, out, err) -> _Out:
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                start_new_session=True)
    except OSError as exc:
        return _Out(None, b"", str(exc), False)
    try:
        code, timed_out = proc.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        below = _below(proc.pid)             # before the stop: afterwards they belong to init
        _stop(proc)
        _stop_below(below)
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
    path: str        # the url's path, lowercased
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
    try:
        path = urllib.parse.urlparse(url).path.lower()
    except ValueError as exc:
        raise _Infra("gh pr view gave a url that does not parse: %s" % exc)
    return _Pr(number, url, path, head, base)


def _is_the_pr(seen: _Pr, job: _Job) -> bool:
    """The PR gh answered with is the one asked for: its number, and a URL path of
    /<owner>/<repo>/pull/<N> (the names compared without case)."""
    return seen.number == job.pr and seen.path == "/%s/pull/%d" % (job.key, job.pr)


class _Checkout(NamedTuple):
    head: str
    root: str        # the top of the worktree: the checkout may be a directory inside it


def _checkout_of(job: _Job) -> _Checkout | None:
    """The commit the checkout stands on and the worktree it is in, or None when it is not a git
    checkout. A git that cannot be run or outlasts the wait is _Infra: that says nothing about
    which commit it stands on."""
    run = _spawn(["git", "-C", job.checkout, "rev-parse", "HEAD", "--show-toplevel"], job.io_timeout)
    if run.timed_out or run.code is None:
        raise _Infra("git rev-parse %s" % ("ran past %ss" % job.io_timeout if run.timed_out
                                           else "could not be run: %s" % run.err.strip()[-300:]))
    # HEAD is the first line. The rest is the path and the newline git ends it with: a path may hold
    # a newline or bytes that are not text, so it is cut at that one newline and decoded as the
    # filesystem does, never split into lines or decoded with replacement.
    head, _, rest = run.out.partition(b"\n")
    root = rest[:-1] if rest.endswith(b"\n") else rest
    if run.code != 0 or not root or not _SHA.fullmatch(head.decode("ascii", "replace")):
        return None
    return _Checkout(head.decode("ascii"), os.fsdecode(root))


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


def _sound(data: dict, code: int) -> bool:
    """Whether the chain's result is plainly a Codex-only one and agrees with its own exit code:
    one Codex attempt, answered exactly when the result names Codex, with a verdict, and exit 0.
    A malformed value raises KeyError or TypeError; the caller counts that as unsound."""
    reviewer, output, parsed, attempts = (data[k] for k in ("reviewer", "output", "parsed", "attempts"))
    if not (isinstance(attempts, list) and len(attempts) == 1 and isinstance(attempts[0], dict)
            and all(k in attempts[0] for k in _ATTEMPT_KEYS)):
        return False
    a = attempts[0]
    answered = reviewer == "codex"
    word = None if parsed is None else parsed["word"]
    return (reviewer in ("codex", "none")
            and a["reviewer"] == "codex" and a["model"] is None
            and isinstance(a["output"], str) and isinstance(a["stderr_tail"], str)
            and (a["exit_code"] is None or type(a["exit_code"]) is int)
            and (a["reason"] == "answered") == answered
            and (answered or a["reason"] in CODEX_FAILURES)
            and (word in EXIT_FOR_VERDICT) == answered
            and (code == 0) == answered
            and output == (a["output"] if answered else "")
            and (not answered or _follows(word, a["output"])))


def _follows(word: str, output: str) -> bool:
    """Whether the answer carries `word` as its verdict, read as the chain read it (01's parser,
    strict, whole words). The chain parsed the bytes with their NULs removed and keeps the answer
    as it was written, so with a NUL in it the answer alone cannot say what the chain read: such an
    answer is refused (exit 7), whatever verdict is reported for it."""
    if "\0" in output:
        return False
    found = _parse(output, GO_NOGO, strict=True)
    return found is not None and found.word == word


def _chain_result(run: _Out) -> dict:
    """The chain's JSON, once it is plainly a Codex-only result; else _Infra. A child that
    crashed, was killed or printed something else says nothing about Codex, so it is no outage."""
    if run.timed_out:
        raise _Infra("the chain ran past its time and was stopped")
    if run.code not in (0, 1):
        raise _Infra("the chain exited %s: %s" % (run.code, run.err.strip()[-300:]))
    try:
        data = json.loads(run.out.decode("utf-8"))
        sound = _sound(data, run.code)
    except (ValueError, KeyError, TypeError) as exc:
        raise _Infra("the chain printed no result I can read: %s: %s" % (type(exc).__name__, exc))
    if not sound:
        raise _Infra("the chain printed a result that is not a consistent Codex-only one")
    return data


def _ask_codex(checkout: str, head: str, base: str, codex_timeout: int) -> dict:
    """01's chain in a child process whose working directory is the checkout, so every reviewer
    it starts inherits that directory (`run_chain` has no parameter for one)."""
    try:
        with tempfile.TemporaryDirectory(prefix="boss-review-") as tmp:
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text(build_brief(head, base), encoding="utf-8")
            run = _spawn([sys.executable, str(CHAIN), "--prompt-file", str(prompt), "--words", "GO,NO-GO",
                          "--match", "token", "--strict", "--no-fallback", "--effort", REVIEW_EFFORT,
                          "--codex-timeout", str(codex_timeout)],
                         codex_timeout + policy.REVIEW_CHAIN_SLACK, cwd=checkout)
    except OSError as exc:
        raise _Infra("the brief for the chain could not be written: %s" % exc)
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
        checkout = _checkout_of(job)
        if checkout is None or checkout.head != seen.head:
            return _refused("the HEAD of %s is not the head of the PR, %s" % (job.checkout, seen.head))
    except _Infra as exc:
        return _failed(str(exc))
    if Path(os.path.realpath(_reviews_dir())).is_relative_to(os.path.realpath(checkout.root)):
        return _failed("the reviews directory %s is inside the worktree of the checkout, %s"
                       % (_reviews_dir(), checkout.root))
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
            checkout = _checkout_of(job)
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
            if (live.head, live.base, checkout and checkout.head) != (seen.head, seen.base, seen.head):
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


# ------------------------------------------------------------ the fallback, confined ----
EXIT_CHECK_FAILED = 1       # --check-fallback only: the call is not shown to be confined
CHECK_PROMPT = "ok"         # one word: the check reads the init event, not the answer
CHECK_FLAGS = ("--output-format", "stream-json", "--verbose")   # `claude -p` refuses stream-json without --verbose
_MISSING = object()


def fallback_spec(timeout: int = policy.REVIEW_FALLBACK_TIMEOUT) -> Fallback:
    """The PR gate's fallback reviewer: `claude` on the policy's model, limited to the built-in tools
    Read, Grep and Glob, with every MCP server and every slash command off, and any permission it was
    not given denied rather than asked for. `--tools` alone leaves the MCP tools in (checked with
    `claude` 2.1.288 and 2.1.289), hence `--strict-mcp-config`. It runs when Codex is absent, hangs or
    fails, and not after a Codex answer that has no verdict. Not yet run by review(): ticket 08 does that."""
    return Fallback("opus", policy.REVIEW_FALLBACK_MODEL, timeout=timeout,
                    when=("absent", "timeout", "error"),
                    extra_args=("--tools", ",".join(policy.REVIEW_FALLBACK_TOOLS),
                                "--strict-mcp-config", "--disable-slash-commands",
                                "--permission-mode", policy.REVIEW_FALLBACK_PERMISSION_MODE))


def _shown(value) -> str:
    return "absent" if value is _MISSING else json.dumps(value)[:200]


def init_problems(events: list[dict]) -> list[str]:
    """Why the events of a fallback run do not show it confined; [] when they do. Fail-closed: exactly
    one init event; its `tools` exactly Glob, Grep and Read (a list of strings, each once, in any
    order); its `mcp_servers` present and an empty list; its `model` the policy's model id, whole."""
    inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    if len(inits) != 1:
        return ["expected exactly one init event, found %d" % len(inits)]
    init, problems = inits[0], []
    tools = init.get("tools", _MISSING)
    wanted = sorted(policy.REVIEW_FALLBACK_TOOLS)
    if not (isinstance(tools, list) and all(isinstance(t, str) for t in tools)):
        problems.append("the init event's tools are not a list of strings: %s" % _shown(tools))
    elif sorted(tools) != wanted:
        problems.append("the init event lists the tools %s, not exactly %s" % (sorted(tools), wanted))
    servers = init.get("mcp_servers", _MISSING)
    if servers != []:
        problems.append("the init event's mcp_servers is %s, not an empty list" % _shown(servers))
    model = init.get("model", _MISSING)
    if not isinstance(model, str) or model != policy.REVIEW_FALLBACK_MODEL:
        problems.append("the init event's model is %s, not %r" % (_shown(model), policy.REVIEW_FALLBACK_MODEL))
    return problems


def _events(out: bytes) -> tuple[list[dict], list[str]]:
    """The events of newline-delimited JSON output, and a problem for each non-blank line that is
    not a JSON object."""
    events, problems = [], []
    for n, line in enumerate(out.decode("utf-8", "replace").split("\n"), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            event = None
        if isinstance(event, dict):
            events.append(event)
        else:
            problems.append("line %d of claude's output is not a JSON object" % n)
    return events, problems


def check_fallback(checkout: str, timeout: int = policy.REVIEW_FALLBACK_TIMEOUT) -> list[str]:
    """Run the fallback call once, from `checkout`, with a one-word prompt in stream-JSON mode, and
    say why what it printed does not show it confined; [] means it does. The argv is the one a
    review sends (`claude_argv` of `fallback_spec`) plus CHECK_FLAGS, so the two cannot drift. A run
    that is stopped, cannot be started or exits non-zero is not a pass, whatever it printed first."""
    spec = fallback_spec(timeout)
    probe = dataclasses.replace(spec, extra_args=spec.extra_args + CHECK_FLAGS)
    run = _spawn(claude_argv(probe, CHECK_PROMPT), timeout, cwd=checkout)
    if run.timed_out:
        return ["claude ran past %ss and was stopped" % timeout]
    if run.code is None:
        return ["claude could not be started: %s" % run.err.strip()[-300:]]
    events, problems = _events(run.out)
    problems += init_problems(events)
    if run.code != 0:
        problems.append("claude exited %s: %s" % (run.code, run.err.strip()[-300:]))
    return problems


def _check_main(checkout: str) -> int:
    problems = check_fallback(checkout)
    for problem in problems:
        _say("check-fallback: " + problem)
    if problems:
        return EXIT_CHECK_FAILED
    print("fallback confined: tools %s; no MCP servers; model %s"
          % (", ".join(sorted(policy.REVIEW_FALLBACK_TOOLS)), policy.REVIEW_FALLBACK_MODEL))
    return 0


def _pr_number(text: str) -> int:
    if not re.fullmatch(r"[0-9]+", text) or int(text) < 1:      # not int(): it takes Arabic-Indic digits too
        raise argparse.ArgumentTypeError("must be a positive integer: %r" % text)
    return int(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="boss_review.py",
        description="Review one PR head with Codex and post the verdict. Exit 0: GO posted. 2: usage, "
                    "wrong PR or wrong checkout. 3: NO-GO posted. 4: Codex gave no verdict. 6: the head "
                    "or base moved. 7: infrastructure failure. With --check-fallback: 0 the fallback "
                    "call is confined, 1 it is not, 2 usage.")
    ap.add_argument("--repo", metavar="OWNER/REPO", help="never inferred from the directory")
    ap.add_argument("--pr", type=_pr_number, metavar="N")
    ap.add_argument("--checkout", metavar="DIR",
                    help="a checkout standing on the PR head (with --check-fallback: where the fallback runs)")
    ap.add_argument("--author", metavar="NAME", help="who runs the review, as the comment says")
    ap.add_argument("--check-fallback", action="store_true",
                    help="instead of a review: run the read-only fallback once, in --checkout, and check "
                         "its init event (one real, one-word call; takes no --repo, --pr or --author)")
    args = ap.parse_args(argv)
    given = {"--repo": args.repo, "--pr": args.pr, "--checkout": args.checkout, "--author": args.author}
    if args.check_fallback:
        refused = [flag for flag in ("--repo", "--pr", "--author") if given[flag] is not None]
        if refused:
            ap.error("--check-fallback does not take %s" % ", ".join(refused))
        if args.checkout is None:
            ap.error("--check-fallback needs --checkout")
        if not os.path.isdir(args.checkout):
            ap.error("checkout is not a directory: %r" % (args.checkout,))
        return _check_main(args.checkout)
    missing = [flag for flag, value in given.items() if value is None]
    if missing:
        ap.error("the following arguments are required: %s" % ", ".join(missing))
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
