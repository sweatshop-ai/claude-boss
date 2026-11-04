# 24: Two open findings from the review of PR 54 (count workers by name)

**What to build:** the two P2 findings left after the third Codex round of PR 54 (verdict: `.scratch/boss-efficiency/reviews/pr54-verdict.md`, raw output `pr54-codex-round3.txt`). Neither concerns security or lost data. Paths are in `routines/boss_efficiency_core.py` at merge `54de129`.

1. **A failed `boss-goal status ... met` still cuts the track** (`core.py:245-246`). `scan_session` records the status when the Bash call is made and never reads its `tool_result`, so a command that fails (missing evidence, wrong track) cuts the track at that time and drops the later time, tokens and messages. Record the mark only when the matching result is not an error; test with a failing result and a succeeding one.
2. **A recipient `Name [ref]` loses its ref** (`core.py:238`). With two live sessions sharing a name, the supported form is `Name [ref]`, but the ref is stripped and `_attribute_by_name` picks by name alone (alive at the message, else nearest). A send to the older session can attribute the newer one. Keep the ref, match it to the session's id, and skip the match when the name is ambiguous and the ref cannot decide. The session start name records no ref, so check what the transcript does hold before designing.

**Why:** both move the weekly "nobody active" and "outside tracked activity" figures: the first shortens a track that is still open, the second moves time to the wrong session.

**Blocked by:**
- 17 (merged)

**Claimed by:** Oskar 2026-11-05 00:28

**Status:** in-progress

- [ ] A `met` mark counts only when its command succeeded, shown by two tests (failed, succeeded)
- [ ] A ref-qualified send picks the session it names, or none when the ref cannot decide; two tests
- [ ] The ticket 17 figures rerun on the fixed head and compared with those in ticket 17
