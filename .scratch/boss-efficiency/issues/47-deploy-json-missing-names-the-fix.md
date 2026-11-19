# 47: a missing .boss/deploy.json refusal says how to fix it

**What to build:** when `boss_merge.py` refuses with exit 4 and the deploy state is `missing`, the message names the file to commit on the base branch and prints a ready `{"version": 1, "non_deploying": ["<base>"]}`, with the warning that it is the owner's declaration. No fallback to `branch_deploys.py`.

**Why no fallback:** `branch_deploys.py` exit 1 says no GitHub workflow fires on push. It does not see a box that pulls the branch itself (the tiroir-central VPS pulls its mirror that way), and it reads a local checkout, while the merge gate reads only what is committed on the base through `gh api`. `deploy.json` is the declaration that covers both; missing means deploying, by design. Exit 4 applies only to a provisional or waived GO; a plain GO merges without the file.

**Measured 2026-11-18 (Rocco):** Lucas had to find out on his own to push `.boss/deploy.json` to tiroir/thierrys-tiroir master before PR 7 could merge; the refusal said only "deploying-base: deploy list missing".

**Blocked by:** None (can start immediately)


**Claimed by:** Suki 2026-11-19 15:34

**Status:** in-progress

- [ ] Test first: a provisional GO on a base with no deploy.json prints the path and the ready JSON for that base
