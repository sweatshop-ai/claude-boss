# Handoff Otilia, 2026-11-26: claude-boss 0.32.0 released

- Release commit b9c93f95b3d1cf6f350f42884c2d1eb59d61aaad on main: `.claude-plugin/plugin.json` 0.31.0 -> 0.32.0 and CHANGELOG `## Unreleased` -> `## 0.32.0`. The marketplace entry (sweatshop-ai/cc-agent-names) carries no version, so plugin.json on main is the release.
- Carries PR 184 (a park on a track no boss marker names is refused; a refused `--opus-direct` prints the runnable review) and PR 182 (the merge gate refuses a head whose CI is not complete and green, on every path).
- `branch_deploys.py` on main: tests only, no deploy line. Pushed directly.
- Local install: `claude plugin marketplace update sweatshop-ai` then `claude plugin update claude-boss@sweatshop-ai`: 0.31.0 -> 0.32.0.
- `boss-version-gap` after the update: released and installed agree; live sessions started before the update still run 0.31.0 until they restart.
- The track that asked for it (ml-build-4) is closed; its state line names what stays open.
- No background task running.
