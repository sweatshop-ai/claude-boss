#!/usr/bin/env python3
"""The boss marker, and the one rule for reading it.

`$CLAUDE_CONFIG_DIR/pm/.boss-sessions/<session_id>` says a session is a boss.
Its first line, once the boss has claimed one, is the track: the name of its
tracker `pm/<track>.md` and objective `pm/<track>.goal.md`.

    boss-marker register [track]   mark this session a boss (CLAUDE_CODE_SESSION_ID)
    boss-marker track              print this session's track, or exit 1
    boss-marker is-boss            exit 0 when this session is a boss

Every hook reads the marker through `is_boss()` and `track_of()`, and the boss
writes it through `boss-marker register`. A marker is a regular file of this
user, never a symlink or a directory. A track is a plain name, because it
becomes a file name under pm/; a marker holding anything else has no track.
"""
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

SID_RE = re.compile(r"^[\w-]{1,80}$")
TRACK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def config_dir(cfg=None):
    if cfg is not None:
        return Path(cfg)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def pm_dir(cfg=None):
    return config_dir(cfg) / "pm"


def markers_dir(cfg=None):
    return pm_dir(cfg) / ".boss-sessions"


def valid_track(track):
    return bool(track) and bool(TRACK_RE.match(track)) and ".." not in track


def _marker(sid, cfg):
    if not sid or not SID_RE.match(sid):
        return None
    return markers_dir(cfg) / sid


def is_boss(sid, cfg=None):
    """True when this session has a marker: a regular file of this user."""
    path = _marker(sid, cfg)
    if path is None:
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()


def track_of(sid, cfg=None):
    """The track in this session's marker, or "" when it has none or a bad one."""
    if not is_boss(sid, cfg):
        return ""
    try:
        lines = _marker(sid, cfg).read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return ""
    track = lines[0].strip() if lines else ""
    return track if valid_track(track) else ""


def register(sid, track="", cfg=None):
    """Mark the session a boss, with its track when it has one. Atomic."""
    path = _marker(sid, cfg)
    if path is None:
        raise ValueError("not a session id: %r" % sid)
    if track and not valid_track(track):
        raise ValueError("not a track name: %r (lowercase letters, digits, . _ -)" % track)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".marker-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(track + "\n" if track else "")
    os.replace(tmp, path)


def main(argv):
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    cmd = argv[0] if argv else ""
    if cmd == "register" and len(argv) <= 2:
        try:
            register(sid, argv[1] if len(argv) == 2 else "")
        except (ValueError, OSError) as exc:
            print("boss-marker: %s" % exc, file=sys.stderr)
            return 1
        return 0
    if cmd == "track" and len(argv) == 1:
        track = track_of(sid)
        if not track:
            return 1
        print(track)
        return 0
    if cmd == "is-boss" and len(argv) == 1:
        return 0 if is_boss(sid) else 1
    print(__doc__.split("\n\n")[2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
