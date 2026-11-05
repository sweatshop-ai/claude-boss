# Sourced by bin/boss-link and install.sh: write a systemd unit, keeping what it replaces.
#
#   write_unit <path> <content>   <content> is the rendered template followed by a
#                                 literal "x" (so a trailing newline survives $(...)).
#
# A file that already holds different content is copied to <path>.bak-<YYYY-MM-DD-HHMMSS>
# first, because it may hold a hand edit (systemd ignores that suffix; uninstall.sh
# names the units one by one). An existing copy is never overwritten, and the test is
# ours rather than `cp -n`, which warns on stderr at every call. Prints one line,
# naming the copy, when it rewrites; nothing when the file is already current.
write_unit() {
  local path=$1 want=$2 bak
  if [[ -f $path ]]; then
    [[ "$(cat -- "$path"; echo x)" == "$want" ]] && return 0
    bak="$path.bak-$(date +%Y-%m-%d-%H%M%S)"
    [[ -e $bak ]] || cp -p -- "$path" "$bak"
    printf '%s' "${want%x}" > "$path"
    echo "boss: refreshed $path (previous kept as $bak)"
  else
    printf '%s' "${want%x}" > "$path"
  fi
  CHANGED_UNITS=1
}
