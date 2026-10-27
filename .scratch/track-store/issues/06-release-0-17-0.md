# 06: Release 0.17.0, the track store

**What to build:** the track store ships. Version 0.17.0 in the plugin manifest,
a CHANGELOG entry naming the empty-`CLAUDE_CONFIG_DIR` fix and the new owner of
`pm/`, and the CONTEXT.md terms (**Track store**, **Boss file**) committed.
Matt's code review, then `/codex-review` for a bug hunt (Opus fallback if Codex
is unavailable), findings fixed or answered, then a PR from `feat/track-store`
to `main` for the owner to merge.

**Blocked by:** 02, 03, 04, 05

**Status:** ready-for-agent

- [ ] Version and CHANGELOG at 0.17.0
- [ ] Code review and Codex (or fallback) review recorded, every finding fixed
      or answered
- [ ] CI green on the PR head
- [ ] PR open, its body naming the bug fixed and the modules moved onto the store
