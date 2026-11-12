# 20: Codex down blocker, edge cases found in the review of 05c

**Blocked by:** 05c (merged with this PR)

**Status:** ready-for-agent

Found by the fallback review of PR 96, round 1 (Opus on b8a97ce, Codex unavailable; no class a finding). Each is a small box. Review files: `/home/tiroir/Projects/boss-plugin-wt/05c-reviews/`.

- [ ] Class b, for 09 to decide: a blocker the owner cleared by hand is raised again at the next `--track` review while the streak has not grown (health stays down with `failures >= CODEX_DOWN_AFTER`, for instance after a `noverdict`, or a run that logged nothing). 05c's own tests require a re-raise after a hand clear. Decide whether a hand clear holds until the streak grows (a marker of the failure count at the clear), then change code and tests together.
- [ ] Class c: a hand-written marker with an empty `cleared=` is open forever in `codex_blocker` (`validate` returns `cleared=""`, `mark_cleared` leaves it): every "up" sync rewrites identical text and no clear or new raise follows. Make `_classify` and `mark_cleared` agree (see 16, finding 5), test it.
- [ ] Class c: `usable_tracker` checks the path with `lstat` and `tracker.update` reopens it, following a symlink swapped in between. Open the tracker once (`O_NOFOLLOW`) or have `update` refuse a symlink.
- [ ] Class c: `CD_IN_TEXT` is not anchored, so `id=cd` plus 13 digits or `xid=cd...` in another blocker's prose counts as a broken cd line. Anchor it on the marker's own `id=` field.
- [ ] Class d: test the `UNSAFE` cleaning (a `repo` holding `]`, `"`, `[ladder` and a newline gives one valid marker); test a CRLF tracker (raise, classify, clear); drop `test_an_id_on_a_cleared_line_is_never_reused`, which repeats the same-`now` test; test a chain `_Infra` that is not `_Refused` (timeout, unreadable output) runs no sync.
- [ ] Class d: on the findings_block path a failed append says "the attempts of the refused answer are not logged" (`boss_review.py` `_log_refused`) though nothing was refused; say what happened.
