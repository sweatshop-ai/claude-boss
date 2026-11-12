# 10b: `--list`, the release stop and the SKILL.md text

**What to build:** `boss_recheck.py --track T --list` prints the entries that count and exits 1 when there is one, else 0; `skills/boss/SKILL.md` tells the boss to run the recheck whenever a Codex review answers and at wrap-up, to dispatch on a `DISPATCH` line, and to stop wrap-up and any release request while `--list` exits 1. A release or wrap-up stops while the list holds an entry that counts (the entry of a PR closed without a merge does not).

**Scope:** split out of 10 on 2026-11-12 (Otilia, on Chiara's ruling that accepts Codex spec finding 12 of `plan-review-codex-04-10-11-1.md`). The box below was moved from 10 whole. The recheck it activates, and the merged-head box that also names `--list`, are 10a's: **10b builds the `--list` sentences and tests of 10a's merged-head box** (a closed PR is not counted, an unreadable state counts, `--list` makes no `review(...)` call) together with the box below. 10b reads and writes nothing that `boss_merge.py` owns.

**Blocked by:** 10a (The recheck, the post-merge blocker and its crash resume: `boss_recheck.py` and its `_live_state` handling of a closed PR)

**Status:** ready-for-agent

Trigger and release stop (R16):

- [ ] `skills/boss/SKILL.md` (the Codex routine, "Codex is the external reviewer, twice", :617-640 and after, and Phase E, :1091) says: run `boss_recheck.py` for each repo that has entries whenever a Codex review answers and at wrap-up; on a `DISPATCH` line, dispatch the author or any free worker with the round file as the brief; **wrap-up (Phase E) and any release request (a version bump, a tag, a publish, a reinstall) stop while `--list` exits 1** (the entry of a `CLOSED` PR is not counted, as the merged-head box above says), and the boss tells the owner which PRs. `boss_recheck.py --track T --list` prints the entries and exits 1 when it holds an entry that counts (any entry except one whose PR reads as `CLOSED` without a merge; an unreadable state counts), else 0. A text test finds the trigger, the dispatch rule and the stop; a command test checks both exit codes, a closed-PR-only list among them. `--list` reads each entry's state with `_live_state` (one `gh pr view` per entry), so it makes the same calls the pass does and no `review(...)` call
