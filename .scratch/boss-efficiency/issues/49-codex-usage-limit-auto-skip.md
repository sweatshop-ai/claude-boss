# 49: boss_review skips Codex by itself while its usage limit holds

**What to build:** decision 2 of `/home/tiroir/.claude/plans/2026-11-19-token-review-decisions.md` (owner's choice 2026-11-19: A). When a Codex attempt in `boss_review.py` fails on a usage limit, the reset time Codex names is written to a state file under the reviews dir. Every later review that starts before that time runs as `--opus-direct` does (ticket 52: Codex not started, the labelled fallback straight away) and says so in its round record and comment. At the reset time the skip ends by itself; no flag to turn it on or off by hand. A limit message with no parseable time skips for a fixed one hour and says so.

**Why:** measured 16–19 November: every round tried Codex first, waited for the limit error, then ran Opus; Codex was out until 2026-11-20 14:10.

**Blocked by:** 48 (decision 5A: decisions 3 and 4 first; both change `boss_review.py`)

**Status:** ready-for-agent

- [ ] Test first: a usage-limit failure with "try again at <time>" writes the state; a review before that time does not start Codex; one after it does
- [ ] An unparseable limit message skips for one hour, said in the round record
- [ ] The round record and posted comment say "Codex skipped: usage limit until <time>"
- [ ] PR merged to main with green CI and one review round
