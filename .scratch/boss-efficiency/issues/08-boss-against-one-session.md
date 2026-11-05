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

## Setup report (Kwame, 2026-11-05)

Setup only; neither arm started. Nothing under agentview's own repo or `dev` was touched (read-only `git show`, `git ls-tree`).

- **Private repo:** `sweatshop-ai/ab-replay`, read back as `private: true`. The org lets members create private repos; its runner group "Default" is visible to all repos and refuses public ones. Bases `replay-A` (`b6be213`) and `replay-B` (`6780872`): a5674b4 plus one commit with the 8 stripped tickets and `.github/workflows/test.yml` (noreply identity).
- **CI proof on t-compute:** a throwaway branch `ci-proof` ran the whole unittest suite on `t-compute-1`, green (run on commit `31b6baa`; branch deleted). Two earlier runs failed and led to the fix in `test.yml`: the runner has no `python3` (now `uv run --no-project --python 3.14 --with numpy`), and numpy is missing without it (28 failures in the embedding tests). `test.yml` itself (the `pull_request` trigger) has not yet run on a PR.
- **Clean tickets:** `/home/tiroir/Projects/ab-replay/make-clean-tickets.py <agentview-repo> <outdir>`, output in `/home/tiroir/Projects/ab-replay/clean-issues/` (21 files: 01-13 as at a5674b4, 14-17 and 19-22 stripped to title, What to build, Blocked by and unticked boxes; 18 out). Ticket 19 had no boxes and was blocked by 18: it now has one box taken from its own text and "Blocked by 14".
- **Grepped in the output** (case-insensitive): Claimed by, Evidence, Merged to, Hunt, Status done/in-progress, `[x]`, "origin/dev as", Follow-ups, Gate, the worker names, any 7-40 hex string, "Found by", "worker". The only hits are product text in tickets 02 and 12 and the word "evidence" in ticket 19's own text. All 21 are `ready-for-agent`; none has a ticked box.
- **Scrub names:** no hit in the script, `test.yml` or the 21 tickets. agentview's own code at a5674b4: 1 matching line in the tree, 4 matching lines in the history up to a5674b4 (all in the private repo). Commit messages: 0.
- **Copies:** `/home/tiroir/Projects/ab-replay/agentview-A` (branch `replay-A`) and `agentview-B` (`replay-B`), own `.git`, only remote `origin` = the private repo.
- **Not done / for the owner:** `boss-start` is not on PATH; it is `/home/tiroir/Projects/boss-plugin/skills/boss/bin/boss-start`. The plan's `ab-` track name is not a directory: arm A is `boss-start overview-build-A` run inside agentview-A.

- [x] Clean-ticket script, proven by grep
- [x] Two copies, private repo with `replay-A` / `replay-B`, CI on t-compute proven
- Kwame, 2026-11-05: briefs written at `/home/tiroir/Projects/ab-replay/brief-A.md` and `brief-B.md` (outside every repo; identical except the staffing paragraph and the arm letter; scrub list: no hit). `test.yml`'s pull_request trigger proven: a throwaway PR into `replay-A` ran `test` on `t-compute-3`, 572 tests, green; PR closed, branch deleted, `replay-A` still `b6be213`.
