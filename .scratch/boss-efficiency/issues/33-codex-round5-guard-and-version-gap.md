# 33: Codex round 5 on PR 56: three guard gaps, a liveness check that skips orphans, and two unit-check lines

**What to build:** Codex ran on PR 56 (head ef223b3, merged as e9e765d; `.scratch/boss-efficiency/reviews/pr-claude-boss-56-codex-round5.md`) and found four things, class b, all reproduced on ef223b3. The boss ran findings 1 and 3 against main's guard before the PR: both return True there too, so they are not regressions of PR 56; finding 4's old check only compared the start time. They get their own small PR. The guard warns and logs, it is no boundary, so none of this breaks a security property; it makes a warning miss a real command, and finding 4 makes a documented behaviour false on real data. Each fix gets a test written first that fails on main.

**Blocked by:** None (can start immediately)

**Claimed by:** Adnan 2026-11-05 04:52

**Status:** in-progress

Guard (`skills/boss/boss-guard.py`)
- [ ] 1 (b) line 103, `SED_SUBSTITUTE = re.compile(r"s([/|#,:@])[^\\]*?\1[^\\]*?\1[gpI0-9]*")`, used at line 166: the lazy groups can take the delimiter, so the regex backtracks across `;` and accepts a whole multi-command program. Reproduce: `is_coordination("sed -i 's/a/b/;e touch /tmp/pwn;s/x/y/' ~/.claude/pm/a.md")` returns True (checked on ef223b3; `~` expands to an owned path). Fix sketch: each group excludes the captured delimiter, `s(.)((?!\1)[^\\])*\1((?!\1)[^\\])*\1[gpI0-9]*`, or split on the delimiter and require exactly three parts; keep the `w` and `e` flags out.
- [ ] 2 (b) lines 175-178, `filter_is_plain`: `not (w.startswith("-") and w not in REDIRECTS)` accepts any `-` token, so a long option that opens files passes. Reproduce: `is_coordination("printf '/repo/src/app.ts\\0' | wc --files0-from=-")` returns True (checked on ef223b3). The boss's two tries at this form returned False on both, so run exactly this command. Fix sketch: allow only short flags, and per filter only the ones in a small allowlist (`wc`: `-l -w -c -m`; `head` and `tail`: `-n -c`; `cut`: `-d -f -c -b`); refuse `--` options.
- [ ] 3 (b) lines 213-217: for `cd <owned dir> && ...` the `os.path.isdir` check is skipped (`token != "&&"`), and `cwd_own` stays True past the next `;`. Reproduce: `is_coordination("cd ~/.claude/pm/missing && echo skipped > a.md; echo x > src/app.ts")` returns True (checked on ef223b3; main returns True too). Fix sketch: after a `cd` joined by `&&`, check `os.path.isdir` at the end of that `&&` chain (at `;`, a newline or the end) and clear `cwd_own` there if the directory is missing, or treat any statement after `;` as outside the owned directory unless the `cd` was checked.

Liveness (`skills/boss/version_gap.py`)
- [ ] 4 (b) lines 84-87, `_same_process`: `registry.is_live({"pid": mark.name, "procStart": ..., "entrypoint": rec.get("entrypoint")})`. The real `.in_use/<pid>` marker holds only `pid` and `procStart` (read on this machine: `['pid', 'procStart']`), so `entrypoint` is None and `registry.is_live` never applies its controlling-terminal check (`registry.py:75`, only for `entrypoint == "cli"`): an orphaned CLI session with the same pid and start time counts as a live old-version session. The docstring of `_same_process` ("an orphan ... count as gone") is false on real markers. Reproduce: a marker `{"pid": P, "procStart": S}` for a live CLI process with no controlling terminal (field 5 of `/proc/P/stat` is 0) makes `running()` list it. Fix sketch: take the entrypoint from the session record, `registry.by_pid(pid, cfg)` (`sessions/<pid>.json` has `entrypoint`, `procStart` and `pid`), and pass it to `registry.is_live`; with no record, decide and document (a marker with no record is not a session). Correction of the round-5 text: `test_version_gap.py` writes markers of the real shape (`{"pid", "procStart"}`, line 42); the gap is that no test covers an orphan, only a reused pid (line 82) and a zombie (line 95). Add a test with a real-shaped marker and a session record with `entrypoint: cli` whose process has no controlling terminal.

From ticket 25 (round 4, `reviews/pr-claude-boss-56-opus-round4.md`)
- [ ] R4-4 (b) `bin/boss-link`, `check_units`: two config dirs share one units dir but run different plugin versions; every session under the second prints "run install.sh", and following it moves the units to that config dir. Compare only when the installed `ExecStart` root resolves to this config's link.
- [ ] R4-5 (b) a unit whose `ExecStart` and `Documentation` both point at an old version directory compares equal, so `boss-link` stays silent (the 2026-10-23 failure mode); low today because the new header makes every older service unit differ once.

Minor, from round 4 (none blocks; take them in the same PR only if they stay small)
- [ ] R4-1 (c) `install.sh`, `install_unit`: the `&&` after the render assignment checks nothing (the status is that of `echo x`); only the length test guards.
- [ ] R4-2 (c) when one unit's copy fails, earlier units are already rewritten and `daemon-reload` does not run (nothing is lost).
- [ ] R4-3 (c) the unit is overwritten in place, not by rename; an interrupted write can leave a short unit (the copy exists).
- [ ] R4-6 (c) a config path with `&` or `\` renders a broken unit and `boss-link` stays silent (the renderer on main has it too); a `|` prints a sed error at every session start.
- [ ] R4-7 (c) an unreadable unit prints "Permission denied" lines at every session start.
- [ ] R4-8 (c) `install.sh` runs `boss-link` before writing the units, so an upgrade prints "run install.sh" from inside `install.sh`.
- [ ] R4-9 (c) the `.service.in` headers still say "so an upgrade needs no re-render", `install.sh:12-13` says "the units never go stale", and `bin/boss-link:6` says "two units" for three.
