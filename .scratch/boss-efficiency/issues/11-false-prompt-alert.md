# 11: boss-workers-watch reads a concierge's question as a permission prompt

**What to build:** `routines/boss-workers-watch.sh` matches `❯ 1. Yes` on screen. A concierge's question whose first option starts with Yes raises a false `permission-prompt` alert after two runs, then a false recovery. Skip panes with `@worker_role` set to concierge, or read the registry's `waitingFor` instead of the screen.

**Blocked by:** None (can start immediately)

**Claimed by:** Wren 2026-11-04 20:49

**Status:** in-progress

Waits for the merge of PR 48 (sweatshop-ai/claude-boss#48); the boxes are ticked, their evidence is its tests.

- [x] A test with a concierge's question on screen raises no alert
- [x] A worker's real permission prompt still does
