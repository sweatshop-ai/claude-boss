#!/usr/bin/env python3
"""version_gap — is the claude-boss this machine runs the one that was released?

Three versions can differ, and the number in the install record shows only one:

  released   `version` in .claude-plugin/plugin.json on the plugin repo's main.
             Every merge there bumps it, so that file is the release; the repo's
             tags stopped at v0.5.0 and say nothing.
  installed  plugins/installed_plugins.json, the version Claude Code will load
             into the NEXT session. A third-party marketplace is not refreshed
             on its own, so this moves only when somebody updates it (measured
             2026-11-04: 0.19.1 sat there for three days while 0.19.3 and 0.20.0
             were released, then jumped to 0.21.0 in one update).
  running    a live session loaded its plugin at start and keeps it. Claude Code
             marks each version directory in use with plugins/cache/.../<version>/
             .in_use/<pid>; a pid still alive is a session on that version. The
             same sessions also carry the old `bin/` on PATH, ahead of the new one.

Prints one line per gap and nothing when all three agree. The released version is
read from GitHub at most once per CACHE_TTL; offline it is simply unknown, and
that is silent. Exit 0 always: a report, not a gate.

Run: python3 skills/boss/version_gap.py        (or `boss-version-gap`)
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402

PLUGIN = "claude-boss"
RELEASED_URL = ("https://raw.githubusercontent.com/sweatshop-ai/claude-boss/"
                "main/.claude-plugin/plugin.json")
CACHE_TTL = 6 * 3600


def vkey(v):
    """Sortable form of a version: '0.19.2' -> (0, 19, 2); junk sorts lowest."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) if nums else (-1,)


def installed(cfg=None):
    """(version, install path) of the user-scope install record, or (None, None)."""
    rec = boss_store.config_dir(cfg) / "plugins" / "installed_plugins.json"
    try:
        plugins = json.loads(rec.read_text()).get("plugins", {})
    except (OSError, ValueError):
        return None, None
    for key, entries in plugins.items():
        if key.split("@")[0] == PLUGIN and entries:
            return entries[0].get("version"), entries[0].get("installPath")
    return None, None


def running(cfg=None):
    """{version: [live pids]} from the .in_use markers under the plugin cache."""
    out = {}
    for mark in (boss_store.config_dir(cfg) / "plugins" / "cache").glob(
            f"*/{PLUGIN}/*/.in_use/*"):
        if mark.name.isdigit() and Path("/proc", mark.name).exists():
            out.setdefault(mark.parent.parent.name, []).append(int(mark.name))
    return out


def released(cfg=None, fetch=None, now=None):
    """The released version, from the cache when it is fresh, else GitHub; None when unknown."""
    now = time.time() if now is None else now
    cache = boss_store.state_dir(cfg) / "version-gap.json"
    try:
        seen = json.loads(cache.read_text())
        if now - seen["at"] < CACHE_TTL:
            return seen["version"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        version = (fetch or _fetch)()
    except Exception:
        return None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"at": now, "version": version}))
    except OSError:
        pass
    return version


def _fetch():
    with urllib.request.urlopen(RELEASED_URL, timeout=3) as r:
        return json.load(r)["version"]


def gaps(cfg=None, fetch=None, now=None):
    """The lines to show; empty when installed, released and running agree."""
    inst, _ = installed(cfg)
    rel = released(cfg, fetch, now)
    lines = []
    if inst and rel and vkey(inst) < vkey(rel):
        lines.append(f"claude-boss {inst} is installed, {rel} is released: "
                     f"update the plugin, then restart the sessions that matter.")
    newest = max([v for v in (inst, rel) if v], key=vkey, default=None)
    old = {v: p for v, p in running(cfg).items() if newest and vkey(v) < vkey(newest)}
    if old:
        n = sum(len(p) for p in old.values())
        lines.append(f"{n} live session(s) still run an older claude-boss "
                     f"({', '.join(sorted(old, key=vkey))}) than {newest}; their "
                     f"rules and their `bin/` on PATH are the old ones until they restart.")
    return lines


def main():
    for line in gaps():
        print("version gap: " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
