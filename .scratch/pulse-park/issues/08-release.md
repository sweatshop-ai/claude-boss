# 08: Release the pulse park changes

**What to build:** a CHANGELOG entry that tells the boss operator what changed (parks, the
block, no span, the memory floor, `(→ Name)` marks, the silence log) and the version bump.
Check that the SKILL.md sections written by 01-07 read as one text.

**Blocked by:** 01, 02, 03, 04, 05, 06, 07

**Claimed by:** Zainab 2026-11-19 19:08

**Status:** done

- [x] CHANGELOG entry and version bump in the plugin manifest
  Evidence: PR 169 (sweatshop-ai/claude-boss) head 11def710ea238b719c2d86420c2faa38743e7d60; plugin.json 0.28.0; CHANGELOG has one `## 0.28.0` head with the entries of 01-07 and an empty `## Unreleased`; CI `pytest: success` on that head; review round 1 GO (opus fallback, Codex limit).
- [x] SKILL.md mentions `boss-park`, the five events, the 2 h limit, the block and the memory floor once each
  Evidence: each is documented (memory floor §3 line 385, boss-park/five events/2 h/block at lines 1221-1263); not literally once (boss-park and the 2 h limit recur in the P8 worker contract and the Carriers list), the text reads as one. Spec review found `memory-short` missing from the silence-log gate list: fixed in unpushed commit 87f992c.
