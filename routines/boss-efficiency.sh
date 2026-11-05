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
#   BOSS_EFFICIENCY_LOCK_WAIT, BOSS_EFFICIENCY_TIMEOUT, BOSS_EFFICIENCY_KILL
#               seconds to wait for the lock (7200), to let the scan run (3600), and to
#               wait after the TERM before the kill (30); the tests shorten them
#   ARGS        passed on: --end 2026-11-04 --weeks 4 for a backfill
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROUTINES="$CFG/routines"           # the core writes reports and state under the same place
CORE="$HERE/boss_efficiency_core.py"
# One scan of the transcripts at a time: ticket 07's gap scan takes the same lock.
TRANSCRIPTS_LOCK="$CFG/pm/.boss-efficiency-transcripts.lock"
LOG="$ROUTINES/logs/boss-efficiency.log"
if [ "${DRY_RUN:-}" != 1 ]; then
    mkdir -p "$ROUTINES/state" "$ROUTINES/logs" "$CFG/pm"
    if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 262144 ]; then
        tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
    exec >> "$LOG" 2>&1
fi

echo "=== run $(date -Is) dry_run=${DRY_RUN:-0} ==="
# A dry run on a machine that never ran the routine has no pm directory: nothing to lock against.
if [ -d "$CFG/pm" ]; then exec 9>"$TRANSCRIPTS_LOCK"; else exec 9>/dev/null; fi
# The week cannot be measured at all: say so on Slack, because the core's own alert never runs. If Slack
# is out too the log says ALERT NOT SENT and the exit is 3, not the 1 or 124 of a miss that was told.
missed() {
    if ! timeout 90 python3 -B "$CORE" --alert "boss-efficiency: $1; no weekly measure this run"; then
        echo "ALERT NOT SENT: $1"
        exit 3
    fi
}

if ! flock -w "${BOSS_EFFICIENCY_LOCK_WAIT:-7200}" 9; then
    echo "transcripts lock still held after ${BOSS_EFFICIENCY_LOCK_WAIT:-7200} s, run skipped"
    missed "transcripts lock still held after ${BOSS_EFFICIENCY_LOCK_WAIT:-7200} s"
    exit 1                     # a week with no measure is a failure the unit shows, not a pass
fi

# nice and ionice: the laptop is shared and the scan is the heaviest thing on it.
# Best-effort class 2 at its lowest priority, not idle (-c3): an idle scan can starve on a busy
# disk and hit the cap below, which loses the week.
CAP="${BOSS_EFFICIENCY_TIMEOUT:-3600}"
timeout -k "${BOSS_EFFICIENCY_KILL:-30}" "$CAP" nice -n 19 ionice -c2 -n7 python3 -B "$CORE" "$@"
rc=$?
if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then      # 137: it ignored the TERM and was killed 30 s later
    echo "TIMED OUT after ${CAP}s"
    missed "scan timed out after ${CAP} s"
fi
echo "core exit=$rc"
exit "$rc"
