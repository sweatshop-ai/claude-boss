#!/usr/bin/env python3
"""The memory floor: a spawn must leave policy.MEMORY_FLOOR_GB of MemAvailable free.

    memfloor.py check [--boss PANE] [--meminfo FILE]

Exit 0 when the new worker fits, 1 with the refusal on stderr when it would
not. The new worker is estimated as the mean resident size of the boss's
current workers, at least policy.WORKER_MIN_GB. BOSS_MEMINFO names another
meminfo file (tests). boss-lifecycle.sh spawn runs it.
"""
import os
import sys
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


def _rss_kb(pid):
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
    rss = (_rss_kb(s.session.get("pid")) for s in fleet.workers(seats, boss_pane) if s.session)
    return [r for r in rss if r]


def main(argv):
    if not argv or argv[0] != "check":
        print("usage: memfloor.py check [--boss PANE] [--meminfo FILE]", file=sys.stderr)
        return 2
    opt = dict(zip(argv[1::2], argv[2::2]))
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
