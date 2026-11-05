# PR 56 (claude-boss, anouk/ticket-25), round 4 review of head ef223b3

Fresh Opus reviewer, read-only. Scope: `bin/boss-link`, `install.sh`, `systemd/*.in`, README,
CHANGELOG, `skills/boss/test_bin.py`. Every experiment ran in a `mktemp -d` sandbox with HOME,
XDG_CONFIG_HOME and CLAUDE_CONFIG_DIR pointed into it and a stub `systemctl` first on PATH;
the sandboxes are removed. `python3 -m pytest test_bin.py -q`: 48 passed (VERIFIED).

## Summary

No data-loss finding. boss-link writes nothing at session start, and install.sh makes the copy
before every rewrite and stops when it cannot. Two wrong-behavior findings, neither blocking:
version skew between two config dirs that share one units dir, and silence about a unit whose
ExecStart points at a stale root. The rest is cosmetic.

## (a) "Writes nothing at session start"

- No finding. Under `strace -f` (openat/creat/rename/unlink/link/mkdir/utimensat/truncate/execve)
  with one differing unit, `check_units` opened nothing for writing (the only O_RDWR was a failed
  `/dev/tty` probe), changed no mtime, made no temp file, and executed only `sed`, `head`, `cat` and
  `readlink`. The stub systemctl log held only the calls install.sh made. `bin/boss-link:43-60` VERIFIED.
- The link write (`mkdir -p` + `ln -sfn`, `bin/boss-link:84-85`) is in `$cfg/routines`, not the units
  dir. It is unchanged from earlier behavior. VERIFIED.

## (b) install.sh copy-before-rewrite

All VERIFIED by running it:
- Hand edit, re-run: the copy `boss-ladder.service.bak-YYYY-MM-DD-HHMMSS` holds the edit, the path is printed, then the unit is rewritten (`install.sh:49-55`).
- Read-only units dir: `cp` fails, `set -e` aborts (rc=1), and the unit keeps the edit. No rewrite happens without a copy.
- Unreadable unit: `cp` fails, rc=1, and the unit is unchanged.
- Same second: the test stubs `date`, both copies are kept through `--backup=numbered` (`.~1~`), and the test passes.
- Missing template, or an empty one: the length guard refuses, rc≠0, and the unit is unchanged. A `|` in CFG makes sed fail, the guard refuses, and nothing is written.
- Symlinked unit: `cp -p` dereferences, so the copy is a regular file with the edit. The new content goes *through* the link into its target (a dotfile). The link stays and nothing is lost.

Findings:
1. **(c)** `install.sh:47-48`: the `&&` in `want="$(sed …; echo x)" && [[ ${#want} -gt 1 ]] || {…}` checks nothing. The assignment's status is `echo x`'s, which is always 0, so sed's exit status is discarded and only the length test guards. That catches no output (missing, empty or unreadable template, a bad sed expression). A sed that fails after writing part of its output would pass the guard. I found no realistic way to trigger that. The precedence `(A && B) || C` is right. VERIFIED (read; the `|` case ran).
2. **(c)** `install.sh:69` with `set -e`: when one unit's copy fails, the units before it in the loop are already rewritten and `daemon-reload` does not run. Every rewritten unit has its copy, so no data is lost. The state is half-applied until a re-run. VERIFIED (read-only-dir run: rc=1 after `boss-ladder*`/`workers*` were processed).
3. **(c)** `install.sh:55`: `printf > unit` truncates in place. Interrupting it can leave a short unit, but the copy already exists. Commit 3e89a23 used a rename, and this head dropped it. VERIFIED (read).

## (c) boss-link at session start

Exit code and hangs. All VERIFIED, rc=0 in every case:
- A directory, a FIFO or a dangling symlink at a unit path is skipped by `-f` (`bin/boss-link:49`).
- A unit with no ExecStart falls back to `$link`/`$cfg`.
- A 200 MB unit took 14 s. That is absurd input, so (c).
- Every caller uses `check_units || true` (`bin/boss-link:68,75,87`), so `set -e` and `pipefail` are inert inside the function. The `sed | head -n1` SIGPIPE cannot fail the hook.
- Normal case: 0.36 s under load 11. VERIFIED.

Noise and silence:
4. **(b)** **Version skew across two CLAUDE_CONFIG_DIRs that share one units dir.** Config A is upgraded and has run install.sh. Config B's link points at a different version (each config has its own plugin cache). Every session under B then prints "installed unit(s) differ … run `<B's root>`/install.sh". Following that advice rewrites the units to B's link and B's config dir, so logs and state move to B, and B's templates may be older. Same version under both configs: silent (VERIFIED). Different version: three units reported (VERIFIED with a copy of the root whose headers were removed). Suggested fix: compare only when the installed unit's ExecStart root (`r`, `bin/boss-link:51`) resolves to this config's `$link`, or else name the owner config in the line.
5. **(b)** **False silence on a unit that points at a stale root.** `r` is taken from the installed ExecStart and substituted back into the template. A unit whose ExecStart and Documentation both point at, say, `/old/cache/0.17.0` therefore compares equal and boss-link says nothing, although that is the 2026-10-23 failure mode (VERIFIED: sed-edited unit, empty output). The owner chose this design, and this release's header change makes every older service unit differ anyway, so impact today is low. Logged so the design choice is a known one.
6. **(c)** `&` or `\` in CFG/ROOT: install.sh renders a corrupt path (`amp&x` becomes `amp@ROOT@x`, `bs\x` becomes `bsx`). boss-link reads that corrupt path back, round-trips it and stays silent (VERIFIED). The renderer is pre-existing (`origin/main:install.sh:52` uses the same sed). A `|` makes boss-link print a sed error plus a "differ" line on every session (VERIFIED), and install.sh refuses to render. Spaces work (VERIFIED).
7. **(c)** An unreadable unit prints three `sed`/`cat` "Permission denied" lines to stderr on every session start, plus the "differ" line (VERIFIED). The advice then fails in install.sh (finding (b) above, no loss).
8. **(c)** `install.sh:39` runs boss-link before the units are written. An upgrade run of install.sh therefore prints "units differ … run …/install.sh" in the middle of install.sh itself, a few lines before it replaces them (VERIFIED). Suggest `check_units` only for the hook call, or pass a flag from install.sh.

## (d) Docs vs behavior

9. **(c)** `systemd/boss-{ladder,workers-watch,efficiency}.service.in:9-10` still say "bin/boss-link moves it on every session start, so an upgrade needs no re-render". The new header three lines above, and the CHANGELOG, say an upgrade that changes a template needs `install.sh`. VERIFIED (read).
10. **(c)** `install.sh:12-13`: "so the units never go stale" is true only of the path, not the content. `bin/boss-link:6` says "The two systemd units" where there are three (pre-existing). VERIFIED (read).
- README (`README.md` hunk at line 86) and the CHANGELOG entry match the behavior. That covers the one line, writing nothing, the `.bak-<YYYY-MM-DD-HHMMSS>` copy with its path printed, no render meaning no unit, no pruning, the drop-in being left alone, and each service unit being replaced once on the first run because of the new header. Timers have no header and are not replaced. VERIFIED (ran a fresh install, then boss-link: silent).

## Classification

| # | Class | Where |
|---|---|---|
| 1 | (c) | install.sh:47-48 |
| 2 | (c) | install.sh:69 |
| 3 | (c) | install.sh:55 |
| 4 | (b) | bin/boss-link:51-57 |
| 5 | (b), owner's design | bin/boss-link:51-53 |
| 6 | (c), mostly pre-existing | install.sh:47, bin/boss-link:53 |
| 7 | (c) | bin/boss-link:51-54 |
| 8 | (c) | install.sh:39 |
| 9 | (c) | systemd/*.service.in:9-10 |
| 10 | (c) | install.sh:12-13, bin/boss-link:6 |

No (a) finding: no path loses a hand edit, clobbers a copy or rewrites before copying. boss-link writes nothing and never exits non-zero.

Verdict: GO on ef223b3. Findings 4 and 8 are worth a follow-up but do not block.
