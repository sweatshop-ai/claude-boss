#!/usr/bin/env python3
"""Remove hand-written boss hooks from settings.json, for the plugin migration.

Before claude-boss was a plugin its six hooks were typed into
`~/.claude/settings.json` by hand. Installing the plugin registers the same six
from `hooks/hooks.json`, so leaving the old entries means every hook fires
twice — two guards, two pulses, two reapers.

This removes ONLY entries whose command names one of the boss scripts, leaves
every other hook alone, and writes a timestamped backup first. It prints what
it removed and exits 0 when there was nothing to do.

    python3 scripts/unwire-legacy-hooks.py ~/.claude/settings.json
    python3 scripts/unwire-legacy-hooks.py --dry-run ~/.claude/settings.json
"""
import json
import shutil
import sys
import time
from pathlib import Path

# The scripts this plugin owns. An entry is ours only if its command names one.
OURS = ("boss-guard.py", "boss-pulse.py", "boss-compact.py",
        "boss-jev.py", "boss-reap.py")


def is_ours(hook):
    cmd = hook.get("command") or ""
    # A plugin-root command is already the plugin's own; leave it be.
    if "CLAUDE_PLUGIN_ROOT" in cmd:
        return False
    return any(name in cmd for name in OURS)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dry = "--dry-run" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    path = Path(args[0]).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("cannot read %s: %s" % (path, exc), file=sys.stderr)
        return 1

    removed = []
    hooks = data.get("hooks") or {}
    for event, groups in list(hooks.items()):
        kept_groups = []
        for group in groups:
            kept = [h for h in group.get("hooks", []) if not is_ours(h)]
            gone = [h for h in group.get("hooks", []) if is_ours(h)]
            removed += [(event, h.get("command")) for h in gone]
            if kept:
                group["hooks"] = kept
                kept_groups.append(group)
            elif not gone:
                kept_groups.append(group)      # empty group that was not ours
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]

    if not removed:
        print("nothing to unwire — no hand-written boss hooks in %s" % path)
        return 0

    for event, cmd in removed:
        print("%s %s: %s" % ("would remove" if dry else "removed", event, cmd))
    if dry:
        return 0

    backup = path.with_suffix(".json.bak-%s" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("backup: %s" % backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
