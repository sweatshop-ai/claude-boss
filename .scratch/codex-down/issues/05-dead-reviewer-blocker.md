# 05: A dead reviewer becomes an open blocker

**What to build:** after N consecutive failed PR reviews (N kept in the policy module), the boss's tracker gets an open blocker "Codex down" with a ladder marker. It escalates on the normal rungs and reaches the owner once through `AskUserQuestion`, with three options: wait, accept the fallback review, or merge on tests alone. The blocker clears itself on the next successful Codex answer. Today an outage leaves every PR waiting with nothing telling the boss what to do; this makes it an open blocker the ladder already knows how to raise.

**Blocked by:** 02 (PR review becomes a command)

**Status:** ready-for-agent

- [ ] N lives in the policy module and the skill quotes it (the policy test keeps the quote true)
- [ ] The Nth consecutive failure appends exactly one open blocker with a marker; more failures do not add duplicates
- [ ] The ladder raises it on the normal rungs with no boss turn needed
- [ ] The boss puts the question to the owner once, via `AskUserQuestion`, with the three options
- [ ] A successful Codex answer removes the blocker and resets the count
- [ ] Tests against a throwaway config dir: count, single blocker, clear on recovery
