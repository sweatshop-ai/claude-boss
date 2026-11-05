# PR 56 (claude-boss), Codex round 5 on head ef223b3

Codex review, `--base origin/main`, run 2026-11-05 04:41 through `codex-review.sh` (17 files, 436 changed lines; name grep on the diff: 0). Codex is available again (no usage-limit error). Verdict: **NO-GO as it stands, four findings of class b**, none in the unit-backup code (`bin/boss-link`, `install.sh`), which Codex did not flag. All four are in code that came with the earlier ticket 25 commits (78c8580, 664373c, 3ccfcdc), not in the redesign.

## Codex's output, verbatim

Several classifier gaps still allow real commands and file reads to be treated as coordination, defeating the intended warning and logging behavior. The version-gap liveness change also does not reject orphaned CLI sessions for the marker format used in practice.

Full review comments:

- [P1] Exclude extra sed commands from plain substitutions — /home/tiroir/Projects/boss-plugin-wt-anouk/skills/boss/boss-guard.py:103-103
  Because both `[^\\]*` groups can consume the chosen delimiter, the regex can backtrack to later delimiters and accept an entire multi-command sed program. For example, `sed -i 's/a/b/;e touch /tmp/pwn;s/x/y/' ~/.claude/pm/a.md` is classified as coordination even though the `e` command executes a shell command, so this real work remains unlogged; constrain each group to exclude the captured delimiter or parse exactly one substitution.

- [P2] Reject filter options that open additional files — /home/tiroir/Projects/boss-plugin-wt-anouk/skills/boss/boss-guard.py:175-178
  Treating every hyphen-prefixed token as harmless lets GNU `wc --files0-from=-` bypass the file-operand check. For example, `printf '/repo/src/app.ts\0' | wc --files0-from=-` is classified as coordination while `wc` opens and reads the listed source file, so the option handling needs an allowlist or explicit rejection of file-reading options.

- [P2] Clear owned cwd state after a failed && chain — /home/tiroir/Projects/boss-plugin-wt-anouk/skills/boss/boss-guard.py:213-217
  When an owned `cd` is followed by `&&`, `cwd_own` remains true past the next semicolon even if the directory does not exist. Thus `cd ~/.claude/pm/missing && echo skipped > a.md; echo x > src/app.ts` is classified as coordination, although the final write runs in the original non-owned directory; validate the directory before retaining the state or track the conditional chain through its terminating separator.

- [P2] Obtain the entrypoint before applying registry liveness rules — /home/tiroir/Projects/boss-plugin-wt-anouk/skills/boss/version_gap.py:84-87
  Normal `.in_use/<pid>` markers contain `pid` and `procStart` but no `entrypoint`, so this passes `None` to `registry.is_live`. Its controlling-terminal check only runs for `entrypoint == "cli"`, meaning an orphaned CLI process with the same PID/start time is still reported as a live old-version session despite the new documented behavior; merge the corresponding session-registry record or otherwise supply the entrypoint.

## Check of each citation against the code (run on ef223b3)

- **[P1] sed `e` command accepted as a plain substitution** — `skills/boss/boss-guard.py:103` (SED_SUBSTITUTE) and use at line 166. VERIFIED: `is_coordination("sed -i 's/a/b/;e touch /tmp/pwn;s/x/y/' ~/.claude/pm/a.md")` returns True; the plain `s/a/b/` also True. The lazy groups `[^\\]*?` can take the delimiter, so the regex backtracks across `;`. Class **b**: the guard is a warning and a log, not a boundary (its own comment says so), so a wrong True is a missed warning on a real command, not an escalation; but this is the exact gap ticket 25 set out to close.
- **[P2] `wc --files0-from=-`** — `boss-guard.py:175-178` (`filter_is_plain`). VERIFIED: `printf '/repo/src/app.ts\0' | wc --files0-from=-` returns True; any `-`-prefixed token passes. Class **b** (same reasoning). Fix shape: allowlist the short flags per filter, reject long options.
- **[P2] `cwd_own` kept after a failed `&&` chain** — `boss-guard.py:213-217`. VERIFIED: `cd ~/.claude/pm/missing && echo skipped > a.md; echo x > src/app.ts` returns True. For `&&` the directory check is skipped, and `cwd_own` stays true past the `;`. Class **b**.
- **[P2] real `.in_use` markers have no `entrypoint`** — `skills/boss/version_gap.py:84-87`. VERIFIED: a marker on this machine holds exactly `pid` and `procStart`; `rec.get("entrypoint")` is None, so `registry.is_live` never applies its controlling-terminal check (registry.py:75, only for `entrypoint == "cli"`), and an orphaned CLI process with the same pid and start time still counts as a live old-version session. Correction after the first write-up: `test_version_gap.py` writes markers of the real shape (`pid`, `procStart`, line 42); no test covers an orphan (only a reused pid, line 82, and a zombie, line 95). Class **b**: the documented behaviour of 3ccfcdc does not hold on real markers.

Nothing in the unit-backup work (`bin/boss-link`, `install.sh`, the templates, README) was flagged.

## Decision

The boss (Anton) merged PR 56 on ef223b3 as e9e765d and moved the four findings to ticket 33: class b, and not regressions (findings 1 and 3 return True on main's guard as well).
