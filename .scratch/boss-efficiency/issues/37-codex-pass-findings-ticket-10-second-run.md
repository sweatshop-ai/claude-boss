# 37: Findings of the second Codex pass on the merged PRs (ticket 10)

**What to build:** Codex, run once on the merged diff of each PR (2026-11-05, Britt, after its limit reset at 09:41), found the items below. Each is a ticket-sized fix, not a revert; none is fixed here. Raw output and the answers are in `.scratch/boss-efficiency/reviews/pr-<repo>-<n>-codex.md`. Class: a security property broken, data loss, wrong behaviour on a normal path; b wrong behaviour on an unusual realistic path; c far-fetched; d tests, docs, style. Citations were checked against current main.

**Blocked by:** None (can start immediately)

**Claimed by:** none

**Status:** ready

- [ ] b. PR 71, `skills/boss/SKILL.md:739`: the `boss-unask record` example uses a heredoc with the fixed delimiter `EOF`; a question or owner wording with a line that is exactly `EOF` ends it early and the rest of the report text runs as shell. VERIFIED on main. Use framing that cannot collide (a delimiter checked absent from the content, or stdin from a file).
- [ ] b. PR 71, `skills/boss/unask.py:81`: `read_text()` raises `UnicodeDecodeError` on a torn multi-byte record (an interrupted append), before the per-line skip runs; `boss-unask list` and `owner_reports()` in the weekly routine then fail until the file is repaired. VERIFIED on main and reproduced (`UnicodeDecodeError` from `unask.read`). Read bytes and decode per line with `errors="replace"`, or skip lines that do not decode.
