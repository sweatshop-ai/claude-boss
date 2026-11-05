# Codex review, claude-boss PR 69, merge 1712bd1 (first parent as base)

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr2
scope: base 1712bd1^1
diff:  12 file(s), 335 changed line(s)
files:
  .scratch/boss-efficiency/issues/32-codex-pass-findings-ticket-10.md
  .scratch/boss-efficiency/reviews/pr-69-code-review.md
  CHANGELOG.md
  bin/boss-link
  routines/boss-efficiency.md
  routines/boss-efficiency.sh
  routines/boss_efficiency_core.py
  skills/boss/test_bin.py
  skills/boss/test_boss_efficiency.py
  systemd/boss-efficiency.service.in
  systemd/boss-ladder.service.in
  systemd/boss-workers-watch.service.in
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr2.
The secret check covers the diff listed above, not what Codex opens on its own.

The new retry queue can retain or re-persist alerts that were successfully delivered, causing duplicate Slack notifications. It also hides queued notifications during dry runs.

Full review comments:

- [P2] Remove queued alerts superseded by successful reruns — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/routines/boss_efficiency_core.py:817-819
  When retrying a queued alert fails but rerunning that same week's window produces a fresh alert that succeeds, the success path leaves the old same-label entry in `unsent`; only the failure path replaces entries by label. The next invocation therefore posts the obsolete alert again, so clear any queued entry for `label` when the fresh alert succeeds as well.

- [P2] Persist successful dequeues before continuing the scan — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/routines/boss_efficiency_core.py:799-802
  When Slack accepts a delayed alert, this `continue` removes it only from the in-memory queue; the persisted state is not updated until the first window reaches `write_outputs`. If the configured timeout kills the process after the POST but before that write, the old queue remains on disk and the already-delivered alert is sent again next run. Persist the dequeued queue immediately after retry processing.

- [P3] Include queued alerts in dry-run output — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/routines/boss_efficiency_core.py:799-800
  With `DRY_RUN=1` and pending `unsent` entries, the `dry or ...` short-circuit prevents `alert` from being called, so the dry run silently omits messages waiting for delivery even though `alert(..., dry=True)` safely prints what would be sent. This contradicts the documented dry-run behavior and can make an operator believe no delayed alerts are pending.

## Answers

Verdict: GO with follow-ups. Class a/b/c/d: 0/0/2/1. All three citations VERIFIED at the merge commit (lines as cited) and on main (lines shifted to 872, 850-853, 851). None fixed by a later PR. In ticket 37.

- [P2] `routines/boss_efficiency_core.py:817-819`, a fresh successful alert leaves the older same-label entry in `unsent`, so it is re-sent. Class c (Slack must fail then recover inside one run). Ticket 37.
- [P2] `routines/boss_efficiency_core.py:799-802`, a dequeued delayed alert is persisted only at the first `write_outputs`; a kill in between re-sends it. Class c (a duplicate message). Ticket 37.
- [P3] `routines/boss_efficiency_core.py:799-800`, a dry run skips queued alerts. Class d. Ticket 37.
