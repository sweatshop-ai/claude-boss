#!/usr/bin/env python3
"""The "Codex down" blocker: raised when codex_health says down, cleared when it says up.

    sync(track, now=None)    one locked step on pm/<track>.md, then at most one boss-alert

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
ID_RE = re.compile(r"^cd[0-9]{12}$")
CD_IN_TEXT = re.compile(r"id=cd[0-9]{12}")
ASK = "Codex is down: choose wait, accept the fallback review, or merge on tests alone"
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


def _classify(lines: list[str]):
    """(open_ids, broken) over the Open blockers body: indices of the open valid `cd` lines, and of the
    `cd` lines that cannot be read and are not closed by hand (each with its reason)."""
    lo, hi = tracker.blockers_range(lines)
    opened, broken = [], []
    for i in range(lo, hi):
        line = lines[i]
        if not tracker.has_marker(line) or not CD_IN_TEXT.search(line):
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


def _new_id(text: str, now: datetime) -> tuple[str, datetime]:
    while True:
        id_ = "cd" + now.strftime("%y%m%d%H%M%S")
        if not re.search(r"id=%s(?![a-z0-9])" % id_, text):
            return id_, now
        now += timedelta(seconds=1)


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
    if len(sys.argv) != 2:
        print("usage: codex_blocker.py TRACK", file=sys.stderr)
        return 2
    try:
        sync(sys.argv[1])
    except ValueError as exc:
        _say(str(exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
