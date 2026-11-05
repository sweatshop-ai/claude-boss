# 37: Findings of the second Codex pass on the merged PRs (ticket 10)

**What to build:** Codex, run once on the merged diff of each PR (2026-11-05, Britt, after its limit reset at 09:41), found the items below. Each is a ticket-sized fix, not a revert; none is fixed here. Raw output and the answers are in `.scratch/boss-efficiency/reviews/pr-<repo>-<n>-codex.md`. Class: a security property broken, data loss, wrong behaviour on a normal path; b wrong behaviour on an unusual realistic path; c far-fetched; d tests, docs, style. Citations were checked against current main.

**Blocked by:** None (can start immediately)


**Claimed by:** Rune 2026-11-05 10:25

**Status:** done (merge 351f31a, PR 72; Codex owed on the 14:47 list)

- [x] b. PR 71, `skills/boss/SKILL.md:739`: the `boss-unask record` example uses a heredoc with the fixed delimiter `EOF`; a question or owner wording with a line that is exactly `EOF` ends it early and the rest of the report text runs as shell. VERIFIED on main. Use framing that cannot collide (a delimiter checked absent from the content, or stdin from a file). Built (Rune, branch rune/ticket-37).
- [x] b. PR 71, `skills/boss/unask.py:81`: `read_text()` raises `UnicodeDecodeError` on a torn multi-byte record (an interrupted append), before the per-line skip runs; `boss-unask list` and `owner_reports()` in the weekly routine then fail until the file is repaired. VERIFIED on main and reproduced (`UnicodeDecodeError` from `unask.read`). Read bytes and decode per line with `errors="replace"`, or skip lines that do not decode. Built (Rune, branch rune/ticket-37).
- [ ] c. PR 69, `routines/boss_efficiency_core.py` (merge 817-819; main 872): a queued alert whose retry fails stays in `unsent`; if the same week's fresh alert then succeeds, only the failure path replaces by label, so the old entry is posted again next run. VERIFIED; needs Slack to fail and then take a message in one run. Drop the queued entry for `label` when the fresh alert succeeds. Not built: boss's call: class c and d, the stop rule.
- [ ] c. PR 69, `routines/boss_efficiency_core.py` (merge 799-802; main 850-853): a delayed alert Slack took is dropped from the queue in memory only; the state is written after the first window's measure, so a timeout kill in between re-sends it next run. VERIFIED; a duplicate message, no loss. Persist the queue right after the retry loop. Not built: boss's call: class c and d, the stop rule.
- [ ] d. PR 69, `routines/boss_efficiency_core.py` (merge 799-800; main 851): `if dry or alert(...)` skips queued alerts in a dry run, so `DRY_RUN=1` never shows what is waiting. VERIFIED. Print them (`alert(..., dry=True)` is safe). Not built: boss's call: class c and d, the stop rule.
