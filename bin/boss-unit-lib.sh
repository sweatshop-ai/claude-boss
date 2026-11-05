# Sourced by bin/boss-link and install.sh: write a systemd unit, keeping what it replaces.
#
#   write_unit <path> <content>   <content> is the rendered template followed by a
#                                 literal "x" (so a trailing newline survives $(...)).
#
# A file that already holds different content is copied to <path>.bak-<YYYY-MM-DD-HHMMSS>
# first, because it may hold a hand edit (systemd ignores that suffix; uninstall.sh
# names the units one by one). Prints one line naming the copy when it rewrites;
# nothing when the file is already current. CHANGED_UNITS is set on a rewrite.
#
# Sessions start together, so two runs can reach the same unit at once. The whole
# check-copy-rewrite runs under flock on <dir>/.boss-units.lock (when flock exists),
# and underneath it the copy is complete before it takes its name (a hard link, which
# fails rather than replace a copy that is there; the name gets -2, -3 ... then) and
# the unit is replaced by rename, so the copy never shares an inode with the new file.
# A copy that cannot be made leaves the unit alone, with a line on stderr.
_write_unit_locked() {
  local path=$1 want=$2 bak tmp n=1
  if [[ -f $path ]]; then
    [[ "$(cat -- "$path"; echo x)" == "$want" ]] && return 0
    tmp="$(mktemp -- "$path.tmp-XXXXXX")" || { echo "boss: cannot write beside $path; left alone" >&2; return 0; }
    if ! cp -p -- "$path" "$tmp" 2>/dev/null; then
      rm -f -- "$tmp"; echo "boss: cannot keep a copy of $path; left alone" >&2; return 0
    fi
    bak="$path.bak-$(date +%Y-%m-%d-%H%M%S)"
    until ln -- "$tmp" "$bak" 2>/dev/null; do
      [[ -e $bak ]] || { rm -f -- "$tmp"; echo "boss: cannot keep a copy of $path; left alone" >&2; return 0; }
      n=$((n + 1)); bak="$path.bak-$(date +%Y-%m-%d-%H%M%S)-$n"
    done
    rm -f -- "$tmp"
    tmp="$(mktemp -- "$path.tmp-XXXXXX")"
    printf '%s' "${want%x}" > "$tmp"
    chmod --reference="$bak" -- "$tmp" 2>/dev/null || true
    mv -f -- "$tmp" "$path"
    echo "boss: refreshed $path (previous kept as $bak)"
  else
    printf '%s' "${want%x}" > "$path"
  fi
  return 3
}

write_unit() {
  local rc=0 lock
  lock="$(dirname -- "$1")/.boss-units.lock"
  if command -v flock >/dev/null 2>&1 && ( exec 9>>"$lock" ) 2>/dev/null; then
    ( flock 9; _write_unit_locked "$@" ) 9>>"$lock" || rc=$?
  else
    _write_unit_locked "$@" || rc=$?
  fi
  [[ $rc -eq 3 ]] && CHANGED_UNITS=1
  return 0
}
