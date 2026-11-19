#!/usr/bin/env python3
"""Why the pulse said nothing: one line per Stop of a boss session.

`pm/.pulse/<sid>.silence.log` holds tab-separated lines: time, track, the gate
that held the pulse back (or `fired`), then `key=value` details. The log
rotates to `<sid>.silence.log.1` at MAX_BYTES, so it is bounded at twice that.
Reap removes both with the session's other state. `summary` reads every
session's log, so a track that changed boss keeps its history.

Writing is best effort: a log that cannot be written never fails the hook.
"""
import time

import boss_store

MAX_BYTES = 1024 * 1024
DAY_S = 86400


def record(sid, track, gate, now=None, cfg=None, **details):
    """Append one line. `details` with a value of None are left out."""
    try:
        p = boss_store.state_path(sid, "silence", cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.stat().st_size >= MAX_BYTES:
                p.replace(p.with_name(p.name + ".1"))
        except FileNotFoundError:
            pass
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now or time.time()))
        fields = [stamp, track or "-", gate]
        fields += ["%s=%s" % (k, str(v).replace("\t", " ").replace("\n", " "))
                   for k, v in details.items() if v is not None]
        with open(p, "a", encoding="utf-8") as f:
            f.write("\t".join(fields) + "\n")
    except (OSError, ValueError):
        pass


def summary(track, now=None, cfg=None, window=DAY_S):
    """({gate: count} for the last `window` seconds, time of the last `fired` or None)."""
    now = now or time.time()
    counts, last = {}, None
    d = boss_store.state_dir(cfg)
    try:
        files = [p for p in d.iterdir() if ".silence.log" in p.name and p.is_file()]
    except OSError:
        return counts, last
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            f = line.split("\t")
            if len(f) < 3 or f[1] != track:
                continue
            try:
                t = time.mktime(time.strptime(f[0], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                continue
            if f[2] == "fired" and (last is None or t > last):
                last = t                      # the last firing, whatever its age
            if now - t <= window:
                counts[f[2]] = counts.get(f[2], 0) + 1
    return counts, last


def why(track, cfg=None, now=None):
    """The text of `boss-pulse why <track>`."""
    counts, last = summary(track, now=now, cfg=cfg)
    if not counts and last is None:
        return "track %s: no Stop recorded in the last day" % track
    out = ["track %s, last 24 h, Stops by gate:" % track]
    out += ["  %-18s %d" % (g, n) for g, n in sorted(counts.items(), key=lambda x: -x[1])]
    out.append("last fired: " + (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last))
                                 if last else "never recorded"))
    return "\n".join(out)
