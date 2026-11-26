#!/usr/bin/env python3
"""boss-park: a worker may sit idle only while an event the pulse can check has not happened.

    boss-park <track> <worker> --until <event>   park the worker (a new park replaces the old one)
    boss-park <track> --list                     the parks, each with what the pulse sees now
    boss-park <track> <worker> --clear           drop the park
    boss-park <track> <worker> --retire          the worker was retired for memory: keep the park
    boss-park <track> <worker> --clear --retired drop a retired worker's kept park

The events, in `WAKE`: `ticket:<id>` (the ticket graph reports it done), `worker:<name>` (that
worker's session is idle or gone), `owner:<question id>` (no open blocker of the tracker
names the question any more: the boss clears it when the concierge's `ANSWER` comes),
`pr:<owner/repo#N>-merged` (the PR is merged, or closed and so never will be) and
`ci:<owner/repo#N>` (every check run of the PR's head has concluded, or the PR is no longer
open). The two GitHub events are read with one `gh pr view` per PR, cached for `GH_CACHE_S`,
so the Stop hook stays fast; a failed call keeps the park and goes to `pm/park-gh.log`. A worker
that ends its turn waiting on CI or review of its own PR parks itself on `ci:` (SKILL.md). A clock
time is no event. A park lasts `TTL_S`, then the pulse asks the boss again; a message from the
boss to the worker (boss-guard.py) or `--clear` drops it sooner.

A park is `{worker: {"event": ..., "since": epoch}}` in `pm/.pulse/<track>.parks.json`. A
retired worker's park moves to the key `retired:<worker>` with `"retired": epoch` (when), so a
new session that gets the name neither inherits it nor wipes it.
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

import boss_store
import tracker

TTL_S = 2 * 3600
TARGET_RE = re.compile(r"[\w.-]{1,40}\Z")
PR = r"\w[\w.-]{0,99}/\w[\w.-]{0,99}#\d{1,7}"      # no leading "-": it goes to `gh --repo`
TARGETS = {"pr": re.compile(PR + r"-merged\Z"), "ci": re.compile(PR + r"\Z")}   # kind -> target form
GH_CACHE_S = 60         # one `gh` call per PR per minute, a failed one included
GH_CALL_S = 3           # one call's timeout; the Stop hook has 5 s in all
GH_BUDGET_S = 3.5       # all the calls of one pulse

RETIRED = "retired:"
RETIRE_GAP_S = 15 * 60          # after a retire for memory, the pulse retires no other for this long
# `retired`: when the worker was retired (epoch), False for a live park; `worker` is the bare name.
Park = namedtuple("Park", "worker event since retired", defaults=(False,))
# What the pulse sees: ticket numbers the frontier reports done, {worker name: status} of the
# boss's live workers, the lines under Open blockers.
# `prs(repo, number)` is the GitHub lookup (pr_lookup): {"state", "ci_done"} or None when unknown.
# `blockers` is None when the tracker could not be read: an owner park is then never over.
World = namedtuple("World", "done workers blockers prs", defaults=(frozenset(), {}, (), None))


def _ticket(target, world):
    num = target.lstrip("0") or "0"
    return any((d.lstrip("0") or "0") == num for d in world.done)


def _worker(target, world):
    return world.workers.get(target, "idle") == "idle"      # gone counts as finished


def _owner(target, world):
    if world.blockers is None:              # tracker unread: no blocker line proves nothing
        return False
    pat = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(target))
    return not any(pat.search(line) for line in world.blockers)


def _pr_of(target, world):
    """The lookup's answer for `owner/repo#N[-merged]`, None when unknown or there is no lookup."""
    repo, _, num = target.removesuffix("-merged").partition("#")
    return world.prs(repo, int(num)) if world.prs else None


def _pr_ended(target, world):
    pr = _pr_of(target, world)
    return bool(pr) and pr["state"] != "OPEN"


def _ci(target, world):
    pr = _pr_of(target, world)
    return bool(pr) and (pr["state"] != "OPEN" or pr["ci_done"])


# kind -> (target label for the usage line, wake check).
WAKE = {
    "ticket": ("<id>", _ticket),
    "worker": ("<name>", _worker),
    "owner": ("<question id>", _owner),
    "pr": ("<owner/repo#N>-merged", _pr_ended),
    "ci": ("<owner/repo#N>", _ci),
}


def gh_run(args, timeout):
    """`gh <args>` stdout; raises OSError, SubprocessError or ValueError on any failure."""
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise ValueError("gh exited %d: %s" % (r.returncode, r.stderr.strip()[:200]))
    return r.stdout


def _pr_info(text):
    """{"state", "ci_done"} from `gh pr view --json state,statusCheckRollup`; ValueError when unreadable."""
    try:
        data = json.loads(text)
        state, rollup = data["state"], data.get("statusCheckRollup") or []
        if not isinstance(state, str) or not isinstance(rollup, list):
            raise TypeError(state)
        def over(c):
            if c.get("__typename") == "StatusContext":
                return c.get("state") not in ("PENDING", "EXPECTED")
            return c.get("status") == "COMPLETED"
        return {"state": state, "ci_done": bool(rollup) and all(over(c) for c in rollup)}
    except (TypeError, KeyError, AttributeError, ValueError) as exc:
        raise ValueError("unreadable gh output: %s" % exc)


def _gh_log(cfg, key, why):
    try:
        path = boss_store.pm_dir(cfg) / "park-gh.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), key, why))
    except OSError:
        pass


def pr_lookup(track, now=None, cfg=None, run=None):
    """A `World.prs`: (repo, number) -> {"state", "ci_done"} or None, never raising.

    An answer, or a failure, is kept in `pm/.pulse/<track>.gh.json` for GH_CACHE_S, so repeated
    Stops make no new call. A failure is logged and reads as unknown: the park holds."""
    now = time.time() if now is None else now
    run = run or gh_run
    path = boss_store.gh_cache_path(track, cfg)
    deadline = time.monotonic() + GH_BUDGET_S

    def lookup(repo, number):
        key = "%s#%d" % (repo, number)
        hit = boss_store.read_json(path).get(key) if path else None
        if isinstance(hit, dict) and isinstance(hit.get("at"), (int, float)) and 0 <= now - hit["at"] < GH_CACHE_S:
            return hit.get("info")
        left = deadline - time.monotonic()
        if left <= 0:
            _gh_log(cfg, key, "pulse budget spent, not asked")
            return None                         # this pulse's budget is spent: ask again next time
        try:
            info = _pr_info(run(["pr", "view", str(number), "--repo", repo,
                                 "--json", "state,statusCheckRollup"], min(GH_CALL_S, left)))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            info = None
            _gh_log(cfg, key, exc)
        if path:
            try:
                boss_store.update_json(path, lambda st: st.update({key: {"at": now, "info": info}}))
            except OSError:
                pass
        return info
    return lookup


def allowed():
    return ", ".join("%s:%s" % (k, v[0]) for k, v in WAKE.items())


def parse_event(text):
    """(kind, target) of an event, or ValueError naming the allowed events."""
    kind, sep, target = (text or "").strip().partition(":")
    if kind not in WAKE or not sep or not TARGETS.get(kind, TARGET_RE).match(target.strip()):
        raise ValueError("not an event: %r. Allowed: %s (a clock time is not one)"
                         % (text, allowed()))
    return kind, target.strip()


def read_parks(track, cfg=None):
    """{worker: Park} for this track; an entry that is not a worker's park is skipped."""
    path = boss_store.parks_path(track, cfg)
    if path is None:
        return {}
    out = {}
    for key, rec in boss_store.read_json(path).items():
        if (isinstance(rec, dict) and isinstance(rec.get("event"), str)
                and isinstance(rec.get("since"), (int, float))):
            at = rec.get("retired")
            retired = at if isinstance(at, (int, float)) and not isinstance(at, bool) else False
            worker = key[len(RETIRED):] if key.startswith(RETIRED) else key
            out[key] = Park(worker, rec["event"], rec["since"], retired)
    return out


def _update(track, fn, cfg):
    path = boss_store.parks_path(track, cfg)
    if path is None:
        raise ValueError("not a track name: %r" % track)
    return boss_store.update_json(path, fn, strict=True)


def set_park(track, worker, event, now=None, cfg=None):
    parse_event(event)
    if not TARGET_RE.match(worker or ""):
        raise ValueError("not a worker name: %r" % worker)
    since = time.time() if now is None else now
    _update(track, lambda st: st.update({worker: {"event": event, "since": since}}), cfg)


def clear(track, worker, cfg=None, retired=False):
    """Drop the worker's park (its kept retired park with `retired`); True when there was one."""
    key = RETIRED + worker if retired else worker
    if key not in boss_store.read_json(boss_store.parks_path(track, cfg) or Path(os.devnull)):
        return False                        # nothing to drop: no lock, no file written
    had = []
    _update(track, lambda st: had.append(st.pop(key, None)), cfg)
    return had[0] is not None


def retire(track, worker, cfg=None, now=None):
    """Move the worker's park under `retired:<worker>`: its event stays recorded, so the pulse
    can say when its work may be picked up, but a new session that gets the same name neither
    inherits it nor wipes it. True when there was a park. A kept park of an earlier worker of
    that name is never overwritten: ValueError says to hand its work on and clear it first."""
    had = []

    def move(st):
        if isinstance(st.get(worker), dict):
            if RETIRED + worker in st:
                raise ValueError("a retired park of %s is still kept: hand its work on and "
                                 "`boss-park %s %s --clear --retired` first" % (worker, track, worker))
            st[RETIRED + worker] = dict(st.pop(worker), retired=time.time() if now is None else now)
            had.append(True)
    _update(track, move, cfg)
    return bool(had)


def state(p, now, world):
    """`over` (its event happened), `expired` (TTL_S passed first) or `waiting`."""
    kind, _, target = p.event.partition(":")
    if kind in WAKE and WAKE[kind][1](target, world):
        return "over"
    return "expired" if now - p.since >= TTL_S else "waiting"


def open_blocker_lines(track, cfg=None):
    """The lines under Open blockers; None when the tracker is missing or unreadable."""
    body = boss_store.read_tracker(track, cfg)
    return None if body is None else tuple(tracker.blocker_lines(body))


def unread_problem(track, sid, cfg=None, listing=False):
    """Why no pulse would ever read this track's parks, with what to run; None when a pulse reads them.

    The pulse of a boss reads only the parks of the track in its marker. A park on a track no boss
    marker names is never checked: the worker sits idle past its event (2026-11-26, a boss whose
    marker still named its previous track). A track another live boss is marked with is read by
    that boss's pulse, so it is no problem here."""
    if track in boss_store.marked_tracks(cfg):
        return None
    what = "no pulse reads these parks" if listing else "no pulse reads its parks and this park would never wake"
    mine = boss_store.track_of(sid, cfg) if sid else ""
    if mine:
        return ("no boss marker names track %s, so %s. This session's marker names %s: if you now run %s, "
                "run `boss-marker register %s`, then park again" % (track, what, mine, track, track))
    return ("no boss marker names track %s, so %s. The boss of %s runs `boss-marker register %s` "
            "(a worker asks its boss to), then park again" % (track, what, track, track))


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
            for _, p in sorted(parks.items()):
                w = p.worker
                # ticket and worker events need the graph and the fleet, which only the pulse
                # reads: the list judges expiry and the owner's answer, and says "waiting" else.
                st = state(p, now, world) if p.event.startswith("owner:") else (
                    "expired" if now - p.since >= TTL_S else "waiting")
                print("%s\t%s\t%s\t%d min" % (w, p.event, "retired, " + st if p.retired else st,
                                               (now - p.since) // 60))
            if not parks:
                print("no parks")
            elif unread_problem(track, "", listing=True):
                print("boss-park: %s" % unread_problem(track, "", listing=True), file=sys.stderr)
            return 0
        if len(rest) == 2 and rest[1] == "--retire":
            print("retired park kept" if retire(track, rest[0]) else "no park for %s" % rest[0])
            return 0
        if len(rest) == 3 and rest[1:] == ["--clear", "--retired"]:
            print("cleared" if clear(track, rest[0], retired=True)
                  else "no retired park for %s" % rest[0])
            return 0
        if len(rest) == 2 and rest[1] == "--clear":
            print("cleared" if clear(track, rest[0]) else "no park for %s" % rest[0])
            return 0
        if len(rest) == 3 and rest[1] == "--until":
            kind, target = parse_event(rest[2])
            why = unread_problem(track, os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
            if why:
                raise ValueError(why)
            if kind == "owner" and _owner(target, World(blockers=open_blocker_lines(track) or ())):
                raise ValueError("no open blocker of %s names %s: write the question on its "
                                 "line under Open blockers first" % (track, target))
            set_park(track, rest[0], "%s:%s" % (kind, target))
            print("parked %s until %s:%s" % (rest[0], kind, target))
            return 0
    except ValueError as exc:
        print("boss-park: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("boss-park: nothing was written: %s" % exc, file=sys.stderr)
        return 1
    return _usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
