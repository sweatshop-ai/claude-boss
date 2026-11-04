# 24: Two open findings from the review of PR 54 (count workers by name)

**What to build:** the two P2 findings left after the third Codex round of PR 54 (verdict: `.scratch/boss-efficiency/reviews/pr54-verdict.md`, raw output `pr54-codex-round3.txt`). Neither concerns security or lost data. Paths are in `routines/boss_efficiency_core.py` at merge `54de129`.

1. **A failed `boss-goal status ... met` still cuts the track** (`core.py:245-246`). `scan_session` records the status when the Bash call is made and never reads its `tool_result`, so a command that fails (missing evidence, wrong track) cuts the track at that time and drops the later time, tokens and messages. Record the mark only when the matching result is not an error; test with a failing result and a succeeding one.
2. **A recipient `Name [ref]` loses its ref** (`core.py:238`). With two live sessions sharing a name, the supported form is `Name [ref]`, but the ref is stripped and `_attribute_by_name` picks by name alone (alive at the message, else nearest). A send to the older session can attribute the newer one. Keep the ref, match it to the session's id, and skip the match when the name is ambiguous and the ref cannot decide. The session start name records no ref, so check what the transcript does hold before designing.

**Why:** both move the weekly "nobody active" and "outside tracked activity" figures: the first shortens a track that is still open, the second moves time to the wrong session.

**Blocked by:**
- 17 (merged)

**Claimed by:** Oskar 2026-11-05 00:28

**Status:** done (PR 57 merged, f9c27a6)

- [x] A `met` mark counts only when its command succeeded, shown by two tests (failed, succeeded)
- [x] A ref-qualified send picks the session it names, or none when the ref cannot decide; two tests
- [x] The ticket 17 figures rerun on the fixed head and compared with those in ticket 17

## Result (PR 57, head d1ab68a; per-track detail in `~/.claude/pm/boss-efficiency.rerun-2026-11-05b/report.md`)

- **Failed `met`:** the mark is kept when the Bash call's result is not an error. Not recorded: a `met` whose result never arrives, or inside a compound command whose later part fails (the track then ends at its last done commit). A background `met` always marks.
- **`Name [ref]`:** the transcript records a session's ref only in its own ListAgents result ("This session is Name [ref]", 6 lowercase hex, not derived from the session id). With several sessions alive under the name, the one holding the ref is picked; a session that holds another ref is skipped; with no holder none is counted. A session that never ran ListAgents cannot be told apart, so those sends are skipped rather than guessed.
- **Rerun** (same 10,030 sessions, window to 2026-11-05 00:02, compared with the ticket 17 rerun on the merged code): nobody active on the audit tracks 34.1% (612 of 1,798 h), unchanged from 34.1% (612 of 1,798 h); outside tracked activity 0.3% (13 of 3,743), was 0.4% (14 of 3,742); 14 tracks cut at their last mark, as before. All tracks: 37.7% and 0.5%, as before. No figure moved by more than 0.1 point. The audit list holds 28 tracks with activity in the window, not 30.
- **Review:** code-review round 0 and a fresh Opus verdict (GO, six P3 edge cases above); Codex follow-up owed, Codex out until 04:38.

## Accepted residuals (the six P3 of the Opus verdict, none gives a wrong figure on a realistic track)

1. `boss-goal status X met && cmd` with a failing second part loses the mark; the boss runs `met` alone, and the track then ends at its last done commit.
2. A `met` whose result never arrives records nothing.
3. A background `met` always marks.
4. A ListAgents result before the name attachment loses the ref; the name hook fires at session start.
5. The holder of a ref that ended inside the slack is dropped while another session of the name is live.
6. Refs are compared case-sensitively; the refs seen are 6 lowercase hex.

Codex follow-up on PR 57 is owed (Codex out until 04:38).

**Correction:** the audit list holds 28 tracks with activity in the window, not 30; the figures of ticket 17 and above say "30 tracks" for the same list.
