# 10: Codex re-reviews every provisional GO, and a release waits for it (index)

Split on 2026-11-12 (Otilia, on Chiara's ruling) into two tickets, accepting finding 12 of Codex spec round 1 (`plan-review-codex-04-10-11-1.md`): 10 did not fit one session. The six boxes of the old 10 now live in the one of them named below, moved whole and not rewritten; this file holds none, so an old reference to "10" resolves here and a reference to a box resolves to the letter below.

What to build, in one line: when Codex answers again, each PR on 06a's provisional list gets a Codex review, a Codex NO-GO on a merged PR becomes an open blocker, and a release or wrap-up stops while the list holds an entry that counts. Recovery is Codex-only.

| Ticket | What it holds | Old 10 box (by its first words) | Blocked by |
|---|---|---|---|
| [10a](10a-recheck.md) | `boss_recheck.py` and its pass, the post-merge blocker and its crash resume, the merged-head rule, the tests | "`review(...)` gains no parameter", "`skills/boss/boss_recheck.py --track T`", "A Codex NO-GO on a merged PR (R20)", "A merged PR is reviewed at its merged `headRefOid`" (its recheck half), "Tests use real `git`" | 06b, 22 (both merged) |
| [10b](10b-list-and-release-stop.md) | `--list`, the release stop, the SKILL.md text, and the `--list` sentences and tests of the merged-head box | "`skills/boss/SKILL.md` (the Codex routine" and the `--list` half of the merged-head box | 10a |

**Where other tickets point:** nothing waits on 10 by name except `coverage.md` and 04/11's prose; both now resolve to this index. The merged-head box is in 10a whole; its `--list` sentences are 10b's, said in both files.

**Blocked by:** 10a, 10b (this file is an index; the work is in the two)

**Status:** done (10a: Otilia, PR 120; 10b: Zola, PR 125)
