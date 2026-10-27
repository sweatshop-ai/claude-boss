#!/usr/bin/env python3
"""SessionEnd hook and sweeper for the boss's per-session state.

Two things accumulate. `pm/.boss-sessions/<session_id>` marks a session as a
boss and is what `boss-guard.py` and `boss-pulse.py` check
first; the installation audit of 2026-09-20 found 18 of 20 stale. And
`pm/.pulse/` holds the rate-limit and guard state keyed by session id —
measured the same evening, 9 of 17 files orphaned, the oldest 11 days.

Nothing removed them because nothing was watching a session end. This is that
hook, plus `--sweep` for the ones that got away (a crash leaves no SessionEnd).

THIS IS THE ONE BOSS SCRIPT THAT DELETES THINGS, so it is deliberately timid:

  * It only ever looks in `pm/.boss-sessions/` and `pm/.pulse/`, never deeper,
    and never follows a symlink out of them.
  * A file is a candidate only if its NAME CONTAINS A SESSION UUID. That is
    what protects files such as `jev.log` and `jev.mode`, left in `pm/.pulse/`
    by the retired jev hook: they are the owner's to delete, not ours.
  * `--sweep` spares anything touched in the last GRACE_S. A session that has
    just started has no registry file yet, so "no session" and "not yet" look
    identical for the first minutes.

Usage:
    boss-reap.py                  SessionEnd hook: reap the ending session
    boss-reap.py --sweep          reap every session that is gone
    boss-reap.py --sweep --dry-run    say what it would reap, touch nothing
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402
import registry  # noqa: E402

UUID = boss_store.UUID
GRACE_S = 30 * 60      # a session younger than this may simply not be registered yet


def live_session_ids():
    """Every session id Claude Code has a live session for.

    A peer file alone is not enough: Claude Code does not always remove it
    when the session ends, and a marker kept alive by a leftover file is
    exactly the stale state this script exists to clear.
    """
    return {str(rec.get("sessionId")).lower()
            for rec in registry.live(boss_store.config_dir()) if rec.get("sessionId")}


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
    return [p for p, s in boss_store.reap_candidates() if s == sid and drop(p, dry)]


def sweep(dry=False, now=None):
    import time
    now = now or time.time()
    live = live_session_ids()
    gone = []
    for p, sid in boss_store.reap_candidates():
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
