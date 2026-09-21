#!/usr/bin/env python3
"""SessionEnd hook and sweeper for the boss's per-session state.

Two things accumulate. `pm/.boss-sessions/<session_id>` marks a session as a
boss and is what `boss-guard.py`, `boss-pulse.py` and `boss-jev.py` all check
first; the installation audit of 2026-09-20 found 18 of 20 stale. And
`pm/.pulse/` holds the rate-limit, jev and guard state keyed by session id —
measured the same evening, 9 of 17 files orphaned, the oldest 11 days.

Nothing removed them because nothing was watching a session end. This is that
hook, plus `--sweep` for the ones that got away (a crash leaves no SessionEnd).

THIS IS THE ONE BOSS SCRIPT THAT DELETES THINGS, so it is deliberately timid:

  * It only ever looks in `pm/.boss-sessions/` and `pm/.pulse/`, never deeper,
    and never follows a symlink out of them.
  * A file is a candidate only if its NAME CONTAINS A SESSION UUID. That is
    what protects `jev.mode`, `jev.log` and `jev.mode.bak-*`, which sit in
    `pm/.pulse/` beside the per-session files. Reaping `jev.mode` would put jev
    back to `armed` without anyone asking — a silent behaviour change, the
    worst kind.
  * `--sweep` spares anything touched in the last GRACE_S. A session that has
    just started has no registry file yet, so "no session" and "not yet" look
    identical for the first minutes.

Usage:
    boss-reap.py                  SessionEnd hook: reap the ending session
    boss-reap.py --sweep          reap every session that is gone
    boss-reap.py --sweep --dry-run    say what it would reap, touch nothing
"""
import json
import os
import re
import sys
from pathlib import Path

CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
PM = CFG / "pm"
MARKERS = PM / ".boss-sessions"
STATE = PM / ".pulse"
SESSIONS = CFG / "sessions"

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                  r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
GRACE_S = 30 * 60      # a session younger than this may simply not be registered yet


def live_session_ids():
    """Every session id Claude Code currently publishes."""
    out = set()
    if not SESSIONS.is_dir():
        return out
    for p in SESSIONS.glob("*.json"):
        m = UUID.search(p.name)
        if m:
            out.add(m.group(0).lower())
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sid = rec.get("sessionId")
        if sid:
            out.add(str(sid).lower())
    return out


def candidates():
    """(path, session_id) for every file in the two directories that names one.

    A file whose name holds no UUID is not a candidate and is never returned,
    which is the whole safety property.
    """
    for d in (MARKERS, STATE):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_symlink() or not p.is_file():
                continue
            m = UUID.search(p.name)
            if m:
                yield p, m.group(0).lower()


def drop(path, dry):
    if dry:
        return True
    try:
        path.unlink()
    except OSError:
        return False
    return True


def reap_session(sid, dry=False):
    sid = (sid or "").lower()
    if not UUID.fullmatch(sid):
        return []
    return [p for p, s in candidates() if s == sid and drop(p, dry)]


def sweep(dry=False, now=None):
    import time
    now = now or time.time()
    live = live_session_ids()
    gone = []
    for p, sid in candidates():
        if sid in live:
            continue
        try:
            if now - p.stat().st_mtime < GRACE_S:
                continue              # too young to call dead
        except OSError:
            continue
        if drop(p, dry):
            gone.append(p)
    return gone


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args

    if "--sweep" in args:
        gone = sweep(dry=dry)
        for p in gone:
            print("%s %s" % ("would reap" if dry else "reaped", p))
        return 0

    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    for p in reap_session(payload.get("session_id") or "", dry=dry):
        print("%s %s" % ("would reap" if dry else "reaped", p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
