# 13: an attempt whose answer is refused still reaches attempts.jsonl

**What to build:** in `skills/boss/boss_review.py`, when the chain answers `answered` with a verdict but the answer contains a NUL byte, `_follows` (about line 356) refuses it and the run ends in exit 7 before the claim. The attempt is then not appended to `attempts.jsonl`, though box 5 of ticket 02 says every attempt of every run is logged. Log the attempts of a chain result that was refused after the chain ran, without claiming a round (or claim one as `no-verdict`; decide with 05b, which counts the attempts).

**Origin:** Opus fallback review 1 of PR #84, head 83a5b50 (finding 3, class c: Codex writing a NUL in its answer is far-fetched). Declined in PR #84, ticketed here.

**Blocked by:** 02 (merged)

**Status:** done

**Decision** (Piotr, 2026-11-12): no round is claimed and the exit stays 7. The attempts of the refused result are appended to `attempts.jsonl` with `"round": null` (05b reads `reviewer` and `reason`, which are present). Only the NUL refusal is covered: a result `_sound` takes once NULs are removed. Other inconsistent results say nothing trustworthy about Codex and are still not logged.

- [x] a chain answer refused for a NUL reaches `attempts.jsonl` (reviewer, reason, exit_code, `round` null), exit 7, no round file, no comment. Evidence: `test_an_answer_refused_for_a_nul_is_exit_seven_with_nothing_claimed_and_its_attempt_logged` (both NUL cases moved out of the "nothing written" table); CI is the gate.
