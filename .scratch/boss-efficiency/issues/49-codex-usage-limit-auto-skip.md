# 49: boss_review skips Codex by itself while its usage limit holds

**What to build:** decision 2 of `/home/tiroir/.claude/plans/2026-11-19-token-review-decisions.md` (owner's choice 2026-11-19: A). When a Codex attempt in `boss_review.py` fails on a usage limit, the reset time Codex names is written to a state file under the reviews dir. Every later review that starts before that time runs as `--opus-direct` does (ticket 52: Codex not started, the labelled fallback straight away) and says so in its round record and comment. At the reset time the skip ends by itself; no flag to turn it on or off by hand. A limit message with no parseable time skips for a fixed one hour and says so.

**Why:** measured 16–19 November: every round tried Codex first, waited for the limit error, then ran Opus; Codex was out until 2026-11-20 14:10.

**Blocked by:** 48 (decision 5A: decisions 3 and 4 first; both change `boss_review.py`)

**Claimed by:** Reem 2026-11-19 16:01

**Status:** done

- [x] Test first: a usage-limit failure with "try again at <time>" writes the state; a review before that time does not start Codex; one after it does — `python3 -m pytest skills/boss/test_boss_review_limit.py` → 21 passed (reem worktree; `boss_review.__file__` = /home/tiroir/Projects/boss-plugin-wt/reem/skills/boss/boss_review.py); tests `test_a_usage_limit_failure_writes_the_reset_time…`, `test_a_review_before_the_reset_time_does_not_start_codex`, `test_after_the_reset_time_codex_is_asked_again…`
- [x] An unparseable limit message skips for one hour, said in the round record — `test_an_unparseable_limit_message_skips_for_one_hour_and_says_so` (record `codex_skipped.parsed=false`, comment `(no reset time in the message: skipped for one hour)`)
- [x] The round record and posted comment say "Codex skipped: usage limit until <time>" — comment head `Fallback review N (<model>, Codex skipped: usage limit until <UTC>; run by <author>)`, record `codex_skipped` (`test_the_round_record_and_the_comment_say_codex_was_skipped`)
- [x] PR merged to main with green CI and one review round — `boss_merge.py` → `merged sweatshop-ai/claude-boss#160 on 220d200 (round 1, provisional)`, merge commit 9075a35, CI `pytest: success` (total_count 1); review: mattpocock code-review once (no hard findings, minors fixed in 220d200) + one Opus fallback round, GO
