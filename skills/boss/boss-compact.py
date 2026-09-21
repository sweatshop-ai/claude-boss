#!/usr/bin/env python3
"""Compaction hooks for boss sessions — the boss compacts, so make it survivable.

A boss runs with --autocompact 450k (bin/boss-start). Compaction summarises;
what the summary drops is gone. Two events let us steer that:

  PreCompact               Nothing useful to say. This hook used to emit an
                           additionalContext hint; PreCompact does not accept
                           hookSpecificOutput at all, so every compaction failed
                           validation with "expected one of PreToolUse |
                           UserPromptSubmit | ...". It now stays silent. Only
                           the top-level fields (continue, suppressOutput,
                           stopReason, decision, reason, systemMessage) are
                           legal here, and none of them carry context.
  SessionStart (compact)   Fires after the compaction, and its output is
                           injected into the fresh context. This is the one we
                           rely on: the tracker's live state comes back
                           verbatim, plus the order to redo the session ritual.

The tracker was designed for exactly this ("live state small, history
archived", capped at 15 KB). It is the boss's memory on disk; the summary is
allowed to be lossy because this hook is not.

Active only for sessions registered as a boss, with a track name in the marker:
    ~/.claude/pm/.boss-sessions/<session_id>   contains <track>
(SKILL.md session start, step 2, writes it.) Any other session: silent exit 0.
"""
import json
import os
import sys
from pathlib import Path

CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
PM = CFG / "pm"
MARKERS = PM / ".boss-sessions"
CAP = 15360   # boss-tracker's cap; anything past it is history we do not inject

RESTORE_HEAD = (
    "You are a /boss session that was just compacted (track `{track}`). The "
    "compaction summary is lossy; the two files below are not. Treat them as the "
    "authority on what you are for, and on roster, blockers and decisions. Then "
    "redo the session-start ritual before acting: `boss-lifecycle.sh list "
    "--mine`, then plain `list` for anything unowned. Any blocker listed under Open blockers is "
    "still live — resume its escalation ladder from the T+0 recorded there, do "
    "not restart it at zero. Do not re-dispatch anything listed as in flight.\n\n"
)

GOAL_HEAD = "--- ~/.claude/pm/{track}.goal.md (the objective — this is what you are for) ---\n"
LIVE_HEAD = "\n--- ~/.claude/pm/{track}.md (live state) ---\n"


def track_for(sid):
    if not sid:
        return None
    m = MARKERS / sid
    if not m.is_file():
        return None
    try:
        t = m.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    return t[0].strip() if t and t[0].strip() else None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    track = track_for(payload.get("session_id") or "")
    if not track:
        return 0                               # not a boss, or no track claimed yet

    event = payload.get("hook_event_name") or ""

    if event == "PreCompact":
        # Silent by design. PreCompact accepts no hookSpecificOutput, so the
        # hint this used to print was rejected on every compaction and steered
        # nothing. The SessionStart branch below is what actually restores the
        # boss, and it runs after the summary rather than trying to shape it.
        return 0

    if event == "SessionStart":
        # The field is `source` — verified against the hooks reference, where
        # SessionStart matches on startup|resume|clear|compact|fork. This read
        # `trigger` before, which is never present, so the condition was always
        # false and nothing was injected after a compaction: a silent failure
        # that looked exactly like a hook that had run and found nothing to do.
        # `trigger` is still accepted in case the name ever moves back. When
        # neither key is present we proceed, because settings.json gates this
        # hook with matcher "compact" already.
        why = payload.get("source") or payload.get("trigger") or ""
        if why and why != "compact":
            return 0
        live = PM / f"{track}.md"
        try:
            body = live.read_text(encoding="utf-8")
        except OSError:
            body = f"(tracker {live} could not be read — run boss-tracker show {track})"
        if len(body.encode("utf-8")) > CAP:
            body = body.encode("utf-8")[:CAP].decode("utf-8", "ignore") + (
                f"\n\n[truncated at {CAP} B — the tracker is over its cap; "
                f"run boss-tracker archive {track} after this]")

        # The objective first. A compaction summary reliably keeps the recent
        # tactical thread and drops the standing outcome, which is the wrong way
        # round: the thread can be rebuilt from the tracker, the outcome cannot.
        try:
            goal = (PM / f"{track}.goal.md").read_text(encoding="utf-8")
        except OSError:
            goal = (f"(no objective file for {track} — run `boss-goal init {track}` "
                    f"and fill it in before dispatching anything else)")

        out = (RESTORE_HEAD.format(track=track)
               + GOAL_HEAD.format(track=track) + goal
               + LIVE_HEAD.format(track=track) + body)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": out,
        }}))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
