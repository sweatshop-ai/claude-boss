# 02: Reviews graded by risk and size

**What to build:** rules in P6 of `skills/boss/SKILL.md`, replacing "every PR, up to three rounds":

- Under 100 added lines and nothing sensitive: one Codex round; another only if it finds a defect of class a or b.
- Security, data, or anything on a production host: today's regime.
- Every PR: when a round brings only tests, docs, style or far-fetched cases, those become tickets and the PR closes.
- Over 500 added lines: split before review.
- The standards review runs once per PR, not on every head.

**Why:** review and the work after it were about 40% of tokens and 8% of project duration. In a sample of 738 findings on 40 PRs, 48% were tests, docs or style, and from round 4 half were in code an earlier fix wrote. But 15 of the 33 grave defects came after round 1, 7 of them in the original code, so one round for everybody is not the answer.

**Blocked by:**
- External: Thierry settles a grilling round on what counts as sensitive; not yet asked

**Status:** needs-grilling

- [ ] Grilling round settled: what counts as sensitive, and who decides it for a PR
- [ ] The rules are in the skill and quoted in the dispatch text
- [ ] Reverts and post-merge defects are compared on the PRs that took the short path, before the path is widened
