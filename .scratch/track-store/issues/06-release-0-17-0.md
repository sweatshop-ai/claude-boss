# 06: Release 0.17.0, the track store

**What to build:** the track store ships. Version 0.17.0 in the plugin manifest,
a CHANGELOG entry naming the empty-`CLAUDE_CONFIG_DIR` fix and the new owner of
`pm/`, and the CONTEXT.md terms (**Track store**, **Boss file**) committed.
Matt's code review, then `/codex-review` for a bug hunt (Opus fallback if Codex
is unavailable), findings fixed or answered, then a PR from `feat/track-store`
to `main` for the owner to merge.

**Blocked by:** 02, 03, 04, 05

**Claimed by:** Elske 2026-10-27 12:39

**Status:** done

- [x] Version and CHANGELOG at 0.17.0
- [x] Code review and Codex (or fallback) review recorded, every finding fixed
      or answered
- [x] CI green on the PR head
- [x] PR open, its body naming the bug fixed and the modules moved onto the store

**Waiting on:** the owner (Thierry) merges PR #32

**Evidence:**
- `.claude-plugin/plugin.json` 0.17.0 and CHANGELOG 0.17.0 entry (only manifest with 0.16.0); `git show origin/main:.claude-plugin/plugin.json` still 0.16.0 before ready
- Reviews in /home/tiroir/Projects/boss-plugin-wt/track-store-06-reviews/, posted on PR #32: Matt code-review (issuecomment-6441001003), Codex 1 (-6441111456, 2 real findings fixed), Codex 2 (-6441201847, 1 fixed, 1 answered), Codex 3 no findings
- CI: head 3f1439d, `gh api .../commits/3f1439d.../check-runs`: total_count 1, pytest success (the run on fcbd307 failed on test_boss_lifecycle, fixed test-only, see -6441366396)
- PR #32 ready (isDraft false), body names the bug and the modules moved
