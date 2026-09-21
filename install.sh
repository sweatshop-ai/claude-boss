#!/usr/bin/env bash
# Install claude-boss.
#
# The hooks come from hooks/hooks.json and need nothing here — installing the
# plugin registers them. What this script does is the part a plugin cannot:
#
#   1. creates the state directories the boss writes to, under your Claude
#      config dir (pm/ for trackers and markers, routines/ for timer state)
#   2. installs and enables the two systemd user timers, the escalation ladder
#      and the worker watchdog, pointed at this checkout
#   3. optionally symlinks bin/ into ~/.local/bin so `boss-start` and friends
#      are on PATH
#
#   BIN=1      ./install.sh   # also symlink bin/ into ~/.local/bin
#   NO_TIMERS=1 ./install.sh  # skip the systemd timers
#   MIGRATE=1  ./install.sh   # also strip hand-written boss hooks from
#                             # settings.json (for an upgrade from the
#                             # pre-plugin layout; see README)
#
# Everything here is reversible with ./uninstall.sh. Nothing under pm/ is ever
# touched by either script: that is your state, not the plugin's.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

[[ -d $CFG ]] || { echo "No Claude config at $CFG" >&2; exit 1; }

# ---------------------------------------------------------------- 1. state
mkdir -p "$CFG/pm/.boss-sessions" "$CFG/pm/.pulse" \
         "$CFG/routines/state" "$CFG/routines/logs"
echo "state directories ready under $CFG"

# ---------------------------------------------------------------- 2. timers
if [[ -z ${NO_TIMERS:-} ]]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "no systemctl here — skipping the timers." >&2
    echo "  the ladder and the watchdog are optional; the boss works without them," >&2
    echo "  it just stops escalating on a clock and stops noticing a wedged worker." >&2
  else
    mkdir -p "$UNITS"
    for u in boss-ladder.service boss-ladder.timer \
             boss-workers-watch.service boss-workers-watch.timer; do
      sed -e "s|@ROOT@|$ROOT|g" -e "s|@CFG@|$CFG|g" \
          "$ROOT/systemd/$u.in" > "$UNITS/$u"
    done
    systemctl --user daemon-reload
    systemctl --user enable --now boss-ladder.timer boss-workers-watch.timer
    echo "timers enabled: boss-ladder (every 5 min), boss-workers-watch (every min)"
    echo "  they run $ROOT/routines/ — re-run this script if that path moves,"
    echo "  which it does when you upgrade a plugin installed from a marketplace."
  fi
fi

# ------------------------------------------------------------------ 3. bin
if [[ -n ${BIN:-} ]]; then
  mkdir -p "$HOME/.local/bin"
  for f in "$ROOT"/skills/boss/bin/*; do
    ln -sf "$f" "$HOME/.local/bin/$(basename "$f")"
  done
  echo "bin/ symlinked into ~/.local/bin"
fi

# -------------------------------------------------------------- 4. migrate
if [[ -n ${MIGRATE:-} ]]; then
  python3 "$ROOT/scripts/unwire-legacy-hooks.py" "$CFG/settings.json"
fi

cat <<EOF

claude-boss installed from $ROOT

  hooks        from hooks/hooks.json (the plugin registers them; nothing to do)
  state        $CFG/pm/
  timers       $( [[ -n ${NO_TIMERS:-} ]] && echo skipped || echo enabled )

Start a boss with:  $ROOT/skills/boss/bin/boss-start [track]
then type /boss in the session it opens. It must run inside tmux.

Optional, and the boss degrades quietly without each one:
  ~/.config/tiroir/slack.env   escalation alerts   (BOSS_SLACK_ENV to move it)
  ~/.config/tiroir/typesafe.env  the jev experiment  (BOSS_TYPESAFE_ENV)
  a claude-team checkout       the dashboard chime that tells you it is waiting
EOF
