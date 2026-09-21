#!/usr/bin/env bash
# boss-workers-watch (body) — fired by boss-workers-watch.timer, every minute.
#
# External watchdog for Claude sessions running in tmux panes (boss + workers).
# The /boss skill's Phase D is deliberately event-driven: a worker that dies on
# an API error emits no event, so nothing re-invokes the boss — and after a
# blackout the boss is usually frozen on the same error. So this check lives
# OUTSIDE Claude entirely: pure bash + tmux, no LLM anywhere in the detection
# path, because the failure it exists to catch is "the Claude API is down".
#
# Detects, per claude/node pane (last 40 visible lines):
#   api-error          error banner, not retrying        → alert after 2 runs
#   api-retrying       auto-retry in progress            → alert after 5 runs
#   permission-prompt  a tool-permission dialog waiting  → alert after 2 runs
#   frozen             "esc to interrupt" shown but pane
#                      content identical across runs     → alert after 3 runs
#   at-shell           a pane with @worker_name back at
#                      a shell (crashed or retired)      → alert after 2 runs
#
# Alerts once per pane+condition (Slack #claude-ops + desktop notify-send, the
# latter works even with no internet), posts a recovery note when it clears.
# Silent and cheap on the healthy path. See boss-workers-watch.md.
#
# Test hooks — the alerting path must be exercisable without a real incident:
#   DRY_RUN=1            print what would be sent, send nothing; state is
#                        written only if WATCH_STATE_DIR is also overridden
#   WATCH_STATE_DIR=<d>  use a scratch state dir (lets tests exercise the
#                        consecutive-run counters without touching real state)
#   FAKE_PANES=<file>    substitute `tmux list-panes` output (same TSV fields)
#   FAKE_CAP_DIR=<dir>   substitute captures: <dir>/<pane-id-without-%>.txt
set -uo pipefail

DRY_RUN="${DRY_RUN:-}"
FAKE_PANES="${FAKE_PANES:-}"
FAKE_CAP_DIR="${FAKE_CAP_DIR:-}"

# Code sits beside this script (the plugin); state and logs are state, so they
# stay in the Claude config dir and survive a plugin reinstall.
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROUTINES="${BOSS_ROUTINE_STATE:-$CFG/routines}"
STATE_DIR="${WATCH_STATE_DIR:-$ROUTINES/state}"
STATE="$STATE_DIR/boss-workers-watch.state"    # pane <TAB> cond <TAB> count <TAB> alerted
HASHES="$STATE_DIR/boss-workers-watch.hashes"  # pane <TAB> md5-of-capture
LOG="$ROUTINES/logs/boss-workers-watch.log"
mkdir -p "$STATE_DIR" "$ROUTINES/logs"
touch "$STATE" "$HASHES"

# A per-minute watchdog must keep its own log bounded.
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 524288 ]; then
    tail -n 300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
[ -z "$DRY_RUN" ] && exec >> "$LOG" 2>&1

panes_list() {
    if [ -n "$FAKE_PANES" ]; then cat "$FAKE_PANES"; return; fi
    tmux list-panes -a \
        -F $'#{pane_id}\t#{pane_index}\t#{pane_current_command}\t#{pane_current_path}\t#{@worker_name}' \
        2>/dev/null
}

capture() {
    if [ -n "$FAKE_CAP_DIR" ]; then cat "$FAKE_CAP_DIR/${1#%}.txt" 2>/dev/null; return; fi
    tmux capture-pane -p -t "$1" -S -40 2>/dev/null
}

threshold_for() {
    case "$1" in
        api-retrying) echo 5 ;;   # auto-retry usually heals; only a storm matters
        frozen)       echo 3 ;;
        *)            echo 2 ;;   # one noisy sample is not an incident
    esac
}

PANES=$(panes_list)
if [ -z "$PANES" ]; then
    # No tmux server (or nothing running) — nothing to watch, stay silent.
    exit 0
fi

NEW_STATE=""
NEW_HASHES=""
ALERTS=""
RECOVERIES=""

while IFS=$'\t' read -r id idx cmd path name; do
    [ -n "$id" ] || continue
    cond="none"

    if [[ "$cmd" =~ ^(claude|node)$ ]]; then
        cap=$(capture "$id")
        hash=$(printf '%s' "$cap" | md5sum | cut -d' ' -f1)
        prev_hash=$(awk -F'\t' -v p="$id" '$1==p{print $2}' "$HASHES")
        NEW_HASHES+="$id"$'\t'"$hash"$'\n'

        # Case-sensitive on purpose: the TUI banner says "API Error"; a
        # transcribed conversation about "an API error" (lowercase) must not
        # trigger. Screen-scraping can never be perfect — a chat quoting the
        # exact banner still matches — but the damage is bounded: one
        # aggregated alert per pane+condition, then silence.
        if grep -qE 'Retrying in [0-9]+' <<<"$cap"; then
            cond="api-retrying"
        elif grep -qE 'API Error|overloaded_error|rate_limit_error|Request timed out|Connection (error|failed|refused)|fetch failed|ECONNREFUSED|OAuth token has expired' <<<"$cap"; then
            cond="api-error"
        elif grep -qE 'Do you want to (proceed|allow|make this edit|create|run)|❯ 1\. Yes' <<<"$cap"; then
            cond="permission-prompt"
        elif grep -qE 'esc to interrupt' <<<"$cap" && [ -n "$prev_hash" ] && [ "$hash" = "$prev_hash" ]; then
            # Mid-turn the TUI spinner redraws constantly; identical content
            # across whole runs means the session is wedged, not thinking.
            cond="frozen"
        fi
    elif [ -n "$name" ] && [[ "$cmd" =~ ^(bash|zsh|fish|sh|dash)$ ]]; then
        # A named worker pane back at a shell: crashed, or retired without
        # cleanup. Worth one alert either way; the boss knows which it was.
        cond="at-shell"
    fi

    prev_line=$(awk -F'\t' -v p="$id" '$1==p{print; exit}' "$STATE")
    prev_cond=$(cut -f2 <<<"$prev_line")
    prev_count=$(cut -f3 <<<"$prev_line")
    prev_alerted=$(cut -f4 <<<"$prev_line")
    label="pane $idx${name:+ ($name)} — ${path##*/}"

    if [ "$cond" = "none" ]; then
        if [ "${prev_alerted:-0}" = "1" ]; then
            RECOVERIES+="• $label: recovered (was ${prev_cond})"$'\n'
        fi
        continue  # no state line kept for healthy panes
    fi

    if [ "$cond" = "${prev_cond:-}" ]; then
        count=$(( ${prev_count:-0} + 1 ))
        alerted="${prev_alerted:-0}"
    else
        count=1
        alerted=0
    fi

    if [ "$alerted" = "0" ] && [ "$count" -ge "$(threshold_for "$cond")" ]; then
        detail=$(grep -E 'API Error|overloaded_error|rate_limit_error|Retrying in|Request timed out|Connection|Do you want' \
                 <<<"$(capture "$id")" | tail -2 | sed 's/^[[:space:]]*//')
        ALERTS+="• $label: *${cond}* (${count} min)${detail:+ — ${detail}}"$'\n'
        alerted=1
    fi
    NEW_STATE+="$id"$'\t'"$cond"$'\t'"$count"$'\t'"$alerted"$'\n'
done <<<"$PANES"

notify() {  # $1=text (Slack mrkdwn)
    if [ -n "$DRY_RUN" ]; then
        printf 'DRY_RUN: would notify:\n%s\n' "$1"
        return
    fi
    # Desktop first: it works even when the network (and Slack) is down,
    # which is exactly the blackout scenario this watchdog exists for.
    notify-send -u critical "Claude workers watch" "$(sed 's/\*//g' <<<"$1")" 2>/dev/null || true
    if [ -f "${BOSS_SLACK_ENV:-$HOME/.config/tiroir/slack.env}" ]; then
        # shellcheck disable=SC1091
        source "${BOSS_SLACK_ENV:-$HOME/.config/tiroir/slack.env}"
        payload=$(python3 -c 'import json,sys; print(json.dumps({"channel": sys.argv[1], "text": sys.argv[2]}))' \
                  "$SLACK_CHANNEL_ID" "$1")
        curl -s --max-time 10 -X POST https://slack.com/api/chat.postMessage \
            -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            -H 'Content-type: application/json' \
            -d "$payload" > /dev/null || true
    fi
}

if [ -n "$ALERTS" ]; then
    echo "=== $(date -Is) alerting ==="
    printf '%s' "$ALERTS"
    notify ":rotating_light: Claude worker sessions need attention:"$'\n'"$ALERTS"
fi
if [ -n "$RECOVERIES" ]; then
    echo "=== $(date -Is) recovered ==="
    printf '%s' "$RECOVERIES"
    notify ":white_check_mark: Claude worker sessions recovered:"$'\n'"$RECOVERIES"
fi

# DRY_RUN must not advance the real counters (it would mark conditions as
# alerted without anyone having been told) — but with a scratch state dir the
# write is exactly what lets a test exercise the consecutive-run logic.
if [ -z "$DRY_RUN" ] || [ -n "${WATCH_STATE_DIR:-}" ]; then
    printf '%s' "$NEW_STATE"  > "$STATE"
    printf '%s' "$NEW_HASHES" > "$HASHES"
fi

# Reap the per-session state of sessions that are gone. The SessionEnd hook
# does this for an orderly exit; a crash leaves no SessionEnd, which is why the
# sweep exists here as well. boss-reap.py only ever removes a file whose NAME
# carries a session UUID, and spares anything touched in the last 30 minutes,
# so jev.mode and a session that has only just started are both safe.
BOSS_REAP="${BOSS_REAP:-$HERE/../skills/boss/boss-reap.py}"
if [ -x "$BOSS_REAP" ]; then
    reaped=$(python3 "$BOSS_REAP" --sweep ${DRY_RUN:+--dry-run} 2>&1) || true
    [ -n "$reaped" ] && { echo "=== $(date -Is) reaped stale boss state ==="; printf '%s\n' "$reaped"; }
fi
exit 0
