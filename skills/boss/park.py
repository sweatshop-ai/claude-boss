#!/usr/bin/env python3
"""boss-park: a worker may sit idle only while an event the pulse can check has not happened.

    boss-park <track> <worker> --until <event>   park the worker (a new park replaces the old one)
    boss-park <track> --list                     the parks, each with what the pulse sees now
    boss-park <track> <worker> --clear           drop the park

The events, in `WAKE`: `ticket:<id>` (the ticket graph reports it done), `worker:<name>` (that
worker's session is idle or gone) and `owner:<question id>` (no open blocker of the tracker
names the question any more: the boss clears it when the concierge's `ANSWER` comes). A clock
time is no event. A park lasts `TTL_S`, then the pulse asks the boss again; a message from the
boss to the worker (boss-guard.py) or `--clear` drops it sooner.

A park is `{worker: {"event": ..., "since": epoch}}` in `pm/.pulse/<track>.parks.json`.
"""
import os
import re
import sys
import time
from collections import namedtuple
from pathlib import Path

import boss_store
import tracker

TTL_S = 2 * 3600
TARGET_RE = re.compile(r"[\w.-]{1,40}\Z")

Park = namedtuple("Park", "worker event since")
# What the pulse sees: ticket numbers the frontier reports done, {worker name: status} of the
# boss's live workers, the lines under Open blockers.
World = namedtuple("World", "done workers blockers", defaults=(frozenset(), {}, ()))


def _ticket(target, world):
    num = target.lstrip("0") or "0"
    return any((d.lstrip("0") or "0") == num for d in world.done)


def _worker(target, world):
    return world.workers.get(target, "idle") == "idle"      # gone counts as finished


def _owner(target, world):
    pat = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(target))
    return not any(pat.search(line) for line in world.blockers)


# kind -> (target label for the usage line, wake check). Ticket 04 adds the GitHub kinds here.
WAKE = {
    "ticket": ("<id>", _ticket),
    "worker": ("<name>", _worker),
    "owner": ("<question id>", _owner),
}


def allowed():
    return ", ".join("%s:%s" % (k, v[0]) for k, v in WAKE.items())


def parse_event(text):
    """(kind, target) of an event, or ValueError naming the allowed events."""
    kind, sep, target = (text or "").strip().partition(":")
    if kind not in WAKE or not sep or not TARGET_RE.match(target.strip()):
        raise ValueError("not an event: %r. Allowed: %s (a clock time is not one)"
                         % (text, allowed()))
    return kind, target.strip()


def read_parks(track, cfg=None):
    """{worker: Park} for this track; an entry that is not a worker's park is skipped."""
    path = boss_store.parks_path(track, cfg)
    if path is None:
        return {}
    out = {}
    for worker, rec in boss_store.read_json(path).items():
        if (isinstance(rec, dict) and isinstance(rec.get("event"), str)
                and isinstance(rec.get("since"), (int, float))):
            out[worker] = Park(worker, rec["event"], rec["since"])
    return out


def _update(track, fn, cfg):
    path = boss_store.parks_path(track, cfg)
    if path is None:
        raise ValueError("not a track name: %r" % track)
    return boss_store.update_json(path, fn)


def set_park(track, worker, event, now=None, cfg=None):
    parse_event(event)
    if not TARGET_RE.match(worker or ""):
        raise ValueError("not a worker name: %r" % worker)
    since = time.time() if now is None else now
    _update(track, lambda st: st.update({worker: {"event": event, "since": since}}), cfg)


def clear(track, worker, cfg=None):
    """Drop the worker's park; True when there was one."""
    if worker not in boss_store.read_json(boss_store.parks_path(track, cfg) or Path(os.devnull)):
        return False                        # nothing to drop: no lock, no file written
    had = []
    _update(track, lambda st: had.append(st.pop(worker, None)), cfg)
    return had[0] is not None


def state(p, now, world):
    """`over` (its event happened), `expired` (TTL_S passed first) or `waiting`."""
    kind, _, target = p.event.partition(":")
    if kind in WAKE and WAKE[kind][1](target, world):
        return "over"
    return "expired" if now - p.since >= TTL_S else "waiting"


def open_blocker_lines(track, cfg=None):
    body = boss_store.read_tracker(track, cfg)
    return tuple(tracker.blocker_lines(body)) if body else ()


def _usage():
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    return 2


def main(argv):
    args = list(argv)
    if len(args) < 2 or not boss_store.valid_track(args[0]):
        return _usage()
    track, rest = args[0], args[1:]
    try:
        if rest == ["--list"]:
            parks = read_parks(track)
            world = World(blockers=open_blocker_lines(track))
            now = time.time()
            for w, p in sorted(parks.items()):
                # ticket and worker events need the graph and the fleet, which only the pulse
                # reads: the list judges expiry and the owner's answer, and says "waiting" else.
                st = state(p, now, world) if p.event.startswith("owner:") else (
                    "expired" if now - p.since >= TTL_S else "waiting")
                print("%s\t%s\t%s\t%d min" % (w, p.event, st, (now - p.since) // 60))
            if not parks:
                print("no parks")
            return 0
        if len(rest) == 2 and rest[1] == "--clear":
            print("cleared" if clear(track, rest[0]) else "no park for %s" % rest[0])
            return 0
        if len(rest) == 3 and rest[1] == "--until":
            kind, target = parse_event(rest[2])
            if kind == "owner" and _owner(target, World(blockers=open_blocker_lines(track))):
                raise ValueError("no open blocker of %s names %s: write the question on its "
                                 "line under Open blockers first" % (track, target))
            set_park(track, rest[0], "%s:%s" % (kind, target))
            print("parked %s until %s:%s" % (rest[0], kind, target))
            return 0
    except ValueError as exc:
        print("boss-park: %s" % exc, file=sys.stderr)
        return 2
    return _usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
