#!/usr/bin/env python3
"""Have Codex review again every PR on the list of provisional GOs (ticket 10a).

    recheck(track, repo, checkout, author="recheck") -> list[str]      the pass: the lines it printed
    boss_recheck.py --track T --repo OWNER/REPO --checkout DIR [--author NAME]   the command

A fallback review is only a loan (ticket 06): its PR stays under `## Provisional GO` in the track's tracker
until Codex has since said GO. Once Codex answers again this walks the entries of `--repo`, one at a time, and
reviews each with Codex alone (`review(..., allow_fallback=False)`: a recheck never falls back to Claude), in a
detached worktree of its own outside `--checkout`, at the head `gh` reads now:

    an open PR       its live head;           a merged PR      its merged `headRefOid`, whatever the entry's `head=`
                                              says (`refs/pull/<N>/head` stays after the branch is gone);
    a PR closed without a merge is not reviewed (06b keeps its entry).

Lines printed, for the boss to act on:

    NO-GO <repo>#<N> round <NN> author=<name>      a Codex NO-GO on an open PR: the entry stays, dispatch its author
    DISPATCH <repo>#<N> author=<name> round=<NN>   a Codex NO-GO on a merged PR: the blocker is written, the entry gone

`<name>` is the author of the entry's own round, the worker who got the provisional GO. A Codex NO-GO on a merged
PR is the one case where a NO-GO removes an entry: an open blocker on the ladder is written first (the ladder
raises it with no boss turn, whether or not an author session exists), then the entry is removed. A crash between
the two is resumed, not reviewed again. One pass per repo runs at a time (a lock under the reviews directory); a
second one says so and does nothing. Any other outcome (no Codex answer, a fetch or a `gh pr view` that fails)
leaves the entry and the pass goes on to the next one; `prune_provisional` runs at the start and after each review,
so a Codex GO takes its entry off.

Exit codes: 0 the pass ran; 2 usage, or a track whose tracker is not a regular file of yours (stderr says "no
blocker can be rechecked"); 7 the tracker could not be read. Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import boss_review as br
import boss_store
import codex_blocker
import policy
import tracker

WORKTREE_PREFIX = "boss-recheck-"
DEFAULT_AUTHOR = "recheck"
LOCK_WAIT = 20.0
EXIT_OK, EXIT_USAGE, EXIT_INFRA = 0, 2, 7


class Unusable(Exception):
    """The track's tracker is not a regular file of the user's: no blocker can be written to it."""


class _Skip(Exception):
    """This entry cannot be reviewed now; it stays, and the pass goes on."""


def _say(message: str) -> None:
    print("boss_recheck: " + message, file=sys.stderr)


def blocker_id(repo: str, pr: int, round: int) -> str:
    """`fx` and 8 hex digits of the sha1 of "<repo>#<N> round <NN>": one id per round of one PR, so that a second
    NO-GO on the same PR is a new blocker, and a retry of the same round finds its own."""
    return "fx" + hashlib.sha1(("%s#%d round %02d" % (repo, pr, round)).encode()).hexdigest()[:8]


# ----------------------------------------------------------------- the worktree ----
def _git(checkout: str, *args: str, timeout: float):
    return br._spawn(["git", "-C", checkout, *args], timeout)


def _remove_worktree(checkout: str, path: Path, timeout: float) -> None:
    run = _git(checkout, "worktree", "remove", "--force", str(path), timeout=timeout)
    if run.code != 0:
        _say("git worktree remove %s failed: %s" % (path, run.err.strip()[-200:]))
    shutil.rmtree(path, ignore_errors=True)


def _prune_leftovers(checkout: str, timeout: float) -> None:
    """Remove the temporary worktrees an earlier pass left (it died before it could), and git's records of
    worktrees whose directory is gone. A worktree is the recheck's own by its name and its place."""
    run = _git(checkout, "worktree", "list", "--porcelain", timeout=timeout)
    if run.code == 0:
        tmp = Path(tempfile.gettempdir()).resolve()
        for line in run.out.decode("utf-8", "replace").splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree "):])
                if path.name.startswith(WORKTREE_PREFIX) and path.parent.resolve() == tmp:
                    _remove_worktree(checkout, path, timeout)
    _git(checkout, "worktree", "prune", timeout=timeout)


@contextlib.contextmanager
def _worktree(checkout: str, pr: int, sha: str, timeout: float):
    """A detached worktree at `sha` (the head of `refs/pull/<pr>/head`, which GitHub keeps for open, merged and
    closed PRs), outside `checkout`; `checkout` itself is never moved. `_Skip` when the fetch or the worktree fails
    or does not give `sha`. It is removed afterwards, whatever the review did."""
    fetch = _git(checkout, "fetch", "--no-tags", "origin", "refs/pull/%d/head" % pr, timeout=timeout)
    if fetch.code != 0:
        raise _Skip("git fetch of refs/pull/%d/head failed: %s" % (pr, fetch.err.strip()[-200:] or "timed out"))
    got = _git(checkout, "rev-parse", "--verify", "FETCH_HEAD^{commit}", timeout=timeout)
    if got.code != 0 or got.out.decode("ascii", "replace").strip() != sha:
        raise _Skip("refs/pull/%d/head is not %s" % (pr, sha))
    path = Path(tempfile.mkdtemp(prefix=WORKTREE_PREFIX))
    try:
        add = _git(checkout, "worktree", "add", "--detach", str(path), sha, timeout=timeout)
        if add.code != 0:
            raise _Skip("git worktree add failed: %s" % (add.err.strip()[-200:] or "timed out"))
        head = _git(str(path), "rev-parse", "HEAD", timeout=timeout)
        if head.code != 0 or head.out.decode("ascii", "replace").strip() != sha:
            raise _Skip("the worktree is not at %s" % sha)
        yield str(path)
    finally:
        _remove_worktree(checkout, path, timeout)


# ------------------------------------------------------------------- the rounds ----
def _round_files(pr_dir: Path):
    try:
        names = sorted((int(m.group(1)), f) for f in pr_dir.iterdir() if (m := re.fullmatch(r"round(\d+)\.json", f.name)))
    except OSError:
        return []
    return names


def _record(file: Path) -> dict | None:
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _author_of(pr_dir: Path, entry: br.ProvEntry) -> str:
    """The author of the entry's own round (who got the provisional GO), else "unknown"."""
    data = _record(pr_dir / ("round%02d.json" % entry.round)) or {}
    author = data.get("author")
    return author if isinstance(author, str) and br.NAME.fullmatch(author) else "unknown"


def _unfinished_no_go(pr_dir: Path, entry: br.ProvEntry, head: str) -> int | None:
    """The number of the highest `kind: codex` round on `head` with status posted or post-failed above the entry's
    round, when it is a NO-GO: a recheck that died after that round and before the entry was removed. A record
    that cannot be read is not counted."""
    found = None
    for number, file in _round_files(pr_dir):
        data = _record(file)
        if (number > entry.round and data and data.get("kind") == "codex" and data.get("head_sha") == head
                and data.get("status") in ("posted", "post-failed") and data.get("round") == number):
            found = (number, data.get("verdict"))
    return found[0] if found and found[1] == "NO-GO" else None


# --------------------------------------------------------------------- the tracker ----
def _read(path: Path) -> str:
    with open(path, newline="", encoding="utf-8") as fh:
        return fh.read()


def _add_blocker(path: Path, track: str, entry: br.ProvEntry, number: int, author: str) -> bool:
    """The open blocker for the NO-GO of round `number`, once. True when it is there (written now, or found: any
    occurrence of the round's exact id, a cleared line included, counts, so a retry after a clear adds nothing and
    alerts nobody); False when the write failed. `boss-alert 0` goes out once, only when this call wrote the line."""
    id_ = blocker_id(entry.repo, entry.pr, number)
    try:
        text = _read(path)
    except (OSError, UnicodeDecodeError) as exc:
        _say("%s cannot be read: %s" % (path, exc))
        return False
    if re.search(r"(?<![A-Za-z0-9])id=%s(?![A-Za-z0-9])" % re.escape(id_), text):
        return True
    out = "pm/reviews/%s/pr%d/round%02d.out" % (entry.repo, entry.pr, number)
    what = "Codex NO-GO on merged %s#%d (round %02d)" % (entry.repo, entry.pr, number)
    ask = "%s: dispatch %s, or any free worker, with %s as the brief" % (what, author, out)
    t0 = datetime.now().astimezone()
    marker = tracker.render_marker(id_, t0, t0 + timedelta(minutes=policy.RUNGS[0]), ask=ask)
    line = "- %s - T+0 %s %s" % (what, t0.isoformat(timespec="minutes"), marker)
    got = tracker.add_line(path, tracker.BLOCKERS, line, tracker.marker_tag(id_), time.monotonic() + LOCK_WAIT)
    if got.startswith("failed"):
        _say("the blocker for %s#%d round %02d was not written (%s): the entry stays" % (entry.repo, entry.pr, number, got))
        return False
    if got == "done":
        codex_blocker._post(codex_blocker.default_alert(), "0", "%s: %s. %s" % (track, what, ask))
    return True


def _remove_entry(path: Path, entry: br.ProvEntry) -> bool:
    """Remove the line `entry` was read from, and only that: a line of the same PR that replaced it meanwhile
    (a newer provisional GO) is a different entry and stays. True when no such line is left."""
    def fn(text: str) -> str | None:
        lines = text.split("\n")
        found = br._section(lines)
        if found is None:
            return None
        drop = [i for i in range(*found) if br._entry_of(lines[i]) == entry]
        for i in reversed(drop):
            del lines[i]
        return "\n".join(lines) if drop else None

    got = tracker.update(path, fn, time.monotonic() + LOCK_WAIT)
    if got.startswith("failed"):
        _say("the entry of %s#%d was not removed (%s)" % (entry.repo, entry.pr, got))
        return False
    return True


def _handle_merged_no_go(path: Path, track: str, entry: br.ProvEntry, number: int, pr_dir: Path) -> list[str]:
    """The blocker first, then the entry's removal; the DISPATCH line once both are done."""
    author = _author_of(pr_dir, entry)
    if not _add_blocker(path, track, entry, number, author) or not _remove_entry(path, entry):
        return []
    return ["DISPATCH %s#%d author=%s round=%02d" % (entry.repo, entry.pr, author, number)]


# ----------------------------------------------------------------------- the pass ----
def _one(path: Path, track: str, entry: br.ProvEntry, checkout: str, author: str,
         codex_timeout: int, io_timeout: int) -> list[str]:
    live = br._live_state(entry, io_timeout)
    if live is None:
        raise _Skip("gh pr view of %s#%d failed or gave no state I can read" % (entry.repo, entry.pr))
    state, sha = live
    if state not in ("OPEN", "MERGED"):         # CLOSED without a merge: not reviewed, the entry stays (06b rule 3)
        return []
    pr_dir = br._reviews_dir() / entry.repo / ("pr%d" % entry.pr)
    if state == "MERGED":
        resumed = _unfinished_no_go(pr_dir, entry, sha)
        if resumed is not None:
            return _handle_merged_no_go(path, track, entry, resumed, pr_dir)
    with _worktree(checkout, entry.pr, sha, io_timeout) as wt:
        result = br.review(entry.repo, entry.pr, wt, author, codex_timeout=codex_timeout, io_timeout=io_timeout,
                           allow_fallback=False, track=track)
    if result.verdict != "NO-GO" or result.status not in ("posted", "post-failed") or result.round is None:
        return []
    if state == "MERGED":
        return _handle_merged_no_go(path, track, entry, result.round, pr_dir)
    return ["NO-GO %s#%d round %02d author=%s" % (entry.repo, entry.pr, result.round, _author_of(pr_dir, entry))]


@contextlib.contextmanager
def _pass_lock(key: str):
    """One pass per repo at a time, for every track: a second pass would remove the first one's worktree as a
    leftover. Yields False at once when the lock is held (the kernel lets it go if its holder dies)."""
    reviews = br._reviews_dir()
    reviews.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(reviews / (".recheck-%s.lock" % key.replace("/", "-")), "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def _prune(track: str, repo: str, io_timeout: int) -> None:
    try:
        br.prune_provisional(track, repo, io_timeout)
    except Exception as exc:        # a prune that fails leaves entries: the next pass, or --list, still sees them
        _say("the prune failed: %s: %s" % (type(exc).__name__, exc))


def recheck(track: str, repo: str, checkout: str, author: str = DEFAULT_AUTHOR, *,
            codex_timeout: int = policy.REVIEW_CODEX_TIMEOUT, io_timeout: int = policy.REVIEW_IO_TIMEOUT) -> list[str]:
    """One pass over the entries of `repo` in `track`'s list. Returns the lines to print. ValueError for an
    argument that is not usable, `Unusable` for a track that has no tracker file of the user's, OSError and
    UnicodeDecodeError for a tracker that cannot be read."""
    key = br.repo_key(repo)
    br.check_name(author, "author")
    if not Path(checkout).is_dir():
        raise ValueError("checkout is not a directory: %r" % (checkout,))
    path = codex_blocker.usable_tracker(track, "rechecked")
    if path is None:
        raise Unusable(track)
    with _pass_lock(key) as held:
        if not held:
            _say("another recheck of %s is running: nothing done (its worktree must not be pruned as a leftover)" % key)
            return []
        _prune_leftovers(checkout, io_timeout)
        _prune(track, key, io_timeout)
        entries = [e for e in br.provisional_entries(_read(path)) if e.repo == key]
        lines: list[str] = []
        for entry in entries:
            try:
                lines += _one(path, track, entry, checkout, author, codex_timeout, io_timeout)
            except _Skip as exc:
                _say("%s#%d stays on the list: %s" % (entry.repo, entry.pr, exc))
            except Exception as exc:        # no entry can stop or erase another
                _say("%s#%d stays on the list: %s: %s" % (entry.repo, entry.pr, type(exc).__name__, exc))
            _prune(track, key, io_timeout)
        return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="boss_recheck.py", description=__doc__.splitlines()[0])
    ap.add_argument("--track", required=True, metavar="T")
    ap.add_argument("--repo", required=True, metavar="OWNER/REPO")
    ap.add_argument("--checkout", required=True, metavar="DIR", help="the repo's shared checkout; never moved")
    ap.add_argument("--author", default=DEFAULT_AUTHOR, metavar="NAME", help="who runs the reviews (default recheck)")
    args = ap.parse_args(argv)
    if not boss_store.valid_track(args.track):
        _say("track must match %s and hold no '..': %r" % (boss_store.TRACK_RE.pattern, args.track))
        return EXIT_USAGE
    try:
        lines = recheck(args.track, args.repo, args.checkout, args.author)
    except Unusable:
        return EXIT_USAGE            # usable_tracker has said why
    except (OSError, UnicodeDecodeError) as exc:      # before ValueError, which UnicodeDecodeError is one of
        _say("the tracker cannot be read: %s" % exc)
        return EXIT_INFRA
    except ValueError as exc:
        _say(str(exc))
        return EXIT_USAGE
    for line in lines:
        print(line)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
