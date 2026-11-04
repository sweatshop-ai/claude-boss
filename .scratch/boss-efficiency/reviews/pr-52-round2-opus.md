# PR 52 round 2 (Opus): `--stop-shells`, `shell` refused by default

Reviewed: `/home/tiroir/Projects/boss-plugin-wt-22`, branch `ticket-22-lifecycle`, `git diff d771a25 d60b853`.
Read-only. Nothing in tmux, claude or pytest was started. The one thing I ran was a small bash harness
with a mocked `tmux` function, to exercise `background_counts` and `still_busy`.
Line numbers refer to `skills/boss/boss-lifecycle.sh` at d60b853 unless another file is named.

## Verdict: GO

None of the four attacks finds a path that types at a `shell` pane when `--stop-shells` is absent. The flag
cannot be set by `--force` and cannot be used without `--require-idle`. It only lets `shell` through when
`over == 1`. Below are one residual (pre-existing, not introduced here) and four nits. None of them blocks.

## (1) Default refusal: can a `shell` pane still reach `send-keys`?

- VERIFIED `still_busy` (l.346-349) returns busy for `shell` whenever `STOP_SHELLS` is empty, whatever `over` is.
  The mock harness showed that with no flag, `shell` never passes, for over in {1,0,-,""}.
- VERIFIED without wait, l.414-415: `st == shell` leads to `still_busy && refuse_busy`, then `die` (l.366/368/370, `die`
  at l.94 exits). The `/exit` at l.423 is never reached.
- VERIFIED with wait: the loop at l.394 repeats while `still_busy`. Afterwards l.399 refuses. Only status reads
  run inside the loop (l.396). No keystroke.
- VERIFIED the retire path takes the same function: `cmd_retire` l.477-478 calls `retire_require_idle`. Restart is
  `cmd_restart` l.504, which goes through `cmd_retire` in the same shell (no `$(...)`). So a `die` exits the script
  before `launch_claude` at l.507.
- VERIFIED the only keystroke helpers in this path are l.423 (`/exit`), l.337 (`stop_leftover_background`, after
  `/exit`) and l.442 (Escape, after `/exit`). All of them come after the gate at l.414-418.
- VERIFIED `refuse_busy` only reads: `background_counts` (l.355-358) runs `tmux capture-pane`, never `send-keys`.
- **Residual R1 (low, pre-existing):** the post-`/exit` dialog branch (l.428-439) confirms "Exit and stop tasks"
  without checking `STOP_SHELLS`. A pane that read `idle` at l.383 and still has background work opens the dialog,
  and l.437-438 then stops that work with no flag. So the default refusal only holds if Claude Code never reports
  `idle` while a shell or Monitor is running. SKILL.md l.286 says such a pane reads `shell` (a measured claim).
  The code cannot check this: the status is the peer file's `status` field, passed through as-is
  (`boss-panes.py` l.245). NOT FOUND: no fixture or test pins "Monitor armed gives `shell`". If it matters,
  require `STOP_SHELLS` at l.437 when the status at the first read was `idle`, or record the measurement as a fixture.

## (2) The flag

- VERIFIED `--force` only sets `FORCE` (l.59). `STOP_SHELLS` is only set by `--stop-shells` (l.61). `FORCE` does not
  appear in `retire_require_idle` (l.381-446); the test `test_force_does_not_imply_stop_shells` covers it.
- VERIFIED that without `--require-idle` the flag is rejected at l.71-73 before any command runs (test
  `test_stop_shells_needs_require_idle`). `retire_default` never reads `STOP_SHELLS`.
- VERIFIED that with the flag and `over != 1` (0, `-`, empty) `still_busy` stays true (l.348), so the pane is refused.
  The harness confirmed it; the test loop covers it with and without the flag.
- VERIFIED no status other than `shell`/`idle` gets through: l.416-417 refuses any other value, including empty and
  `-`. `busy` and `waiting` stay busy in `still_busy`, whatever the flag says.

## (3) `set -e` / pipefail

- VERIFIED `counts=$(background_counts ...)` runs in a command substitution. `inherit_errexit` is not set (grep: no
  match), so errexit is off inside it. If `tmux capture-pane` fails, the function still returns 0 with empty output
  (mock run: `fail rc=0 []`, `empty rc=0 []`). The final pipeline is `{ grep || true; } | sort | paste | sed`, so under
  pipefail all four stages exit 0. The `${counts:+ (...)}` form drops the parentheses when nothing was found.
- VERIFIED `still_busy ... && refuse_busy ...` (l.399, l.415): when `still_busy` fails, that is an exempt non-final
  `&&` member, and the enclosing `if` is exempt as a compound command. So the script carries on as intended.
  `refuse_busy` is the final member, so errexit is live inside it. Its only fallible step is the `counts=` assignment,
  which returns 0 (see above). Even if it failed, the script would exit 1 without typing anything, and only the
  message would be lost.

## (4) Footer regex and doc claims

- VERIFIED `4 agents` is not matched, and `2 shells still running` plus `2 shells` collapse to a single entry through
  `sort -u` (mock: `[1 monitor, 2 shells]`).
- **N1 (cosmetic):** the regex has no word boundaries. `12 shellscripts` gives `12 shells` and `3 monitoring` gives
  `3 monitor` (mock run). If the two footer lines disagree mid-update, both counts are shown (`1 shell, 2 shells`).
  This only affects the text of the message; nothing is typed. `tail -5` assumes the footer sits in the last 5
  captured lines. I did not check this against a real pane.
- **N2 (message accuracy):** `refuse_busy` l.367-368 says "a turn is in flight" for any `over` other than 1,
  including `-` or a missing fifth field, where the right answer is "unknown". The test at
  `test_boss_lifecycle.py` (the in-flight-or-unknown loop) locks this wording in.
- **N3 (usage text):** l.12 puts `--stop-shells` inside `[--wait-idle SECONDS [--stop-shells]]` for `retire`, which
  reads as if the flag needs `--wait-idle`. The code does not require that (l.71), and the `restart` line (l.13) and
  the usage `die` (l.562) write it correctly.
- **N4 (unknown status ends the wait early, pre-existing):** `still_busy` returns false for an empty or `-` status,
  so a single failed `--state` read ends `--wait-idle` and l.416 refuses. Nothing is typed, but the wait ends sooner
  than it should.
- VERIFIED doc claims backed by code: CHANGELOG "stays refused by default, turn over or not" (l.348); "`--wait-idle`
  keeps waiting" (l.394); "tells a turn in flight from turn over" (l.364-368); "kinds and counts ... read without
  typing" (l.355-358); "`--force` does not imply it" (l.59/61); "with `--require-idle`" (l.71); "says so, prints each
  job and confirms" (l.419-421, l.335-337). SKILL.md l.286-299 says the same.
- NOT FOUND in code (they are measurement claims): "measured on Claude Code 2.1.311" for the footer format (l.352-353),
  and "a Monitor reads `shell`" (SKILL.md l.286). See R1.
- NOT CHECKED: the CHANGELOG sentence "stamps the old script left on worker panes stay until the pane is reused".
  It concerns `self_register`, which is outside this diff's code.
