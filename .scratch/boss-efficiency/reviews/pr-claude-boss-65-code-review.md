# PR 65 (ticket 35): reviews

Heads: 89376bb (round 0), 7dde8cd (after Opus round 1), 3e98205 (after Opus round 2). Codex was out of tokens until 09:41 (runner exit 7); a fresh Opus stood in for it. **Codex owed.** No transcript text went to any reviewer: code and numbers only. Name grep of the diff: no hit.

## Standards (Matt's code-review, fresh agent, on 89376bb)

No hard violations. Four judgement calls, all class d: capital `T` loop variable (the boss loop below uses it too), the repeated `sum(1 for ... if a <= T < b)` one-liner, repeated setup across the three tests, magic offsets in the tests. Left as they are: they match the file.

## Spec (Matt's code-review, fresh agent, on 89376bb)

No scope creep, nothing implemented wrongly. Open at that time: real-transcript proof and moved figures (in the PR body), Codex round (this file). Two notes:
- The clip test ends its window at +50 s; the helper puts asks at +60, +120, +180 s, so it tests the clip. VERIFIED (skills/boss/test_boss_efficiency.py, `Cfg.session`).
- Concierge wait time is still not credited to `states["ask"]` (lines 543-546 read boss sessions only). Not asked by the ticket. Follow-up.

## Opus in place of Codex (fresh agent, attacking attribution and double counts, on 89376bb)

| # | Class | Finding | Verdict | Handling |
|---|---|---|---|---|
| 1 | a | A boss `AskUserQuestion` refused by the guard stays in its transcript and counted, so one question counted twice once the concierge asked it | VERIFIED (reproduced: boss 1 refused ask + concierge 1 ask gave 2) | Fixed in 7dde8cd: `scan_session` drops an ask whose tool_result is an error. Test added. On the real pair the figure moved 6 to 5 (wrongly, see round 2) |
| 2 | a/b | Any named session in a worker window counted as an asker (interactive and peer sessions have the tool) | VERIFIED (reproduced: peer with 4 asks gave 4) | Fixed in 7dde8cd: only a session that was sent `ASK <id>:` counts. Test added. Still 5 on the real concierge |
| 3 | b | A boss serving two tracks: the concierge is placed by the boss-socket vote (one track), so its asks land on the voted track | VERIFIED by reading `Index.__init__` lines 427-434; reproduced by the reviewer. Time and tokens were already placed this way before this PR | Not fixed here. Follow-up ticket |
| 4 | b | First weekly run after deploy compares a concierge week measured under the new rule with the stored old-rule week (near zero), so the questions alert may fire once | NOT FOUND by experiment (read from code, `judge` and `FLOOR_TOKENS`) | Not fixed here. Follow-up: version the history or skip `asks` for one week |

Checked and clean (reviewer): no double count across workers and bosses (`boss_sids` excluded from both worker paths), across tracks, or across overlapping windows of one session; half-open window clipping is the same as in the boss loop; a reused name only reaches sessions alive within `NAME_SLACK_S`.

A concierge never falls outside every track: the boss addresses it by name, so name attribution covers it while both are alive. On the real boss and concierge pair, by path, under the lock: workers `[('Signe', 18469)]`, asks 0 before the fix, 6 after (3e98205).

## Opus round 2 (fresh agent, on 7dde8cd)

| # | Class | Finding | Verdict | Handling |
|---|---|---|---|---|
| 5 | b | Any `is_error` result dropped an ask, so a question the owner saw and dismissed (Escape) was not counted; a boss CONSENT question escaped by the owner counted before and no longer did | VERIFIED (reproduced). It also explains the 6 to 5 on the real pair: the dropped call was in the concierge's session, which the guard never refuses | Fixed in 3e98205: drop only a result carrying the guard's reason ("Send it to your concierge"). Test added; real pair back to 6 |
| 6 | c | The `ASK` body slice began at the first `>` of the text, not after the tag | VERIFIED in a weaker form; the prefixed record was not reproduced | Fixed in 3e98205 (`find(">", f.end())`) |
| 7 | c | A tool_result before its tool_use is ignored | NOT FOUND (needs a reordered file) | Left |

Checked clean by round 2: equal timestamps, false-positive and false-negative concierge flag, windows that began before the flag.

Round 2 had a class b finding, fixed in 3e98205 (18 lines more, 82 in all). A round 3 on that delta is for Anton to call.
