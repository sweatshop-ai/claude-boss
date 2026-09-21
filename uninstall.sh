#!/usr/bin/env bash
# Remove what install.sh added. Nothing under pm/ is touched: your trackers,
# objectives and markers are state, and they outlive the plugin.
#
#   ./uninstall.sh            remove timers and bin symlinks
#   KEEP_TIMERS=1 ./uninstall.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ -z ${KEEP_TIMERS:-} ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now boss-ladder.timer boss-workers-watch.timer 2>/dev/null || true
  rm -f "$UNITS"/boss-ladder.{service,timer} "$UNITS"/boss-workers-watch.{service,timer}
  systemctl --user daemon-reload
  echo "timers removed"
fi

for f in "$ROOT"/skills/boss/bin/*; do
  link="$HOME/.local/bin/$(basename "$f")"
  [[ -L $link && $(readlink "$link") == "$f" ]] && rm -f "$link" && echo "unlinked $link"
done

cat <<EOF

claude-boss uninstalled.

Left alone on purpose:
  $CFG/pm/           trackers, objectives, markers — your state
  $CFG/routines/     timer state and logs

Remove the plugin itself with Claude Code's own plugin commands; that takes the
hooks with it.
EOF
