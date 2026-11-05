# PR 56 (ticket 25), second-model verdict round 2: fresh Opus, head 94d4644 (backup of a replaced unit). Codex follow-up owed from 04:38.

No class a or b finding. VERIFIED (tests, systemctl --root=<tmp> and mode-555 dir run by the reviewer, never the real ~/.config):
- A failing `cp` stops boss-link before the overwrite (bin/boss-link:54, set -e): in a mode-555 units dir rc=1 and the unit still held the edit.
- A later run cannot overwrite a copy: own timestamp per copy, `cp -n` refuses an existing name.
- A symlinked unit: the copy holds the target's content, the write goes through the link as before.
- `systemctl --root=<tmp> list-unit-files` lists only the real units, 0 `.bak-*`; daemon-reload and timers ignore them.
- uninstall.sh:16-17 and install.sh:49-56 name units one by one; no glob matches `.bak-*` (uninstall leaves copies behind: fine).
- Rendered unit with the header passes `systemd-analyze verify`.
- The new test fails with the `cp` line removed.

Class c, not fixed (a fix would need a new verdict): `cp -n` prints a "non-portable -n" warning on stderr at every refresh (`--update=none-fail` is quiet); the header says `.bak-<date>` where the name is `.bak-YYYY-MM-DD-HHMMSS` (README is right); copies pile up unpruned; a failing copy exits 1 each session start and skips the other units; install.sh re-run still overwrites an edited unit without a copy; one `.bak` per service file on first upgrade.

VERDICT: GO
