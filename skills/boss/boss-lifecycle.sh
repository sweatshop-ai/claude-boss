#!/usr/bin/env bash
# boss-lifecycle.sh — tmux process lifecycle for /boss workers.
#
# tmux is used here for ONE thing only: talking to a SHELL PROMPT
# (spawn / retire / restart / move a worker session). That has always been
# reliable. All conversational coordination — dispatch, questions, status,
# reports — goes through SendMessage/ListAgents, never through this script.
#
# Usage:
#   boss-lifecycle.sh spawn <project-dir> [name-hint] [--model <name>]
#   boss-lifecycle.sh claim <pane-id> [name]
#   boss-lifecycle.sh retire <pane-id> [--kill] [--require-idle [--expect-session S] [--expect-last U]]
#   boss-lifecycle.sh restart <pane-id> [--require-idle [--expect-session S] [--expect-last U]]
#   boss-lifecycle.sh move <pane-id> <new-project-dir>
#   boss-lifecycle.sh list [--mine]
#
# OWNERSHIP — several bosses run in parallel on this machine.
# tmux is global: `list-panes -a` sees every pane in every session, and a %N
# target resolves across sessions, so without a marker one boss can retire,
# restart or kill another boss's workers (or the other boss) by pane id alone.
# So every pane this script touches is stamped with `@boss_pane` = the pane id
# of the boss that owns it, the boss stamps its own pane on every invocation,
# and destructive commands refuse a pane owned by somebody else. Pass --force
# (anywhere in the arguments) for a deliberate takeover.
# A pane with NO `@boss_pane` is unowned, not protected: pre-existing sessions
# stay operable, and `claim` is how a boss takes responsibility for one.

set -euo pipefail

CLAUDE_CMD="${BOSS_CLAUDE_CMD:-claude}"
WORKER_MODEL_DEFAULT="${BOSS_WORKER_MODEL:-opus}"    # see launch_claude
# xhigh for agentic coding (the owner, 2026-09-08: the result matters more than
# the spend). Pinned here so a worker does not depend on the global effortLevel.
WORKER_EFFORT_DEFAULT="${BOSS_WORKER_EFFORT:-xhigh}"
BOSS_PANE="${TMUX_PANE:-}"
SHELL_CMDS='^(bash|zsh|fish|sh|dash)$'

# --force and --model <name> may appear anywhere; strip them before the
# subcommand sees the args. MODEL selects the model the worker runs on:
# see "Choosing a worker's model" in SKILL.md — the criterion is NOT task size.
# --require-idle, --expect-session <id> and --expect-last <uuid> are the
# boss-jev restart path (see retire_require_idle); --force does not relax them.
FORCE=""
MODEL=""
REQUIRE_IDLE=""
EXPECT_SESSION=""
EXPECT_LAST=""
_args=()
_want=""
for _a in "$@"; do
  if [[ -n "$_want" ]]; then printf -v "$_want" '%s' "$_a"; _want=""
  elif [[ "$_a" == "--force" ]]; then FORCE=1
  elif [[ "$_a" == "--require-idle" ]]; then REQUIRE_IDLE=1
  elif [[ "$_a" == "--model" ]]; then _want=MODEL
  elif [[ "$_a" == --model=* ]]; then MODEL="${_a#--model=}"
  elif [[ "$_a" == "--expect-session" ]]; then _want=EXPECT_SESSION
  elif [[ "$_a" == "--expect-last" ]]; then _want=EXPECT_LAST
  else _args+=("$_a"); fi
done
if [[ -n "$_want" ]]; then printf '%s\n' "an option needs a value" >&2; exit 1; fi
if [[ -z "$REQUIRE_IDLE" && ( -n "$EXPECT_SESSION" || -n "$EXPECT_LAST" ) ]]; then
  printf '%s\n' "--expect-session / --expect-last only apply with --require-idle" >&2; exit 1
fi
set -- ${_args[@]+"${_args[@]}"}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

pane_prop() { tmux display-message -p -t "$1" "$2"; }

pane_owner() { pane_prop "$1" '#{@boss_pane}' 2>/dev/null || true; }

PANES_PY="$(dirname "${BASH_SOURCE[0]}")/boss-panes.py"

# A worker has ONE name: the one the claude-agent-names plugin gave it, which is
# also what ListAgents shows and SendMessage resolves. This script used to keep a
# second name in @worker_name and the skill carried a page of prose about
# reconciling the two when they disagreed. They cannot disagree now: @worker_name
# is a mirror the watchdog reads, and the plugin is the store.
agent_name() { python3 "$PANES_PY" "$1" 2>/dev/null | cut -f2; }
agent_status() { python3 "$PANES_PY" "$1" 2>/dev/null | cut -f4; }
set_agent_name() { python3 "$PANES_PY" --set-name "$1" "$2" 2>/dev/null || true; }

# Mirror the plugin's name onto the pane. The boss-workers-watch routine only
# reports a crashed worker for panes carrying @worker_name, so an unmirrored
# pane is invisible to the watchdog.
mirror_name() {
  local pane=$1 n
  n=$(agent_name "$pane")
  [[ -n "$n" && "$n" != "-" ]] || return 0
  tmux set-option -p -t "$pane" @worker_name "$n"
  tmux set-option -p -t "$pane" @custom_title "$n — $(basename "$(pane_prop "$pane" '#{pane_current_path}')")"
  printf '%s' "$n"
}

# Refuse to stop a session mid-turn. retire sends Escape Escape /exit, which
# against a running turn aborts live work — the tool call it was waiting on is
# lost and nothing records that it happened. `busy` in the session's own peer
# file is the safe-point signal.
assert_not_busy() {
  local pane=$1 st
  st=$(agent_status "$pane")
  [[ "$st" == "busy" ]] || return 0
  [[ -n "$FORCE" ]] && { printf 'WARN: --force: stopping %s while it is BUSY; its in-flight turn is lost\n' "$pane" >&2; return 0; }
  die "$pane is BUSY — a turn is in flight and stopping it now aborts that work.
  Wait for it to go idle, or ask it to reach a stopping point first.
  Pass --force only if the owner has said to interrupt it."
}

# Mark this boss's own pane as owned-by-itself, so a PEER boss's resolve_pane
# refuses it too — otherwise the guard would protect workers but not bosses.
# Runs on every invocation, so a boss claims itself by doing anything at all.
self_register() {
  [[ -n "$BOSS_PANE" ]] || return 0
  tmux set-option -p -t "$BOSS_PANE" @boss_pane "$BOSS_PANE" 2>/dev/null || true
}

claim_pane() {
  tmux set-option -p -t "$1" @boss_pane "$BOSS_PANE"
}

# tmux exits 0 with empty output for a nonexistent %N target, which would
# silently fall through to the current pane — so require a real %<digits> back.
resolve_pane() {
  local target=$1 id owner
  id=$(pane_prop "$target" '#{pane_id}' 2>/dev/null) || true
  [[ "$id" =~ ^%[0-9]+$ ]] || die "no such pane: $target"
  [[ -n "$BOSS_PANE" && "$id" == "$BOSS_PANE" ]] && die "refusing to operate on the boss's own pane ($id)"

  # Cross-boss guard. Empty owner = unowned, allowed (adoption still works).
  owner=$(pane_owner "$id")
  if [[ -n "$owner" && -n "$BOSS_PANE" && "$owner" != "$BOSS_PANE" ]]; then
    if [[ -z "$FORCE" ]]; then
      die "$id belongs to another boss (pane $owner), not you ($BOSS_PANE).
  Its own boss is managing it and expects it to stay put; retiring or killing it
  destroys that session's context silently. Ask the owner, or pass --force if they
  has told you to take it over."
    fi
    printf 'WARN: --force: operating on %s, owned by another boss (pane %s)\n' "$id" "$owner" >&2
  fi
  printf '%s' "$id"
}

# wait_for_cmd <pane> <regex> <seconds> — poll pane_current_command
wait_for_cmd() {
  local pane=$1 want=$2 secs=$3 i
  for ((i = 0; i < secs; i++)); do
    [[ $(pane_prop "$pane" '#{pane_current_command}') =~ $want ]] && return 0
    sleep 1
  done
  return 1
}

# last resort only: confirm a shell prompt is actually drawn
prompt_visible() {
  tmux capture-pane -t "$1" -p -S -3 | grep -qE '[❯\$#>] *$'
}

launch_claude() {
  local pane=$1 dir=$2
  local cmd="$CLAUDE_CMD"
  # A worker's model is recorded on the pane so `list` shows it and a restart
  # keeps it: a worker silently downgraded on restart is worse than one that
  # was never downgraded.
  local m="${MODEL:-$(pane_prop "$pane" '#{@worker_model}' 2>/dev/null || true)}"
  # No model asked for and none stamped: a worker runs on Opus, whatever the
  # global `model` setting says. /model writes that setting for every new
  # session, so a boss moved to Fable would otherwise drag every worker along
  # at twice the output price (2026-09-08). Override per spawn with --model,
  # or for the machine with BOSS_WORKER_MODEL.
  m="${m:-$WORKER_MODEL_DEFAULT}"
  cmd="$cmd --model ${m@Q} --effort ${WORKER_EFFORT_DEFAULT@Q}"
  tmux send-keys -t "$pane" "cd ${dir@Q}" Enter
  sleep 1
  tmux send-keys -t "$pane" "$cmd" Enter
  wait_for_cmd "$pane" '^(claude|node)$' 30 ||
    die "claude did not start in $pane (current: $(pane_prop "$pane" '#{pane_current_command}'))"
}

cmd_spawn() {
  local dir=${1:-} hint=${2:-}
  [[ -n "$dir" ]] || die "usage: spawn <project-dir> [name-hint]"
  [[ -d "$dir" ]] || die "not a directory: $dir"
  dir=$(cd "$dir" && pwd)

  local pane
  pane=$(tmux split-window -d -c "$dir" -P -F '#{pane_id}')
  tmux select-layout tiled >/dev/null 2>&1 || true
  sleep 1
  launch_claude "$pane" "$dir"

  claim_pane "$pane"
  if [[ -n "$MODEL" ]]; then tmux set-option -p -t "$pane" @worker_model "$MODEL"; fi

  # The plugin names the session at SessionStart; give it a moment, then either
  # adopt that name or, if a hint was given, set it THROUGH the plugin so both
  # sides keep one value. Never invent a name that lives only on the pane.
  local n=""
  for _ in 1 2 3 4 5 6; do
    n=$(agent_name "$pane"); [[ -n "$n" && "$n" != "-" ]] && break; sleep 2
  done
  if [[ -n "$hint" ]]; then set_agent_name "$pane" "$hint" >/dev/null; fi
  n=$(mirror_name "$pane")
  printf '%s\t%s\n' "$pane" "${n:-unnamed}"
}

cmd_claim() {
  local target=${1:-} name=${2:-}
  [[ -n "$target" ]] || die "usage: claim <pane-id> [name]"
  [[ -n "$BOSS_PANE" ]] || die "claim needs a boss pane (TMUX_PANE is unset)"
  local pane; pane=$(resolve_pane "$target")
  claim_pane "$pane"
  if [[ -n "$name" ]]; then set_agent_name "$pane" "$name" >/dev/null; fi
  local n; n=$(mirror_name "$pane")
  printf 'claimed %s as %s\n' "$pane" "${n:-unnamed}"
}

# --require-idle: stop the session only if it is idle at the last possible
# moment, and never with Escape. Measured on Claude Code 2.1.276 (2026-09-18,
# plans/2026-09-18-boss-jev-hook.md): /exit does not queue behind a busy turn.
# With a tool running it opens a "Background work is running" dialog and the
# turn goes on; one Escape closes that dialog and nothing else. With the model
# generating and no tool yet, /exit exits at once and the turn is lost. Two
# Escapes abort ANY busy turn, so this path sends none before /exit. What is
# left is the gap between the read below and the keystroke.
retire_require_idle() {
  local pane=$1 row sid st pin
  row=$(python3 "$PANES_PY" --state "$pane" 2>/dev/null) || true
  IFS=$'\t' read -r sid st pin <<<"$row"
  [[ -z "$EXPECT_SESSION" || "$sid" == "$EXPECT_SESSION" ]] ||
    die "$pane runs session ${sid:--}, not $EXPECT_SESSION: not retiring (--require-idle)"
  [[ "$EXPECT_LAST" != "-" && "$pin" != "-" || -z "$EXPECT_LAST" ]] ||
    die "$pane: no pin to compare (expected ${EXPECT_LAST}, found ${pin:--}): not retiring"
  [[ -z "$EXPECT_LAST" || "$pin" == "$EXPECT_LAST" ]] ||
    die "$pane has new input since the check (last record ${pin:--}, expected $EXPECT_LAST): not retiring"
  [[ "$st" == "idle" ]] ||
    die "$pane status is '${st:-unknown}', not idle: not retiring (--require-idle)"
  tmux send-keys -t "$pane" '/exit' Enter
  wait_for_cmd "$pane" "$SHELL_CMDS" "${BOSS_EXIT_WAIT:-15}" && return 0
  if tmux capture-pane -t "$pane" -p | grep -q 'Background work is running'; then
    tmux send-keys -t "$pane" Escape
    die "$pane: a turn started between the idle check and /exit; the exit dialog was closed with one Escape and the worker left running"
  fi
  die "$pane did not exit within ${BOSS_EXIT_WAIT:-15} s (status now: $(agent_status "$pane")); left as is"
}

# The default stop: refuse a BUSY session, then Escape Escape /exit. A busy
# session must be interrupted before /exit is read: two Escapes cancel an
# in-flight turn, and one retry covers a slow first attempt.
retire_default() {
  local pane=$1 try
  assert_not_busy "$pane"
  for try in 1 2; do
    tmux send-keys -t "$pane" Escape
    sleep 1
    tmux send-keys -t "$pane" Escape
    sleep 1
    tmux send-keys -t "$pane" '/exit' Enter
    wait_for_cmd "$pane" "$SHELL_CMDS" 30 && break
    [[ $try == 2 ]] &&
      die "$pane did not return to a shell (current: $(pane_prop "$pane" '#{pane_current_command}'))"
  done
}

cmd_retire() {
  local target=${1:-} kill_flag=${2:-}
  [[ -n "$target" ]] || die "usage: retire <pane-id> [--kill]"
  local pane; pane=$(resolve_pane "$target")

  if [[ $(pane_prop "$pane" '#{pane_current_command}') =~ ^(claude|node)$ ]]; then
    if [[ -n "$REQUIRE_IDLE" ]]; then
      retire_require_idle "$pane"
    else
      retire_default "$pane"
    fi
    prompt_visible "$pane" || printf 'WARN: %s reports a shell but no prompt is drawn\n' "$pane" >&2
  elif [[ -n "$EXPECT_SESSION" ]]; then
    die "$pane is not running Claude, so it cannot be session $EXPECT_SESSION: not retiring"
  fi

  if [[ "$kill_flag" == "--kill" ]]; then
    tmux kill-pane -t "$pane"
    printf 'killed %s\n' "$pane"
  else
    printf 'retired %s (pane kept)\n' "$pane"
  fi
}

cmd_restart() {
  local target=${1:-}
  [[ -n "$target" ]] || die "usage: restart <pane-id>"
  local pane dir
  pane=$(resolve_pane "$target")
  dir=$(pane_prop "$pane" '#{pane_current_path}')
  local keep; keep=$(agent_name "$pane")
  cmd_retire "$pane" >/dev/null
  launch_claude "$pane" "$dir"
  # A recycled worker keeps its name: the owner tracks the pane by the name on it,
  # and a restart that renames the worker loses them the thread.
  if [[ -n "$keep" && "$keep" != "-" ]]; then
    for _ in 1 2 3 4 5 6; do
      local n; n=$(agent_name "$pane"); [[ -n "$n" && "$n" != "-" ]] && break; sleep 2
    done
    set_agent_name "$pane" "$keep" >/dev/null
  fi
  mirror_name "$pane" >/dev/null
  printf 'restarted %s in %s as %s\n' "$pane" "$dir" "${keep:-unnamed}"
}

cmd_move() {
  local target=${1:-} dir=${2:-}
  [[ -n "$target" && -n "$dir" ]] || die "usage: move <pane-id> <new-project-dir>"
  [[ -d "$dir" ]] || die "not a directory: $dir"
  dir=$(cd "$dir" && pwd)
  local pane; pane=$(resolve_pane "$target")
  local keep; keep=$(agent_name "$pane")
  cmd_retire "$pane" >/dev/null
  launch_claude "$pane" "$dir"
  if [[ -n "$keep" && "$keep" != "-" ]]; then
    for _ in 1 2 3 4 5 6; do
      local n; n=$(agent_name "$pane"); [[ -n "$n" && "$n" != "-" ]] && break; sleep 2
    done
    set_agent_name "$pane" "$keep" >/dev/null
  fi
  mirror_name "$pane" >/dev/null
  printf 'moved %s to %s as %s\n' "$pane" "$dir" "${keep:-unnamed}"
}

# Columns: pane-id, session:window.pane, command, worker name, owner, path.
# The coordinate is session-qualified on purpose — pane INDEXES collide across
# tmux sessions (three separate "pane 0" is normal with two bosses running), so
# a bare index sends the owner to the wrong terminal.
cmd_list() {
  local mine_only=""
  [[ "${1:-}" == "--mine" ]] && mine_only=1

  # One pass over the resolver, cached: it walks /proc and reads transcripts,
  # so calling it per pane would make `list` cost seconds.
  local meta; meta=$(python3 "$PANES_PY" 2>/dev/null || true)

  # `IFS=$'\t' read` COLLAPSES runs of tabs (tab is IFS whitespace), so an unset
  # option in the middle of the format silently shifts every later field left and
  # The owner ends up printed as the worker's name. Never emit an empty field:
  # the #{?opt,...} conditionals substitute a literal "-" instead.
  local fmt=$'#{pane_id}\t#{session_name}:#{window_index}.#{pane_index}\t#{pane_current_command}\t#{pane_current_path}\t#{?@worker_name,#{@worker_name},-}\t#{?@boss_pane,#{@boss_pane},-}'

  printf 'PANE\tCOORD\tNAME\tSTATE\tCTX\tCOST/TURN\tOWNER\tPATH\n'
  tmux list-panes -a -F "$fmt" | while IFS=$'\t' read -r id coord cmd path mirror owner; do
    local tag mark=""
    if [[ "$id" == "$BOSS_PANE" ]]; then
      tag="self"; mark=" <- you"
    elif [[ "$owner" == "-" || -z "$owner" ]]; then
      tag="unowned"
    elif [[ "$owner" == "$BOSS_PANE" ]]; then
      tag="mine"
    else
      tag="other($owner)"
    fi
    if [[ -n "$mine_only" && "$tag" != "mine" && "$tag" != "self" ]]; then
      continue
    fi

    # Live name/status/context from the plugin + transcript; fall back to the
    # pane mirror only when the session is gone (a crashed worker still shows
    # the name it had, which is what makes it recognisable in the watchdog).
    local row name state ctx cpt turns
    row=$(printf '%s\n' "$meta" | awk -F'\t' -v p="$id" '$1==p{print;exit}')
    if [[ -n "$row" ]]; then
      name=$(cut -f2 <<<"$row"); state=$(cut -f4 <<<"$row")
      ctx=$(cut -f5 <<<"$row"); cpt=$(cut -f6 <<<"$row"); turns=$(cut -f7 <<<"$row")
    else
      name="$mirror"; state="$cmd"; ctx="-"; cpt="-"; turns=""
    fi

    # Flag what proposal A acts on: cost per turn well above a fresh session's
    # ~30k. This is the recycle signal, and it is a number, not a hunch.
    local flag=""
    if [[ "$cpt" =~ ^[0-9]+$ ]]; then
      if   (( cpt >= 90 )); then flag=" RECYCLE"
      elif (( cpt >= 60 )); then flag=" heavy"
      fi
    fi
    # Second signal, on absolute context (the owner, 2026-09-08): between 400k and
    # 500k the boss starts evaluating a clear/restart with a handoff; at 500k it
    # is overdue. Independent of cost/turn — a cheap-per-turn session still
    # dies at the window ceiling.
    if [[ "$ctx" =~ ^[0-9]+$ ]]; then
      if   (( ctx >= 500 )); then flag="$flag CTX-RESTART"
      elif (( ctx >= 400 )); then flag="$flag CTX-EVAL"
      fi
    fi

    printf '%s\t%s\t%s\t%s\t%sk\t%sk%s\t%s\t%s%s\n' \
      "$id" "$coord" "$name" "$state" "$ctx" "$cpt" "$flag" "$tag" "$path" "$mark"
  done
}

[[ -n "${TMUX:-}" ]] || die "not running inside tmux"

self_register

case "${1:-}" in
  spawn)   shift; cmd_spawn "$@" ;;
  claim)   shift; cmd_claim "$@" ;;
  retire)  shift; cmd_retire "$@" ;;
  restart) shift; cmd_restart "$@" ;;
  move)    shift; cmd_move "$@" ;;
  list)    shift; cmd_list "$@" ;;
  ctx)     shift; python3 "$PANES_PY" "$@" ;;
  *) die "usage: $(basename "$0") {spawn <dir> [name] [--model M] | claim <pane> [name] | retire <pane> [--kill] | restart <pane> | move <pane> <dir> | list [--mine] | ctx [pane]} [--force] [--require-idle [--expect-session S] [--expect-last U]]" ;;
esac
