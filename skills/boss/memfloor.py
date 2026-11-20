#!/usr/bin/env python3
"""The memory floor: a spawn must leave policy.MEMORY_FLOOR_GB of MemAvailable free.

    memfloor.py check [--boss PANE] [--meminfo FILE]
    memfloor.py settle --pid PID [--boss PANE] [--timeout SECONDS]

Exit 0 when the new worker fits, 1 with the refusal on stderr when it would
not. The new worker is estimated as the mean resident size of the boss's
current workers, at least policy.WORKER_MIN_GB. BOSS_MEMINFO names another
meminfo file (tests). boss-lifecycle.sh spawn runs it.

settle waits, at most --timeout seconds, until the process tree under PID is as
large as check estimated it or has stopped growing: a starting worker has taken only a part of its memory,
and the next boss's check would count the rest as free. spawn holds its lock until then.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import policy

KB_PER_GB = 1024 * 1024


def mem_available_kb(path="/proc/meminfo"):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    raise ValueError("no MemAvailable in %s" % path)


def worker_cost_kb(rss_kb):
    """The mean of the workers' resident sizes, never under the minimum."""
    least = int(policy.WORKER_MIN_GB * KB_PER_GB)
    return max(least, sum(rss_kb) // len(rss_kb)) if rss_kb else least


def refusal(avail_kb, rss_kb):
    """Why a spawn is refused, with the numbers, or None when it fits."""
    cost = worker_cost_kb(rss_kb)
    if avail_kb - cost >= policy.MEMORY_FLOOR_GB * KB_PER_GB:
        return None
    return ("not spawning: %.1f GB free, a new worker costs about %.1f GB, and the %d GB floor "
            "would not hold (%.1f GB left)" % (avail_kb / KB_PER_GB, cost / KB_PER_GB, policy.MEMORY_FLOOR_GB,
                                              (avail_kb - cost) / KB_PER_GB))


def rss_kb(pid):
    try:
        for line in Path("/proc/%d/status" % int(pid)).read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def boss_worker_rss(boss_pane):
    """Resident kB of each live worker of this boss; empty when tmux or the boss is not there."""
    import boss_store
    import fleet
    import registry
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
    except fleet.TmuxUnavailable:
        return []
    rss = (rss_kb(s.session.get("pid")) for s in fleet.workers(seats, boss_pane) if s.session)
    return [r for r in rss if r]


def tree_rss_kb(pid):
    """Resident kB of PID and everything under it."""
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    rows = [tuple(int(x) for x in line.split()) for line in out.splitlines() if len(line.split()) == 3]
    kids = {}
    for p, pp, r in rows:
        kids.setdefault(pp, []).append(p)
    rss = {p: r for p, _, r in rows}
    seen, todo = set(), [int(pid)]
    while todo:
        p = todo.pop()
        if p not in seen:
            seen.add(p)
            todo.extend(kids.get(p, []))
    return sum(rss.get(p, 0) for p in seen)


LEVEL_POLLS = 4         # polls without growth that end a settle: 2 s at the default poll


def settle(want_kb, timeout, rss_of, poll=0.5, clock=time.monotonic, sleep=time.sleep):
    """True once rss_of() reaches want_kb, or the tree is up and has not grown for LEVEL_POLLS
    polls (the estimate is a mean, a worker may stop below it); False when timeout seconds pass first."""
    end = clock() + timeout
    last, level = 0, 0
    while True:
        rss = rss_of()
        if rss >= want_kb:
            return True
        level = level + 1 if 0 < rss <= last * 1.02 else 0
        if level >= LEVEL_POLLS:
            return True
        last = rss
        if clock() >= end:
            return False
        sleep(poll)


def main(argv):
    if not argv or argv[0] not in ("check", "settle"):
        print("usage: memfloor.py check|settle ...", file=sys.stderr)
        return 2
    opt = dict(zip(argv[1::2], argv[2::2]))
    if argv[0] == "settle":
        if not (opt.get("--pid") or "").isdigit():
            return 0
        rss = boss_worker_rss(opt["--boss"]) if opt.get("--boss") else []
        settle(worker_cost_kb(rss), float(opt.get("--timeout", 30)), lambda: tree_rss_kb(opt["--pid"]))
        return 0
    rss = boss_worker_rss(opt["--boss"]) if opt.get("--boss") else []
    try:
        avail = mem_available_kb(opt.get("--meminfo") or os.environ.get("BOSS_MEMINFO") or "/proc/meminfo")
    except (OSError, ValueError) as e:
        print("not spawning: cannot read MemAvailable (%s)" % e, file=sys.stderr)
        return 1
    msg = refusal(avail, rss)
    if msg:
        print(msg, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
