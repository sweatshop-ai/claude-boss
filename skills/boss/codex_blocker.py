#!/usr/bin/env python3
"""The "Codex down" blocker: raised when codex_health says down, cleared when it says up.

    sync(track, now=None)    one locked step on pm/<track>.md, then at most one boss-alert
    choice(track)            (status, id, choice): what the owner chose for the open blocker
    choose(track, value)     write that choice under Decisions in force, under the tracker lock

boss_review.review(..., track=T) calls it once after a review's attempts are logged. The state is
codex_health's, read inside the tracker's lock, so raise and clear act on the file as it is when the lock
is taken. The ladder (routines/boss_ladder_core.py) escalates the raised line from rung 5 on; this module
posts rung 0 itself, and `clear` when it clears.

Raise: state down, `failures >= policy.CODEX_DOWN_AFTER` (after F,F,F,ok the state stays down with 0
failures and stale last_* fields, which raise nothing) and no open `cd` blocker. Clear: state up and an open
`cd` blocker. "Open" is a line inside the Open blockers section whose marker id is `cd` and twelve digits
and has no cleared=; a line that holds such an id but whose marker is unreadable or refused by validate is
open too (never a second blocker beside it) unless its text holds ` cleared=`. `clear` is posted only when
the write was `done` and no open or broken `cd` line is left.

A blocker the owner closed by hand holds: with no open `cd` line, a raise also needs `last_ts` (the newest
failure's `ts`) to be absent or at or after the minute start of the newest `cleared=` on a readable `cd` line
in the section, so a `noverdict`, or a run that logged nothing, does not bring it back. This is an
approximation: attempts.jsonl is ordered by file position, not by `ts`, so a writer that appended a failure
whose `ts` was taken before the clear can be read as old, and that failure does not raise. A `cleared=`
more than CLEAR_SLACK seconds after `now` (a local time read as UTC, a mistyped month) is ignored as
invalid, said on stderr, and holds nothing. Deleting the line from the tracker leaves nothing to compare.

The owner's choice (ticket 09b) is the line `- [codex-choice <blocker id>] <choice> - <ts>` in `## Decisions in
force`, never under Open blockers (where `tracker.open_blockers` would count it as a blocker for good).
The last matching line for the open blocker's id wins, so a later `--choose` revokes an earlier one; a line for
a cleared blocker's id means nothing to a new one. The line is workflow evidence, not proof of who wrote it: any
process of the same user can edit the tracker. What makes a choice the owner's is the question that produced it
(SKILL.md).

    codex_blocker.py TRACK                    sync (as boss_review does after a review)
    codex_blocker.py --choose TRACK CHOICE    exit 0 written or already so; 2 with a reason: no or more than one
                                              open blocker, a choice not offered, a bad TRACK; 1 lock or write failed
    codex_blocker.py --choice TRACK           prints no-blocker (exit 2), none (1), malformed (2, reason on stderr)
                                              or the recorded choice (0)

Failures (a missing tracker, a failed update, a failed alert) go to stderr and raise nothing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import stat as stat_

import boss_store
import codex_health
import policy
import tracker

ALERT_TIMEOUT = 20      # seconds, as the ladder's post
LOCK_WAIT = 20.0
CLEAR_SLACK = 60        # seconds a cleared= may lie after `now` before it is taken as a typo
ID_RE = re.compile(r"^cd[0-9]{12}$")
CD_ID = re.compile(r"(?<=\s)id=cd[0-9]{12}(?![0-9A-Za-z])")   # the marker's own id= field: a word of its own
CHOICES = ("wait", "accept-fallback")                   # what --choose writes; 09c adds "tests-alone"
READABLE = CHOICES + ("tests-alone",)                   # what the reader accepts
ASK = "Codex is down: choose wait or accept the fallback review"
DECISIONS = "Decisions in force"
DECISIONS_RE = re.compile(r"^##\s+%s\b" % DECISIONS)
CHOICE_RE = re.compile(r"^- \[codex-choice (cd[0-9]{12})\] (%s) - \S+$" % "|".join(READABLE))
UNSAFE = re.compile(r"[^A-Za-z0-9._/#-]")


def _say(message: str) -> None:
    print("codex_blocker: " + message, file=sys.stderr)


def default_alert() -> str:
    return os.environ.get("BOSS_ALERT", str(Path(__file__).resolve().parent / "bin" / "boss-alert"))


def usable_tracker(track: str) -> Path | None:
    """pm/<track>.md when it is a regular file the user owns, else None (said on stderr).
    A `track` that is not a plain name is a ValueError."""
    path = boss_store.tracker_path(track)
    if path is None:
        raise ValueError("track must match %s and hold no '..': %r" % (boss_store.TRACK_RE.pattern, track))
    try:
        st = os.lstat(path)
    except OSError:
        st = None
    if st is None or not stat_.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        _say("no blocker can be raised: %s is not a regular file of yours" % path)
        return None
    return path


def _is_cd(line: str) -> bool:
    """Does the line carry a marker whose own `id=` field is a `cd` id? Only the text from the `[ladder` token
    on is looked at, with the quoted values (ask=, cost=) taken out: `xid=cd...`, an id with a thirteenth digit
    and an id named in another blocker's prose are not this marker's."""
    if not tracker.has_marker(line):
        return False
    return bool(CD_ID.search(re.sub(r'"[^"]*"', '""', line[line.find(tracker.TOKEN):])))


def _classify(lines: list[str]):
    """(open_ids, broken) over the Open blockers body: indices of the open valid `cd` lines, and of the
    `cd` lines that cannot be read and are not closed by hand (each with its reason)."""
    lo, hi = tracker.blockers_range(lines)
    opened, broken = [], []
    for i in range(lo, hi):
        line = lines[i]
        if not _is_cd(line):
            continue
        try:
            found = tracker.scan_marker(line)
            m = tracker.validate(found[1]) if found else None
        except tracker.MarkerError as exc:
            if " cleared=" not in line:
                broken.append((i, str(exc)))
            continue
        if m is None or not ID_RE.match(m["id"]):
            continue
        if not m["cleared"]:
            opened.append(i)
    return opened, broken


def _newest_clear(lines: list[str], now: datetime, name: str) -> datetime | None:
    """Minute start of the newest usable `cleared=` on a readable `cd` line in the Open blockers body.
    One later than now + CLEAR_SLACK is ignored and said on stderr."""
    lo, hi = tracker.blockers_range(lines)
    newest = None
    for i in range(lo, hi):
        line = lines[i]
        if not _is_cd(line):
            continue
        try:
            found = tracker.scan_marker(line)
            m = tracker.validate(found[1]) if found else None
        except tracker.MarkerError:
            continue
        if m is None or not ID_RE.match(m["id"]) or not m["cleared"]:
            continue
        at = tracker.parse_ts(m["cleared"], "cleared")
        if at > now + timedelta(seconds=CLEAR_SLACK):
            _say("%s:%d has cleared=%s, later than now; ignored as invalid" % (name, i + 1, m["cleared"]))
            continue
        at = at.replace(second=0, microsecond=0)
        if newest is None or at > newest:
            newest = at
    return newest


def _new_id(text: str, now: datetime) -> tuple[str, datetime]:
    while True:
        id_ = "cd" + now.strftime("%y%m%d%H%M%S")
        if not re.search(r"id=%s(?![a-z0-9])" % id_, text):
            return id_, now
        now += timedelta(seconds=1)


def _open_cd(lines: list[str]):
    """(ids, broken): the ids of the open valid `cd` lines and the broken ones, as _classify finds them."""
    opened, broken = _classify(lines)
    ids = [tracker.validate(tracker.scan_marker(lines[i])[1])["id"] for i in opened]
    return ids, broken


def _choices_of(lines: list[str], id_: str) -> list[str]:
    """The choices recorded for `id_`, oldest first, from the first Decisions in force body only."""
    head = next((i for i, ln in enumerate(lines) if DECISIONS_RE.match(ln)), None)
    if head is None:
        return []
    out = []
    for ln in lines[head + 1:]:
        if tracker.NEXT_H2_RE.match(ln):
            break
        m = CHOICE_RE.match(ln.rstrip("\r"))
        if m and m.group(1) == id_:
            out.append(m.group(2))
    return out


def _state(lines: list[str]):
    """(status, id, choice) over the text: choice() without the file. `choice` holds the reason when malformed."""
    ids, broken = _open_cd(lines)
    if not ids and not broken:
        return "no-blocker", None, None
    if len(ids) + len(broken) > 1 or broken:
        why = ("%d open Codex down lines" % (len(ids) + len(broken)) if ids
               else "; ".join("line %d: %s" % (i + 1, w) for i, w in broken))
        return "malformed", None, why
    got = _choices_of(lines, ids[0])
    return ("chosen", ids[0], got[-1]) if got else ("none", ids[0], None)


def choice(track: str):
    """(status, id, choice) for `track`'s open Codex down blocker. status: `no-blocker`; `none` (open, no line
    carries its id); `chosen` (choice is the last one recorded); `malformed` (the only `cd` lines cannot be read,
    or more than one is open, or the tracker is not a regular file of yours; the third item is the reason). A bad
    `track` is a ValueError (the command prints `malformed` for it too)."""
    path = usable_tracker(track)
    if path is None:
        return "malformed", None, "pm/%s.md is not a regular file of yours" % track
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return "malformed", None, "%s cannot be read: %s" % (path.name, type(exc).__name__)
    return _state(text.split("\n"))


def choose(track: str, value: str, now: datetime | None = None) -> tuple[int, str]:
    """Record `value` for the open blocker: (exit code, message). Nothing is written when the last choice
    for its id already equals `value`; otherwise the line is added (so a revocation is never dropped by an
    earlier identical line) and the marker's ask= says what was chosen, so the ladder's repeats do not look lost."""
    if value not in CHOICES:
        raise ValueError("choice must be one of %s, not %r" % (", ".join(CHOICES), value))
    if now is None:
        now = datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError("now has no UTC offset")
    path = usable_tracker(track)
    if path is None:
        return 2, "no usable tracker for %s" % track
    result = {}

    def fn(text: str):
        result.clear()
        lines = text.split("\n")
        status, id_, got = _state(lines)
        if status in ("no-blocker", "malformed"):
            result["rc"], result["msg"] = 2, "%s: %s" % (status, got or "no Codex down blocker is open")
            return None
        result["rc"], result["msg"] = 0, "%s: %s" % (id_, value)
        if status == "chosen" and got == value:
            return None
        opened, _ = _classify(lines)
        lines[opened[0]] = tracker.set_ask(lines[opened[0]], "Codex down; owner chose " + value)
        return tracker.insert_in_section(
            "\n".join(lines), DECISIONS, "- [codex-choice %s] %s - %s" % (id_, value, now.isoformat(timespec="seconds")))

    got = tracker.update(path, fn, time.monotonic() + LOCK_WAIT)
    if got.startswith("failed"):
        return 1, "%s: %s" % (path.name, got)
    return result["rc"], result["msg"]


def _post(alert: str, rung: str, text: str) -> None:
    try:
        run = subprocess.run([alert, rung, text], capture_output=True, text=True, timeout=ALERT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _say("boss-alert %s failed: %s" % (rung, exc))
        return
    if run.returncode != 0:
        _say("boss-alert %s failed (%s): %s" % (rung, run.returncode, run.stderr.strip()[-200:]))


def sync(track: str, now: datetime | None = None, health_path=None) -> None:
    if now is None:
        now = datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError("now has no UTC offset: the ladder would report the marker malformed")
    path = usable_tracker(track)
    if path is None:
        return
    done = {}

    def fn(text: str):
        done.clear()
        h = codex_health.health(health_path)         # under the lock: the file and the state are read together
        lines = text.split("\n")
        opened, broken = _classify(lines)
        for i, why in broken:
            _say("%s:%d holds a Codex down marker that cannot be read (%s); the ladder reports it" % (path.name, i + 1, why))
        if h["state"] == "down" and h["failures"] >= policy.CODEX_DOWN_AFTER:
            if opened or broken:
                return None
            clear = _newest_clear(lines, now, path.name)
            if clear is not None and h["last_ts"] is not None and h["last_ts"] < clear:
                return None
            id_, at = _new_id(text, now)
            repo = UNSAFE.sub("?", str(h["last_repo"]))
            reason = UNSAFE.sub("?", str(h["last_reason"]))
            what = ("%d failed Codex attempts in a row (last: %s#%d %s; %d PRs affected)"
                    % (h["failures"], repo, h["last_pr"], reason, h["prs"]))
            marker = tracker.render_marker(id_, at, at + timedelta(minutes=policy.RUNGS[0]), ask=ASK)
            line = "- Codex down: %s - T+0 %s %s" % (what, at.isoformat(timespec="minutes"), marker)
            done["raise"] = "%s: Codex down: %s. %s" % (track, what, ASK)
            return tracker.insert_in_section(text, tracker.BLOCKERS, line)
        if h["state"] == "up" and opened:
            for i in opened:
                lines[i] = tracker.mark_cleared(lines[i], now)
            after, still = _classify(lines)
            if after or still:
                _say("%s: a Codex down line is cleared beside one that is not; no clear is posted" % path.name)
            else:
                done["clear"] = "%s: Codex answers again (%d in a row); the Codex down blocker is cleared" % (
                    track, h["answers"])
            return "\n".join(lines)
        return None

    got = tracker.update(path, fn, time.monotonic() + LOCK_WAIT)
    if got != "done":
        if got.startswith("failed"):
            _say("%s: %s" % (path.name, got))
        return
    alert = default_alert()
    if "raise" in done:
        _post(alert, "0", done["raise"])
    elif "clear" in done:
        _post(alert, "clear", done["clear"])


def main() -> int:
    argv = sys.argv[1:]
    try:
        if len(argv) == 3 and argv[0] == "--choose":
            rc, msg = choose(argv[1], argv[2])
            print(msg, file=sys.stderr if rc else sys.stdout)
            return rc
        if len(argv) == 2 and argv[0] == "--choice":
            status, id_, got = choice(argv[1])
            if status == "chosen":
                print(got)
                return 0
            print(status)
            if status == "malformed":
                _say(got)
            return {"none": 1}.get(status, 2)
        if len(argv) == 1 and not argv[0].startswith("--"):
            sync(argv[0])
            return 0
    except ValueError as exc:
        if argv[:1] == ["--choice"]:
            print("malformed")
        _say(str(exc))
        return 2
    print("usage: codex_blocker.py TRACK | --choose TRACK wait|accept-fallback | --choice TRACK", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
