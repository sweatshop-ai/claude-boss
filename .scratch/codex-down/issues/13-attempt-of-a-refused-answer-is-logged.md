# 13: an attempt whose answer is refused still reaches attempts.jsonl

**What to build:** in `skills/boss/boss_review.py`, when the chain answers `answered` with a verdict but the answer contains a NUL byte, `_follows` (about line 356) refuses it and the run ends in exit 7 before the claim. The attempt is then not appended to `attempts.jsonl`, though box 5 of ticket 02 says every attempt of every run is logged. Log the attempts of a chain result that was refused after the chain ran, without claiming a round (or claim one as `no-verdict`; decide with 05, which counts the attempts).

**Origin:** Opus fallback review 1 of PR #84, head 83a5b50 (finding 3, class c: Codex writing a NUL in its answer is far-fetched). Declined in PR #84, ticketed here.

**Blocked by:** 02 (merged)

**Status:** open
