# Codex review, claude-boss PR 49, merge bf3e896 (base 513aa46)

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr
scope: base 513aa46
diff:  10 file(s), 1293 changed line(s)
files:
  .claude-plugin/plugin.json
  CHANGELOG.md
  install.sh
  routines/boss-efficiency.md
  routines/boss-efficiency.sh
  routines/boss_efficiency_core.py
  skills/boss/test_boss_efficiency.py
  systemd/boss-efficiency.service.in
  systemd/boss-efficiency.timer.in
  uninstall.sh
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr.
The secret check covers the diff listed above, not what Codex opens on its own.
The routine is not provisioned for existing installations, fails with supported custom configuration directories, and misses questions from the default concierge workflow. Its failure and alert handling can also silently lose notifications or establish an invalid baseline.

Full review comments:

- [P1] Add an upgrade path for the new timer — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/install.sh:50-51
  Existing installations never execute these newly added installer lines: `README.md:85-90` explicitly says `install.sh` runs once and upgrades only move the stable symlink. After upgrading from 0.21.1, neither `boss-efficiency.timer` nor its service exists under the user's systemd directory, so the advertised weekly routine never runs unless the user happens to rerun installation manually.

- [P1] Pass the configured Claude directory to systemd — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/systemd/boss-efficiency.service.in:8-8
  When installation uses a non-default `CLAUDE_CONFIG_DIR`, the systemd user manager does not inherit a one-shot environment assignment from `install.sh`; this service supplies no `Environment=CLAUDE_CONFIG_DIR=@CFG@`, so the script falls back to `$HOME/.claude` and scans and writes the wrong configuration directory. The template already receives an `@CFG@` substitution, so the service should explicitly export it.

- [P1] Count questions delegated to the concierge — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/routines/boss_efficiency_core.py:391-393
  In the standard workflow described by `skills/boss/references/concierge.md:39-55`, the guard prevents the boss from calling `AskUserQuestion` and the boss delegates it to a concierge session. That session is attributed through the boss socket as a worker, but this counter only examines boss sessions, so normal owner questions are omitted and the questions/day metric and its anomaly alert remain zero or severely understated.

- [P2] Defer the baseline until Slack delivery succeeds — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/routines/boss_efficiency_core.py:638-640
  When a week has anomaly flags and Slack is unavailable, this code adds the week to history and writes the state before `alert()` reports failure. The process exits nonzero, but the unannounced week is now the next baseline, so a persistent spending change compares equal on the following run and may never be reported; failed alert delivery should not commit that week as a successful baseline.

- [P2] Alert on wrapper-level failures — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/routines/boss-efficiency.sh:34-40
  If the transcript lock remains held for two hours, or if the scan below is killed by `timeout`, the wrapper only logs and exits; the core never runs its Slack failure path. These are explicitly measurement failures, so the routine can silently miss an entire week precisely when notification is needed.

- [P2] Expire persisted socket ties before path reuse — /home/tiroir/Projects/boss-plugin-wt/Britt-cr/routines/boss_efficiency_core.py:302-305
  Persisted UDS paths are retained indefinitely without a last-seen time. When a later Claude process reuses an old socket path, such as after PID reuse or reboot, the stale track wins until the new socket accumulates two qualifying votes; the first worker can therefore be attributed to the previous track, and a reused worker socket can be excluded from coverage as though it belonged to another boss.

codex-review: output kept at /tmp/codex-review-Britt-cr-20261105T050712-1723540-review.txt (Codex's session log: /tmp/codex-review-Britt-cr-20261105T050712-1723540-review.txt.stderr)

## Answers

Run with `--base 513aa46` (first parent): real merge commit. Citations checked against bf3e896.

Verdict: GO on the merge as built, with one class a finding and five class b. Codex marked three P1 and three P2.

| # | Finding | Citation | Class | Answer |
|---|---------|----------|-------|--------|
| 1 | [P1] No upgrade path: the timer and service exist only for users who rerun `install.sh`; README says it runs once | install.sh:50-51 | b | VERIFIED: `bin/boss-link` moves the symlink only and writes no unit; README.md:85-90 says no rerun after an upgrade. Same cause as the PR 53 finding in ticket 25 (MemoryMax) and ticket 33 R4-9. Ticket 32. |
| 2 | [P1] The service has no `Environment=CLAUDE_CONFIG_DIR`, so a non-default config dir is ignored under systemd | systemd/boss-efficiency.service.in:8 | b | VERIFIED: the unit has no Environment line (nor does the watchdog's); the script falls back to `$HOME/.claude` (boss-efficiency.sh:19). Only with a non-default dir. Ticket 32. |
| 3 | [P1] Questions asked through the concierge are not counted | routines/boss_efficiency_core.py:391-393 | a | VERIFIED: asks are summed only over `index.bosses`; the concierge is attributed as a worker; the guard refuses the boss's own AskUserQuestion while a concierge lives (concierge.md:39-55). The questions/day metric and its alert (lines 497-498) read near zero in the standard workflow. Ticket 32. |
| 4 | [P2] A week with anomaly flags becomes the baseline before Slack delivery succeeds | routines/boss_efficiency_core.py:638-640 | b | VERIFIED: history is extended and state written before `alert()` runs; a failed send leaves the week as the next baseline. Ticket 32. |
| 5 | [P2] A lock wait or `timeout` kill exits in the wrapper without a Slack alert | routines/boss-efficiency.sh:34-40 | b | VERIFIED: both paths only log and exit; the unit shows failed, nothing is sent. Deliberate per the comment, but nobody reads a failed unit. Ticket 32. |
| 6 | [P2] Persisted socket ties never expire, so a reused socket path keeps its old track | routines/boss_efficiency_core.py:302-305 | b | VERIFIED: `socks = dict(saved)`; a new vote overrides only with 2 or more qualifying votes at 0.6. Socket paths carry the pid, so reuse after a reboot is certain over time. Ticket 32. |
