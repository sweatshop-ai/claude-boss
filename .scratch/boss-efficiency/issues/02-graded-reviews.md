# 02: Reviews graded by risk and size

**What to build:** rules in P6 of `skills/boss/SKILL.md`, replacing "every PR, up to three rounds":

- Under 100 added lines and not sensitive: one Codex round; another only if it finds a defect of class a or b.
- 100 to 500 added lines and not sensitive: up to three rounds, and the stop rule below can end them earlier.
- Sensitive: today's regime, up to three rounds.
- Every PR: when a round brings only tests, docs, style or far-fetched cases, those become tickets and the PR closes.
- Over 500 added lines, sensitive or not: split before review.
- The standards review runs once per PR, not on every head.

Classes, from the audit's codebook. a: a security property broken, data loss, or wrong behaviour on a normal path. b: wrong behaviour on an unusual but realistic path (a crash mid-way, a transient failure, a re-run, a non-default config). c: a far-fetched edge case. d: tests, docs, naming, style, prose, standards only.

**Decided by Thierry, 2026-11-05:**

- Sensitive means a PR touches any of: login, auth or access rights; secrets, including code that screens or redacts them; deleting, migrating or overwriting stored data; anything that runs on a production host; a CI workflow that runs an AI agent.
- The boss decides it for each PR, from the ticket and the diff's file paths, when the PR goes to review, and records the call on the PR. The worker may raise a PR to sensitive, never lower it. In doubt, it is sensitive.
- All six rules above accepted as written. The 100 to 500 rule was added in this round, because the ticket left that size unstated.

**Why:** review and the work after it were about 40% of tokens and 8% of project duration. In a sample of 738 findings on 40 PRs, 48% were tests, docs or style, and from round 4 half were in code an earlier fix wrote. But 15 of the 33 grave defects came after round 1, 7 of them in the original code, so one round for everybody is not the answer.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] Grilling round settled: what counts as sensitive, and who decides it for a PR
- [ ] The rules are in the skill and quoted in the dispatch text
- [ ] Reverts and post-merge defects are compared on the PRs that took the short path, before the path is widened
