# 26: Owner's choice record, edge cases found in the review of 09b

**Blocked by:** 09b

**Status:** ready-for-agent

Found by the fallback reviews of PR 104, rounds 1 and 2 (Opus, Codex unavailable: usage limit until 8:02 PM; no class a, b or c finding left; round 2 GO). Review files: the `09b-reviews/` directory beside the 09b worktree.

- [ ] Class d: only `test_choose_posts_no_alert` checks the `boss-alert` stub log; the rest of `class Choice` relies on `Base.tearDown`'s PATH and `BOSS_ALERT` guard. Assert the stub's call count in the other `--choose` tests too (the ticket's Tests line asks for each test's stub log).
- [ ] Class d: `test_codex_blocker.py` `same_blockers` compares the count and that no entry starts with `[codex-choice`; make it compare the Codex down entry with `tracker.set_ask(before, "Codex down; owner chose <v>")` so only `ask=` is shown to change.
- [ ] Class d: `test_a_tracker_that_is_not_a_regular_file_of_the_user_is_malformed` covers a missing file only; add a symlink and, where the sandbox allows, another owner for `--choice` and `--choose`.
- [ ] Class d: `--choice` on an unusable tracker writes two stderr lines, the first ("no blocker can be raised: ...") from `usable_tracker` and worded for a raise. Give `usable_tracker` a verb argument or drop one line.
