# 03: The merge gate refuses unless the head's CI is complete and green, on every path

**What to build:** `boss_merge.py` read the head's check runs only on the docs/tests-only path (rule 2,
`docs_tests_problem`). A Codex GO, a provisional GO on a non-deploying base, `--test-only-since` and
`--merged-base-since` merged without reading any check. On 2026-11-22 two PRs of a public repo merged
on a GO while their only check run was still queued or in progress (`merges.jsonl`, 21:34:40Z and
21:34:47Z).

1. Once the record allows the merge, `read_checks` on the live head must answer green (at least one
   run, `total_count` equal to the runs listed, every run completed and success/neutral/skipped, one
   success at least, and every `required_checks` name of the base's `.boss/deploy.json` succeeded),
   or the gate refuses with its own reason, `ci-not-green` (exit 3), under `--dry-run` too.
2. The boss merges on the pulse: it runs the gate's `--dry-run` on every open PR of its track and
   merges the ones that pass, without waiting for the worker's "ready" message. The worker still
   reports, and still ticks the ticket and deletes its branch after the merge.

Neither ci-state 01-03 (CI state for the pulse's idle count) nor merge-flow 01-02 (rebase and batch
rules) covers this.

**Blocked by:** None (can start immediately)

**Status:** in-review

- [x] Tests first in `skills/boss/test_boss_merge.py` (`CiGate`): queued, in progress, red, none,
      unlisted, unreadable and missing-required checks refuse as `ci-not-green` on a Codex GO, a
      provisional GO, `--test-only-since` and `--merged-base-since`; the dry run says it; rule 2
      reads the checks once
- [x] The gate in `merge()`, before the merge-queue check and the dry run
- [x] `skills/boss/SKILL.md`: the gate paragraph, "Merge on the pulse", the pulse step, the
      reporting contract
