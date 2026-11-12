# 35: Prune rule 1 removes the entry of a PR that merged at another head (class a)

**What to build:** 06b's rule 1 in `_prunable` (`skills/boss/boss_review.py`) removed an entry when a Codex GO above the entry's round sat on the entry's `head=`, whatever head the PR merged at. Found while building 10a. Provisional GO on head A, then a provisional GO on head B (the entry's line is replaced, so it says `head=B`), then a Codex GO on B, then the PR merges at A: rule 1 removed the entry before 10a's recheck saw the merged head, so the merged code A was never re-reviewed by Codex. A review obligation was lost (class a).

**Scope:** a prune rule may only drop an entry whose merged head, or every head it could merge at, has a Codex GO. For a merged PR that is the merged head, which is rule 4's test. Rule 1 therefore applies to a merged PR only when the merged head is the entry's own head. For an open PR rule 1 is unchanged (the head the PR could still merge at is read by rule 2 and by 22's gate, which refuses a head with no deciding round); that is declined here and stays as 06b specified it.

**Blocked by:** 06b, 10a (merged)

**Status:** done (Otilia built it, PR PRNUM)

- [x] `_prunable` applies rule 1 to a `MERGED` PR only when `headRefOid` equals the entry's `head=`; otherwise rule 4 decides (a Codex GO on the merged head removes, a NO-GO or no round keeps). Test first: the scenario above keeps the entry on main's code and fails there; with a later Codex GO on A it removes; with a Codex NO-GO on A it keeps
- [x] CONTEXT.md and CHANGELOG.md say it
