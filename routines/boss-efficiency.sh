#!/usr/bin/env bash
# boss-efficiency (body) — fired by boss-efficiency.timer, weekly.
#
# Measures where the time and the tokens of the boss tracks went in the last
# seven days and speaks on Slack only when a track's share moved or the
# measuring itself failed. All the logic is in boss_efficiency_core.py; this
# takes the turn on the transcripts, lowers the priority and keeps a log.
# See boss-efficiency.md.
#
# It reads $CLAUDE_CONFIG_DIR/projects (about 5 GB) and writes only under
# $CLAUDE_CONFIG_DIR/routines/{state,reports,logs}: transcripts name clients and
# the plugin repo is public. No model is called.
#
#   DRY_RUN=1   print the report and what would be alerted, write nothing
#   ARGS        passed on: --end 2026-11-04 --weeks 4 for a backfill
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROUTINES="$CFG/routines"           # the core writes reports and state under the same place
CORE="$HERE/boss_efficiency_core.py"
# One scan of the transcripts at a time: ticket 07's gap scan takes the same lock.
TRANSCRIPTS_LOCK="$CFG/pm/.boss-efficiency-transcripts.lock"
mkdir -p "$ROUTINES/state" "$ROUTINES/logs" "$CFG/pm"
LOG="$ROUTINES/logs/boss-efficiency.log"
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 262144 ]; then
    tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
[ "${DRY_RUN:-}" != 1 ] && exec >> "$LOG" 2>&1

echo "=== run $(date -Is) dry_run=${DRY_RUN:-0} ==="
exec 9>"$TRANSCRIPTS_LOCK"
if ! flock -w "${BOSS_EFFICIENCY_LOCK_WAIT:-7200}" 9; then
    echo "transcripts lock still held after ${BOSS_EFFICIENCY_LOCK_WAIT:-7200} s, run skipped"
    exit 1                     # a week with no measure is a failure the unit shows, not a pass
fi

# nice and ionice: the laptop is shared and the scan is the heaviest thing on it.
timeout -k 30 3600 nice -n 19 ionice -c3 python3 -B "$CORE" "$@"
rc=$?
[ "$rc" -eq 124 ] && echo "TIMED OUT after 3600s"
echo "core exit=$rc"
exit "$rc"
