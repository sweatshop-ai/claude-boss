#!/usr/bin/env bash
# boss-ladder (body) — fired by boss-ladder.timer every 5 minutes.
#
# Posts the escalation rungs that have come due on tracker blocker lines, so the
# ladder climbs without a boss turn. All the logic is in boss_ladder_core.py;
# this sets the environment, writes a run header, and keeps one run at a time.
# See boss-ladder.md.
#
# Silent on Slack unless a rung is actually due. It reads only ~/.claude/pm and
# posts only through boss-alert; it touches no device and no remote host.
#
#   DRY_RUN=1   print what would be posted, post nothing, write nothing
set -uo pipefail

# Code sits beside this script (the plugin); state and logs live in the Claude
# config dir, because they are state and survive a plugin reinstall.
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROUTINES="${BOSS_ROUTINE_STATE:-$CFG/routines}"
CORE="$HERE/boss_ladder_core.py"
LOCK="$ROUTINES/state/boss-ladder.run.lock"
mkdir -p "$ROUTINES/state" "$ROUTINES/logs"

echo "=== run $(date -Is) dry_run=${DRY_RUN:-0} ==="

# A 5-minute timer and a Slack call that can hang: without this, a wedged run
# and its successor both walk the same trackers.
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "another boss-ladder run holds the lock, skipping"
    exit 0
fi

timeout 120 python3 "$CORE"
rc=$?
[ "$rc" -eq 124 ] && echo "TIMED OUT after 120s"
echo "core exit=$rc"
exit "$rc"
