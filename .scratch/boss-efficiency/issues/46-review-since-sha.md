# 46: boss_review.py reviews only the fix diff with --since SHA

**What to build:** `boss_review.py --since SHA` reviews `git diff SHA..HEAD` instead of the whole PR against its base, and puts the findings of the round whose head is SHA into the brief as the thing the fixes answer. SHA must be the head of an earlier round on file for that PR, an ancestor of the live head (`git merge-base --is-ancestor`); otherwise exit 2. The round records `since`, so `boss_merge.py` can tell a fix-diff GO from a full one.

Merge rule (settled 2026-11-19, Rocco's vote and mine): a fix-diff GO counts as a GO for the head in `boss_merge.decide` when the round at SHA was a GO with findings or a NO-GO, and the fix diff touches no file outside the files that round reviewed; otherwise the merge needs a full round. First real case: Tiago's PR 1045, round 1 on d3f42595, then a diff-only fix-pass GO on 50a71b2e.

Updates go to the cross-track boss (`~/.claude/pm/cross-track.md`), not to Rocco.

**Measured 2026-11-18 (Rocco):** under the one-round rule the second pass reads only the fix diff, but boss_review reviewed the whole PR head again for Yara (PR 1046, round 3) and for Lucas (thierrys-tiroir PR 7).

**Blocked by:** None (can start immediately)

**Claimed by:** Rafael (2026-11-19, inside ticket 48)

**Status:** open

- [ ] Test first: the brief built with `--since` carries `git diff SHA..HEAD`, not `git diff BASE...HEAD`, and the previous round's findings
- [ ] A SHA that is no round's head, or not an ancestor, is exit 2
- [ ] The merge rule above is tested
