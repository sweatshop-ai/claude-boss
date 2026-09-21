#!/usr/bin/env python3
"""PreToolUse guard for boss sessions — warns and logs, never denies.

The boss skill has carried three pages of bold FORBIDDEN prose telling the
coordinator not to implement. Measured across 15 boss sessions it did not work:
983 Bash calls of which 35 were the lifecycle script, 238 Edits, 47 Writes, and
real source files changed. Prose that long stops reading as a rule.

A hard deny was the obvious fix and is the wrong one. The boss legitimately
needs `gh` for the board, the tracker wrapper, the alert wrapper, background
`sleep` for escalation timers, and — once the skill is split — its own
references/ files. Worse, a hook that misfires leaves the boss unable to inspect
the failure, and only the owner can unstick it from outside.

So this warns and records. The log is the thing the prose never produced:
evidence of which calls actually happen, so a later allowlist can be built from
data instead of imagination.

Active only for sessions that registered themselves as a boss:
    ~/.claude/pm/.boss-sessions/<session_id>
"""
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
MARKERS = CFG / "pm" / ".boss-sessions"
LOG = CFG / "pm" / "boss-guard.log"
STATE = CFG / "pm" / ".pulse"

# Commands a coordinator genuinely runs. Everything else is a worker's job.
#
# Measured on pm/boss-guard.log 2026-09-20: 1,227 of 2,589 firings named one of
# these. `boss-goal`, `boss-start` and `team-line` were missing outright, and the
# rest arrived behind a `cd X &&` or `VAR=...` prefix that defeated a match
# anchored at position 0. Half the guard's volume was the boss being told off
# for running the boss's own commands — team-line most of all, which the harness
# instructs every session to run at the end of every turn.
ALLOWED_CMD = re.compile(
    r"^\s*(?:"
    r"(?:\S*/)?boss-lifecycle\.sh|"
    r"(?:\S*/)?boss-tracker|"
    r"(?:\S*/)?boss-alert|"
    r"(?:\S*/)?boss-goal|"
    r"(?:\S*/)?boss-start|"
    r"(?:\S*/)?boss-panes\.py|"
    r"(?:\S*/)?boss-run\b|"
    r"(?:\S*/)?team-line\b|"
    r"gh\b|"
    r"sleep\b|"
    r"date\b|"
    r"tmux\b"
    r")")

# `cd somewhere &&` and leading `VAR=value` assignments are shell throat-clearing,
# not the command. Strip them and the real head is what follows. Only a leading
# `cd` counts: `npm run build && cd x` is still a build.
PREFIX = re.compile(r"^\s*(?:cd\s+[^\s;&|]+\s*(?:&&|;)\s*|[A-Za-z_][A-Za-z0-9_]*=\S*\s*[;]?\s*)")


def strip_prefix(cmd, limit=6):
    """`cd /repo && B=bin; $B/boss-goal next` -> `$B/boss-goal next`."""
    for _ in range(limit):
        m = PREFIX.match(cmd)
        if not m or not m.group(0).strip():
            break
        cmd = cmd[m.end():]
    return cmd

# Paths the boss owns outright: its own state, and its own code.
#
# This was keyed to a literal `/.claude/skills/boss/`, which stopped being the
# boss's home when it became a plugin. Both halves are now computed, so the
# boundary follows the install rather than a string that used to be true. The
# literal `/.claude/pm/` stays as well, because a boss often writes the path in
# tilde or relative form and the resolved prefix would miss it.
PLUGIN = Path(os.environ.get("CLAUDE_PLUGIN_ROOT",
                             str(Path(__file__).resolve().parent.parent.parent)))
OWNED = (str(CFG / "pm"), str(PLUGIN))
LOOSE = re.compile(r"/\.claude/pm/")


def owns(path):
    p = str(path)
    return p.startswith(OWNED) or bool(LOOSE.search(p))

WATCHED = {"Bash", "Edit", "Write", "NotebookEdit", "Read", "Glob", "Grep"}


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def bump(sid):
    """Count this firing against the session. Returns the new total.

    Measured on pm/boss-guard.log 2026-09-20: 2,589 firings across 21 sessions
    in 14 days, one of them 725 on its own. The hook said the same 330-character
    sentence every time — about 215,000 tokens, of which everything after the
    first carried no information. The count is what carries information after
    that, so keep it per session and let main() decide when to speak.
    """
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / ("%s.guard.json" % sid)
    try:
        fh = f.open("r+", encoding="utf-8")
    except OSError:
        try:
            fh = f.open("w+", encoding="utf-8")
        except OSError:
            return 1                  # unwritable state: behave as first firing
    with fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                st = json.loads(fh.read() or "{}")
            except ValueError:
                st = {}
            n = int(st.get("n") or 0) + 1
            st["n"] = n
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(st))
        except OSError:
            return 1
    return n


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    sid = payload.get("session_id") or ""
    if not sid or not (MARKERS / sid).exists():
        return 0                      # not a boss session; nothing to say

    tool = payload.get("tool_name") or ""
    if tool not in WATCHED:
        return 0
    ti = payload.get("tool_input") or {}

    detail = ""
    if tool == "Bash":
        cmd = (ti.get("command") or "").strip()
        if ALLOWED_CMD.match(cmd) or ALLOWED_CMD.match(strip_prefix(cmd)):
            return 0
        detail = cmd[:200]
    else:
        fp = ti.get("file_path") or ti.get("path") or ti.get("pattern") or ""
        if owns(fp):
            return 0
        detail = str(fp)[:200]

    try:
        MARKERS.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session": sid,
                "tool": tool,
                "detail": detail,
            }) + "\n")
    except OSError:
        pass

    n = bump(sid)
    if n == 1:
        msg = (f"Boss guard: this session is coordinating, and {tool} on "
               f"`{detail[:90]}` is implementation work. Dispatch it to a worker "
               f"instead. (Not blocked, and recorded in pm/boss-guard.log — if this "
               f"really is coordination, say so and carry on.)")
    elif n & (n - 1) == 0:
        # Powers of two. Repeating the sentence says nothing; the running total
        # does, and it grows louder exactly as the problem does. Across the 21
        # logged sessions this speaks 137 times instead of 2,589.
        msg = (f"Boss guard: {tool} on `{detail[:60]}` — your {ordinal(n)} "
               f"implementation-shaped call this session. Dispatch, or say why not.")
    else:
        return 0                      # logged, not spoken
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
