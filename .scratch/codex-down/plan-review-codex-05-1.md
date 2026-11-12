# Spec round 1 of ticket 05 (a dead reviewer becomes an open blocker)

Run by Sana (task #05S of the codex-down track), 2026-11-12. **Codex did not review:** `codex-review.sh exec` stalled past 540 s with no answer (not a usage limit); brief `05-spec-reviews/brief-05-1.md`, empty round file `round-1.md` beside it. The labelled fallback ran in the same turn: a fresh Opus agent, read-only, the same brief. Reviewed: `issues/05-dead-reviewer-blocker.md` after the 2026-11-12 rewrite and `coverage.md`, against main 13c47b0. Verdict: **NO-GO**, 12 findings (1 P1, 11 P2). Because the reviewer was the fallback, Codex has not seen this spec; the code review of the build is where Codex looks again. The Opus agent confirmed that the names on main (`boss_store.valid_track`, `tracker_path`, the `tracker.*` functions, `append_attempts`, the ladder's three environment variables and `--now`, `objective.is_open`, `hermetic.Sandbox`), the `boss-alert` argument shapes, the streak rules against every table test, the counting of a refused `answered` line as a success, `cleared=` before `ask=`, and the privacy of the text all hold. Findings in brief:

1. [P1] The sync trigger "on every path that appended, and on no other" cannot be built: `review()` cannot tell a failed append from a later `.out` or record failure (both exit 7, status None), and `_log_refused` swallows its error.
2. [P2] Health read outside the tracker lock can reopen a blocker that was just cleared.
3. [P2] A blocker could be raised with no failure streak behind it (down state kept after one answer, blocker hand-cleared).
4. [P2] A broken `cd` marker blocks raising and clearing, and whether `clear` is posted is unspecified.
5. [P2] `now` and `when` must carry a UTC offset; a naive one makes the ladder call the marker malformed.
6. [P2] The harness is described wrongly: `Base` stubs only `claude`, and `boss-alert` is the absolute `BOSS_ALERT`, not on PATH.
7. [P2] The ladder test gives a wrong reason for `BOSS_LADDER_STATE`, and "no boss session was involved" has no observable.
8. [P2] "Up to 3 retries" against "changed 3 times" is ambiguous; the temp file prefix is not named.
9. [P2] `track` cannot be "last": 10 adds `head_sha` beside it.
10. [P2] One outage gives one blocker per track; the ticket did not say so, nor that no `track` means no sync.
11. [P2] The coverage.md R23 row was broken by the note inserted inside `str \| None`; the R25 row still says `tracker_add` is moved.
12. [P2] Ticket size: 05 is more than one session; split into 05a (tracker writer), 05b (policy and `codex_health`), 05c (`track`, raise, clear, ladder test).

## Settled (Sana)

| # | Disposition | Where |
|---|---|---|
| 1 | Accepted. The sync runs once the chain has returned, whether or not the append succeeded, after `_keep_and_post` in any status (a round left empty included) and after `_log_refused`; it only reads, so an extra one is harmless. Test added for a round left empty. | 05, `track` box |
| 2 | Accepted. `health()` is called inside `fn`, under the tracker lock; a test flips the state between the first read and the locked step. | 05, raising box |
| 3 | Accepted. A blocker is raised only when `failures >= CODEX_DOWN_AFTER`; test: hand-cleared blocker, one answer, no new line. | 05, raising box |
| 4 | Accepted. The broken case is defined by `has_marker` plus `id=cd` and twelve digits; `clear` is posted only when `update` returned `done`; test: only a broken line, two runs, zero `clear` calls. | 05, raising and clearing boxes |
| 5 | Accepted. `now` and `when` are timezone-aware; a naive value is a `ValueError`, one test each. | 05, tracker box and raising box |
| 6 | Accepted. Every test that can raise or clear sets `BOSS_ALERT` to the `boss-alert` stub's path, asserts its call log and fails if unset; the eight-process test asserts exactly one `0` call. The harness sentence is corrected. | 05, tests box |
| 7 | Accepted. Reason reworded (the default follows `CLAUDE_CONFIG_DIR`; set explicitly); the observable is "exactly one call, `5 <text>`, and no `CLAUDE_CODE_SESSION_ID` in the child's environment". | 05, ladder box |
| 8 | Accepted. At most 3 tries in all, as the ladder; the test asserts `fn` was called 3 times; prefix `.boss-tracker-`. | 05, tracker box |
| 9 | Accepted. "Keyword-only, default `None`", and "last" dropped. | 05, `track` box |
| 10 | Accepted. One blocker per track that runs a review with `--track` is stated as intended; no `track` means no sync. | 05, `track` box |
| 11 | Accepted. R23's cell repaired with the note after the closing quote; R25 now says `boss-jev.py` is gone and `update` and `add_line` are new in `test_tracker.py`. | coverage.md |
| 12 | **Not applied; the call is Chiara's.** The dispatch asked for the spec brought up to date, not re-cut, and splitting renumbers tickets that 06, 09, 10 and `coverage.md` cite. Recommendation: split off the tracker writer as its own ticket only if the build worker wants it, since 06 and 10 need only `update` and `add_line` and nothing blocks them, not even 08. | Chiara, report |

Not done: a second round. The fixes are the reviewer's own proposals; there is no second Codex round because Codex stalled once and the code review of the build is where the ticket is looked at again.
