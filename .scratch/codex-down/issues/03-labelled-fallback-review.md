# 03: Labelled fallback review

**What to build:** when Codex does not answer, the PR review command falls back to Claude Opus in read-only mode (decided 2026-10-03: only `codex` and `claude` are installed, so the fallback is the same family as the Claude workers; the label and ticket 04 make up for that). Its verdict is posted as "Fallback review (Codex unavailable)" and recorded as a **provisional GO** or NO-GO. A provisional GO lets a merge go ahead only where nothing deploys; the boss's merge rule says so.

**Blocked by:** 02 (PR review becomes a command)

**Status:** ready-for-agent

- [ ] With Codex down, the command reviews with Claude Opus read-only and posts the verdict labelled as a fallback, naming the reviewer and the head SHA
- [ ] A fallback GO is stored as provisional, distinct from a Codex GO, in the round file and on the PR
- [ ] The skill states that a provisional GO allows a merge only where nothing deploys
- [ ] When both reviewers fail, behaviour is as in 02: no verdict, failure recorded
- [ ] Tests: Codex down + fallback GO, Codex down + fallback NO-GO, both down
