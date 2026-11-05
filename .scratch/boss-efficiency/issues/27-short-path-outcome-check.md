# 27: Compare reverts and post-merge defects on the PRs that took the short path

**What to build:** the measurement left over from ticket 02 box 3. Once PRs have merged on the short path (under 100 added lines, not sensitive, one Codex round), compare them with the longer paths: how many were reverted, or needed a fix PR that names them, within 14 days of merging. Do this before the short path is widened (a higher size line, or fewer rounds for sensitive PRs).

**How it is read:** the boss records its sensitivity call and the round count on each PR (ticket 02). Read the merged PRs of the period with `gh pr list --state merged --json number,additions,mergedAt,title` and the recorded calls in their comments; list the reverts and fix-ups with `git log origin/main --grep='^Revert' --since=<date>` and a search of later PR titles and bodies for "#<number>". The weekly `boss-efficiency` routine does not count reverts today, so this is a hand count unless a line is added to it.

**Questions for the owner** (left open by ticket 02, class d or readings it did not settle):
- A PR under 100 added lines and not sensitive: is there an upper bound on the extra rounds a class a or b finding can buy, or does it run until clean?
- A round that returns NO-GO with only class c or d findings and no earlier GO: does the PR merge with those findings as tickets, or does it get one more round to earn a GO?

**Blocked by:** time. At least 10 PRs merged on the short path and 14 days after the last of them. Not before.

**Claimed by:** nobody

**Status:** waiting

- [ ] Short-path PRs listed with their recorded sensitivity call
- [ ] Reverts and post-merge fixes counted for them and for the longer paths
- [ ] Result written here; widen the path, keep it, or tighten it
