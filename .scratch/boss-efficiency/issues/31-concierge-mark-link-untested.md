# 31: Nothing tests the link between a concierge's pane mark and the watchdog

**What to build:** ticket 11's tests (`skills/boss/test_workers_watch.py`) write the pane list by hand: `run_watch` writes the TSV at line 52 and the role is a literal at line 55. The real mark is `tmux set-option -p -t "$pane" @worker_role "$ROLE"` in `boss-lifecycle.sh` (line 292, in `cmd_spawn`); the watchdog reads it through `#{?@worker_role,#{@worker_role},-}` in the `tmux list-panes -F` of `routines/boss-workers-watch.sh` (line 59). Nothing tests that link: rename the option on one side and a concierge's question alerts again, with every test green. One test closes it: on an isolated tmux server (private socket, no pane of this machine touched), `boss-lifecycle.sh spawn --concierge` marks a pane through its own code, and the watchdog, with no `FAKE_PANES`, reads that pane through its own format string and treats it as a concierge.

**Blocked by:** None (can start immediately)

**Claimed by:** Ronja 2026-11-05

**Status:** open

- [ ] The test: a pane marked by `boss-lifecycle.sh`'s own code, read by the watchdog's own format string, a question on its screen raises no alert; skipped with a stated reason when tmux is absent
- [ ] Shown to fail: a mutant with the option renamed on one side fails it, for each side
- [ ] The second half of ticket 11's criterion, below

**The second half of ticket 11 does not apply as written.** Ticket 11 offered two ways to the same end: "skip panes with `@worker_role` set to concierge, or read the registry's `waitingFor` instead of the screen". The criterion "screen detection still alerts with the registry unavailable" assumes the second. The watchdog never reads a registry: it was built with the first option, screen only, and its own header says it is "pure bash + tmux, no LLM anywhere in the detection path" (`routines/boss-workers-watch.sh` lines 7-9). Checked: `grep -n -i registry routines/boss-workers-watch.sh` prints nothing; the only inputs are `panes_list` (`tmux list-panes -a`, or `FAKE_PANES`) and `capture` (`tmux capture-pane`, or `FAKE_CAP_DIR`). The existing tests already drive that path: `test_a_concierge_stuck_on_a_real_permission_prompt_still_alerts`, `..._full_permission_dialog_alerts` and `..._narrow_pane_dialog_alerts` alert from the screen alone, and no test has a registry to make unavailable. No test is built for a thing that does not exist.
