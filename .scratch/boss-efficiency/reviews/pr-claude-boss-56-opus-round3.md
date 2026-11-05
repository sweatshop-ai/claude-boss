# PR 56 (sweatshop-ai/claude-boss), round 3: adversarial review of the unit backup

Reviewer: fresh Opus agent, no prior context. Head reviewed: `e635b0c` on `anouk/ticket-25`
(worktree `/home/tiroir/Projects/boss-plugin-wt-anouk`). Read-only: nothing edited, committed or pushed.
Every experiment ran in `mktemp -d` (`/tmp/tmp.C5XZRFNEtM`) with HOME, XDG_CONFIG_HOME and
CLAUDE_CONFIG_DIR pointed there and a stub `systemctl` on PATH. `test_bin.py`: 48 passed.

Classes: (a) data loss / blocks merge, (b) wrong behavior, (c) minor or cosmetic, (d) out of scope.

## Findings

### F1 (a) Concurrent SessionStart runs lose the hand edit: the only copy holds the template

`bin/boss-unit-lib.sh:14-17` (VERIFIED, read and run) does compare, then `[[ -e $bak ]]`, then
`cp -p`, then `printf > path`, with no lock and no atomic create. Two `boss-link` processes in the
same second (several sessions starting together, which is what the boss does when it launches
workers; also `install.sh` while a session starts) interleave like this:

1. A and B both read the hand edit, both see it differs (line 14).
2. B tests `[[ -e $bak ]]`: false (line 16).
3. A runs `cp` (creates the copy with the hand edit) and `printf` (truncates and writes the template).
4. B's `cp` now finds the copy existing and opens it with O_TRUNC: it overwrites the copy with the
   current unit, which is the template or an empty truncated file.

Measured: 4 parallel `boss-link` runs on 6 hand-edited units, 40 trials: the hand edit was in no
`.bak-*` file for **192 of 240 units**. Isolated run, one unit, 3 trials: 2 of 3 lost; the copy held
`[Unit]\nDescription=Run the boss escalation ladder…` (the template). Some copies were 0 bytes
(B copied the file between A's truncate and write). All four processes printed
`boss: refreshed … (previous kept as …bak-…)`, naming a copy that does not hold the previous file.
Other runs failed instead with `cp: cannot create regular file …: File exists` on stderr and exit 1
(cp's own O_EXCL create lost the race), which also breaks the "silent on stderr" goal.

This is exactly the loss the ticket exists to prevent, and it happens on the first refresh after an
upgrade, the one moment a hand edit is at stake. Fix options: serialise with `flock` on a lock file
outside the units dir (e.g. under `$cfg/routines/`) around the whole refresh; or copy first to a
unique name (`mktemp "$path.bak-$(date …)-XXXX"`), compare that snapshot, keep it only if it
differs, and write the new unit through a temp file plus `mv` so no reader ever sees a truncated
unit. A test with N parallel `boss-link` runs belongs next to
`skills/boss/test_bin.py:527` (VERIFIED: that test covers only sequential same-second calls).

### F2 (b) A second CLAUDE_CONFIG_DIR retargets the user's timers, and alternation piles up copies

`bin/boss-link:39-41,54` (VERIFIED) renders `@ROOT@`/`@CFG@` from the session's own
`CLAUDE_CONFIG_DIR`, but the units dir is per user, not per config dir (`bin/boss-link:47`).
Measured: alternating sessions under `$T/home/.claude` and `$T/cfgB` rewrote the 3 `.service`
units on every switch, 4 switches gave 12 `.bak-*` files, and the units end up pointing at
whichever config dir started a session last. A `CLAUDE_CONFIG_DIR` with a trailing slash differs
from one without and also triggers a rewrite. No hand edit is lost (each copy is made), but the
ladder silently runs against another config dir and the copies grow without bound. Before this PR
only `install.sh` wrote the units, so this behavior is new here. Suggest: refresh only when the
unit's current `ExecStart` already points at this `$link` (or skip units whose `@CFG@` differs).

### F3 (b) A failing copy aborts the hook every session, with stderr, and the unit is never refreshed

`bin/boss-unit-lib.sh:16` under `set -euo pipefail` (`bin/boss-link:29`, VERIFIED): `cp` is the
last command of the `||` list, so its failure exits before line 17. That ordering is right: no
rewrite without a copy (VERIFIED: read-only units dir left `HAND ro` intact, rc=1; unreadable unit
mode 200 left intact, rc=1). But the hook then exits 1 with `cp: … Permission denied` (and for an
unreadable unit also `cat: … Permission denied` from line 14) at every SessionStart, and the
`boss-link` run from `install.sh:41` aborts the install. Data safe; noise and a dead refresh.

### F4 (c) Sequential same-second rewrite: the second message names a copy that holds the first edit

`bin/boss-unit-lib.sh:15-18` (VERIFIED with a stubbed `date`): edit ONE, run, edit TWO in the same
second, run: edit TWO is in no file, and the second run prints "previous kept as" the copy holding
ONE. A human edit within one second of a refresh is not realistic, so (c); the test at
`skills/boss/test_bin.py:537-545` (VERIFIED) deliberately accepts dropping the intermediate content.
The message should not claim a copy it did not make. Fixed for free by unique copy names (F1).

### F5 (c) A failed template render writes an empty unit in install.sh

`install.sh:54` (VERIFIED): `"$(sed … "$ROOT/systemd/$u.in"; echo x)"` takes the status of
`echo x`, so a `sed` failure is masked and `write_unit` writes an empty unit (after copying the old
one). Reproduced by sourcing the lib with a missing template: rc=0, unit 0 bytes. `boss-link`
guards with `-f $tdir/$u.in` (`bin/boss-link:53`, VERIFIED); `install.sh` does not, but all six
templates ship in the repo, so only a broken checkout hits it. The old code (`sed > unit`) also
left an empty unit, but failed loudly.

### F6 (c) Symlinked unit: the write goes through the link into the target file

`bin/boss-unit-lib.sh:13,17` (VERIFIED): `-f` follows the link, `cp -p` copies the target's
content (kept correctly), and `printf >` rewrites the target (e.g. a dotfiles repo) while the
link stays. No loss, but now at every SessionStart rather than once at install. A dangling
symlink is skipped by `boss-link` (`bin/boss-link:53`) and written through by `install.sh`
(`bin/boss-unit-lib.sh:20`), same as before the PR.

### F7 (c) NUL bytes: one bash warning on stderr

`bin/boss-unit-lib.sh:14` (VERIFIED): `warning: command substitution: ignored null byte in input`
on stderr. The copy is byte-exact (`HAND\0nul\n`, checked with `od`). Cosmetic.

### F8 (c) `BIN=1 ./install.sh` symlinks the library onto PATH

`install.sh:66-67` (VERIFIED, read) links every `bin/*` into `~/.local/bin`, now including the
non-executable `boss-unit-lib.sh`. Harmless clutter; exclude it or move the lib out of `bin/`.

## Checked and found sound

- Copy before rewrite: `cp` (line 16) completes before `printf >` truncates (line 17); a failed
  `cp` exits under `set -e` before the rewrite (VERIFIED, F3 experiments).
- Trailing newlines: the `echo x` sentinel and `${want%x}` round-trip exactly; a current unit is
  silent (VERIFIED: rerun printed nothing, rc 0, no extra copy).
- `install.sh` after `boss-link` refreshed: `install.sh:41` runs `boss-link`, which refreshes and
  copies; the loop at `install.sh:51-55` then finds every unit current and is silent (VERIFIED:
  one copy, holding the hand edit).
- `CHANGED_UNITS` under `set -u`: initialised at `bin/boss-link:48` before the read at line 57;
  `install.sh` never reads it (VERIFIED, read).
- Sourcing: `bin/boss-link:44` resolves `readlink -f` of `BASH_SOURCE`, so a call through a
  symlink finds the lib (VERIFIED: `$T/lb/boss-link` symlink worked). `bin/boss-unit-lib.sh` is
  tracked in git (`git ls-files bin`, VERIFIED) and not ignored; the plugin ships the repo tree, and
  `.claude-plugin/plugin.json` has no file list that would exclude it (VERIFIED, read).
- Missing unit: `boss-link` never creates one (`bin/boss-link:53`); `install.sh` creates it
  without a copy (`bin/boss-unit-lib.sh:19-20`) (VERIFIED, fresh install in temp HOME).

## Verdict

F1 is the loss the ticket is meant to prevent, reproduced in 192 of 240 units under 4 concurrent
session starts; F2 is new wrong behavior from the same refresh.

NO-GO on e635b0c: concurrent `boss-link` runs overwrite the backup and lose the hand edit (F1).
