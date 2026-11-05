# PR 63, round 1: fresh Opus correctness review (head 27599bd). Verdict: GO

Run by running the test and mutants on a `git archive` copy, not only by reading. Codex follow-up owed (out until 04:38).

- Real tmux server not touched, VERIFIED: every `TMUX*` variable stripped, `TMUX_TMPDIR` private, server started `-f /dev/null`, `kill-server` runs with the private `TMUX`; the real server's `list-panes -a` was identical before and after.
- No leaks after a passing run and two failing mutant runs, VERIFIED: no `sleep 120`, no private server, no `/tmp/boss-mark-test*` dir. Only a SIGKILL of the runner would orphan them.
- No false pass, VERIFIED: the control (mark removed, same screen must alert `permission-prompt`) fails if `pane_current_command` is not `claude` or capture fails. `exec -a claude sleep` reports `claude`. Mutant at `boss-lifecycle.sh:292`: FAIL. Mutant at `boss-workers-watch.sh:59`: FAIL. Unmutated: OK in 20.4 s at load about 10.
- Skip logic, VERIFIED: skips only when tmux is missing. CI on 27599bd: 623 passed, 1 skipped (main: 622 passed, 1 skipped), so the new test ran.
- Ticket citations `boss-lifecycle.sh:292` and `boss-workers-watch.sh:59`, and "the watchdog has no registry input": VERIFIED.

Minor, not fixed in this round (one round allowed):
1. `tmux()` and `watch()` run `subprocess.run` with no timeout; a hung tmux would hang the suite. Suggested `timeout=30`.
2. The stub sleeps 120 s from its start; spawn's naming loop takes about 12 s; under extreme load the control could fail late (a flaky failure, never a false pass).
3. The boss pane runs the default shell with its rc files (`default-command` is set after `new-session`); cosmetic.
