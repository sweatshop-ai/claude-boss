# Coverage: premortem risks and Codex findings, by ticket box

Written 2026-10-04 by Birgit for task #100, after tickets 03 to 06 were drafted. Each box is named by its first words in the ticket file under `.scratch/codex-down/issues/`. R-numbers are the owner-accepted premortem (25 risks); "finding N" is Codex review 1 of the plan (`plan-review-codex-1.md`). 01 is Anouk's and is only referred to here, never edited.

| Item | Ticket and box |
|---|---|
| R1 gate unreachable during the outage | No ticket box. The goal file's "Pause when" line holds it: the track stops if Codex is down before 03 lands |
| R2 `boss-run` semantics change | 01: "Characterization tests pin", "A reviewer that hangs", "`boss-run` fails closed" |
| R3 sequential timeouts stall | 01: "The timeout is per reviewer"; 03: "Codex and the fallback have separate timeout constants" (a sleeping Codex stub moves on to the fallback) |
| R4 prompt injection into the verdict | 02: "The brief puts the PR title, body and diff inside a fence" |
| R5 stale SHA posted | 02: "The head SHA is read once with `gh pr view`" |
| R6 round number collision | 02: "The round number is the next free `round<NN>.json`" |
| R7 wrong repo | 02: "`--repo` is required and never inferred"; 04: "`boss_merge.py --repo OWNER/REPO`" |
| R8 leakage in the PR comment | 02: "The comment holds ..." (redaction); 03: the stderr tail goes through that redaction |
| R9 review files readable by others | 02: "Per round, under `$CLAUDE_CONFIG_DIR/pm/reviews/`" (0700/0600, name check) |
| R10 same-family blind spots | 03: "The comment's first line is `Fallback review ...`" (label and the last line); 06: "The recheck" (Codex re-reviews every provisional head) |
| R11 NO-GO read as GO | 01: "Verdict words match as the section above says" |
| R12 Codex error taken for an outage | 01: the closed reason set; 03: "The fallback is passed to 01's chain with `when=...`" (reason carried to the record and the comment) |
| R13 wrong model labelled Opus | 01: `Attempt.model`; 03: "The label's model name comes from 01's `Result.attempts`" |
| R14 deploy check fails open | 04: "The repo holds `.boss/deploy.json`" (allowlist, fail closed, read from the base branch) |
| R15 merge by hand | 04: "`skills/boss/bin/boss-run` gains a built-in hard rule" and "`skills/boss/SKILL.md`: the merge order names `boss_merge.py`" (the limit stated) |
| R16 release on a provisional merge | 06: "`skills/boss/SKILL.md` says: run `boss_recheck.py`" (wrap-up and release stop, `--list` exit codes) |
| R17 re-review of the wrong commit | 06: "02's `boss_review.review(...)` gains two optional parameters" and "`boss_recheck.py --track T --repo ...`" (detached worktree at the SHA) |
| R18 only the first PR re-reviewed | 06: "`boss_recheck.py` ..." (one entry at a time, none stops another) and the three-entry test |
| R19 state in session memory | 06: "When `boss_review.py` records a provisional GO it first writes one line" (tracker section, cross-process test) |
| R20 post-merge NO-GO goes nowhere | 06: "A Codex NO-GO on a merged PR (R20) writes an open blocker first" |
| R21 counts mix or reset | 05: "`skills/boss/codex_health.py` derives the state from `pm/reviews/attempts.jsonl`" (all repos, persistent, two-process test) |
| R22 one success clears | 05: "`policy.py` gains `CODEX_DOWN_AFTER = 3` ... `CODEX_UP_AFTER = 2`", the `codex_health` table tests, and the clearing box |
| R23 duplicate blockers, lost edits | 05: "`tracker.py` gains `update` and `add_line`" (eight processes, one line) and "`boss_review.py --track T` runs `codex_health`" (check and add in one locked update) |
| R24 marker malformed or misplaced | 05: "After the write a test runs `tracker.scan_marker` and `tracker.validate`" (inside `blockers_range`, ladder picks it up at rung 5); 06: the same test for the `fx` blocker |
| R25 tests reach real tools | 02: "Tests use 01's stub-directory harness"; 03, 04, 05, 06: each ticket's closing "Tests use ..." box (PATH guard, call logs asserted) |
| Finding 1 optional fallback | 01: "The fallback is optional"; 02: "It calls 01's chain with Codex only" |
| Finding 2 structured result | 01: "The result is structured as above", "Every attempt keeps its own raw `output`" |
| Finding 3 read-only named and tested | 03: the four "Fallback spec" boxes (flags as `policy.py` constants, `extra_args`, the argv test, `--check-fallback`) |
| Finding 4 replace the absolute sentences | 03: "In `skills/boss/SKILL.md` the sentence ... are replaced by one rule with three cases" (text test: old sentence gone, new wording once) |
| Finding 5 an executable enforcement point | 04: "`boss_merge.py ...` is the one merge path", "The record is the highest-numbered `status: posted` round", "The repo holds `.boss/deploy.json`", the `boss-run` hard rule |
| Finding 6 `boss-run` compatibility | 01: "Characterization tests pin" |
| Finding 7 dependency, counter, scope of "tests alone" | 05: blocked by 02 and 03; "`skills/boss/codex_health.py`" (Codex attempts counted even when the fallback answered); "`boss_review.py --waive ...`" (needs an open blocker, the owner's recorded choice and passing tests); 04: the decision-table row for `waived` and its end-to-end test |
