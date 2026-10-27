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
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

SID_RE = re.compile(r"^[\w-]{1,80}$")
TRACK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                  r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Per-session state under pm/.pulse/: kind -> file name suffix. The names are the
# ones the hooks have always written, so a state file survives the upgrade.
STATE_KINDS = {"guard": ".guard.json", "pulse": ".json"}
LOCK_NAME = ".state.lock"


def config_dir(cfg=None):
    """The config directory: `cfg` when given, else `$CLAUDE_CONFIG_DIR`, else `~/.claude`.

    An empty variable is unset. It is read on every call, so a test that sets it
    (or passes `cfg`) is heard, and a hook never holds a stale copy.
    """
    if cfg is not None:
        return Path(cfg)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def pm_dir(cfg=None):
    return config_dir(cfg) / "pm"


def markers_dir(cfg=None):
    return pm_dir(cfg) / ".boss-sessions"


def state_dir(cfg=None):
    return pm_dir(cfg) / ".pulse"


def frontier_cache(track, source, cfg=None):
    """Where the last `frontier.py --json` of this track's GitHub graph is kept.

    Keyed by the source too, so a track moved to another graph never reads the
    old one's tickets. `boss-goal check` writes the same file with bash (a
    `sha1sum` of the source's bytes); test_bash_agreement.py keeps the two equal.
    """
    key = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return state_dir(cfg) / ("%s.%s.frontier.json" % (track, key))


def valid_track(track):
    return bool(track) and bool(TRACK_RE.match(track)) and ".." not in track


def objective_path(track, cfg=None):
    """`pm/<track>.goal.md`, or None when `track` is not a plain track name."""
    return pm_dir(cfg) / (track + ".goal.md") if valid_track(track) else None


def tracker_path(track, cfg=None):
    """`pm/<track>.md`, or None when `track` is not a plain track name."""
    return pm_dir(cfg) / (track + ".md") if valid_track(track) else None


def _read(path):
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_objective(track, cfg=None):
    """The objective's text, or None when it is missing, unreadable or the track is invalid."""
    return _read(objective_path(track, cfg))


def read_tracker(track, cfg=None):
    """The tracker's text, or None when it is missing, unreadable or the track is invalid."""
    return _read(tracker_path(track, cfg))


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


def state_path(sid, kind, cfg=None):
    """Where this session's state of this kind lives: `pm/.pulse/<sid><suffix>`."""
    if not sid or not SID_RE.match(sid):
        raise ValueError("not a session id: %r" % sid)
    if kind not in STATE_KINDS:
        raise ValueError("not a state kind: %r (%s)" % (kind, ", ".join(sorted(STATE_KINDS))))
    return state_dir(cfg) / (sid + STATE_KINDS[kind])


def read_state(sid, kind, cfg=None):
    """The state as it is now, `{}` when the file is missing, unreadable or not an object."""
    try:
        st = json.loads(state_path(sid, kind, cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


def update_state(sid, kind, fn, cfg=None):
    """Read the state, let `fn` change it, write it back. Returns the new state.

    `fn(state)` changes the dict in place or returns a new one. The whole round
    trip holds `flock` on one lock file beside the state files, so two hooks of
    one session never lose each other's update. The lock is its own file with no
    UUID in its name, never the state file: reap deletes state files, and a lock
    taken on a deleted inode would let a second process lock a new file at once.
    The new JSON goes to a temp file in the same directory and replaces the old
    one, so a `fn` that raises, or a crash, leaves the old file as it was.

    A directory that cannot be written is not an error: the hook still has to
    exit 0, so `fn` runs on whatever could be read and its result is returned.
    """
    f = state_path(sid, kind, cfg)
    lock = None
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        lock = open(f.parent / LOCK_NAME, "a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    except OSError:
        if lock is not None:
            lock.close()
        lock = None
    try:
        state = read_state(sid, kind, cfg)
        new = fn(state)
        if not isinstance(new, dict):
            new = state
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".state-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(new))
            os.replace(tmp, f)
        except OSError:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return new
    finally:
        if lock is not None:
            lock.close()


def reap_candidates(cfg=None):
    """`(path, session_id)` for every file in the boss-file and `.pulse/` directories
    whose name holds a session UUID, the id lower-cased.

    A name with no UUID is never returned: that is what keeps files such as
    `jev.log` out of reap's reach. A UUID anywhere in the name counts, as it
    always has; symlinks and directories do not.
    """
    for d in (markers_dir(cfg), state_dir(cfg)):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_symlink() or not p.is_file():
                continue
            m = UUID.search(p.name)
            if m:
                yield p, m.group(0).lower()


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
