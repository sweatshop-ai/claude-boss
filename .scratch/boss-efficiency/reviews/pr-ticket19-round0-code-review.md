# Ticket 19 — round 0: mattpocock-skills:code-review (Rune)

Diff `origin/main...HEAD`, one commit. No repo coding standards documented; smell baseline only. Two fresh agents, read-only, no transcripts.

## Standards (judgement calls)
- Possible Duplicated Code: the failure rule (90%, ten messages) lives in `judge`, the constants and `boss-efficiency.md`. Kept: the doc states the rule for readers.
- FAIL_UNCOVERED comment grew to five lines, out of idiom. **Fixed**: block comment above the constants.
- `day(t)` generic name, local-time date label. Kept: small helper, label already local everywhere in the routine.
- Stderr wording awkward. **Fixed**: "skipped (in sessions with records)".
- `.sh` one-line if/else for the lock fallback; `exec 9>/dev/null` skips locking when `pm/` is absent. Kept: only reachable in a dry run, since a real run makes `pm/` first.
- `Usage` four-clause predicate: mild, kept.

## Spec
- Item 3 met through the "or" (stderr wording); no code path change to `scan_session`.
- Item 7: `MemoryMax=1G` decided from one measured real week; the figure is deliberately not in the repo.
- Item 9: `-c2 -n7` chosen, cap unchanged. **Fixed**: test now asserts `ionice -c2 -n7`.
- Item 6: literal 25 verified (test passes against the code: output weight 5).
- Rerun test flakiness at midnight: `NOW` is a fixed 12:00 local, +3600 is 13:00; cannot cross midnight. No change.
- Not asked for: `MIN_MESSAGES = 10` value is a policy choice the spec left open; written in the doc.

Local tests: 37 passed, imported from `/home/tiroir/Projects/boss-plugin-wt/Rune/routines/boss_efficiency_core.py`.
