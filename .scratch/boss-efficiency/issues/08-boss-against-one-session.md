# 08: A/B: boss against one long session with subagents

**What to build:** the same ticket graph run both ways, on a repository with no client data: tokens, merged PRs, reverts, duration, and the owner's minutes.

**Why:** the one question the audit could not answer. It says where time goes inside the boss, not whether the boss beats the alternative. Open since 2026-10-27.

**Decided by Thierry, 2026-11-05:** the graph is `overview-build` in agentview, 22 tickets: 142M tokens, 37 hours, 13 of them machine time in the original run. He chose it over the recommended `paste` (10 tickets, 22M tokens). Both runs are replays from the same starting commit, in a separate copy that never goes live, and stop at merged PRs with CI green. About 284M tokens for the two.

No bar is set in advance. In his words: "I think we'll just look at the numbers and then decide." The runs report tokens, merged PRs, reverts and serious post-merge defects, duration and his minutes, side by side, with no verdict; the decision is his, after he has seen them. Both replays start with all 22 tickets known, while the original started with 13 and found the rest, so neither replay compares directly with the 142M.

**Blocked by:** None (can start immediately)

**Claimed by:** Kaveh 2026-11-05 09:14

**Status:** in-progress

- [x] The graph chosen; no bar in advance, by the owner's choice
- [ ] Both runs measured the same way and put in front of the owner
- [ ] His decision recorded
