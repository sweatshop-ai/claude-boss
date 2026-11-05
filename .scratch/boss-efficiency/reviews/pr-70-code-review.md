# PR 70 (ticket 36): review

Name grep on the diff and the commit messages against the scrub list: no hit.
Reviewers: Matt's `code-review` (Standards and Spec, two fresh Opus agents), then one fresh Opus for round 2. Codex owed (out until 09:41).

## Round 1 (on 257fde0)

Standards: no class a, b or c. Class d only:
- the ASK flag lives in a list kept beside `xmsgs` and is matched by timestamp (a fifth tuple field would be tighter);
- `socks.get(sock)` read three times in one comprehension;
- `_asked_on`'s parameter `concierge` names a session dict, and the method is named by what it takes, not returns;
- the read-change-write block of a transcript repeats in three tests;
- `sys.path.insert` inside a test body.

Spec: items 1, 3, 5, 6, 7 built or answered, 4 decided in the ticket, 8 not built, 2 an External blocker with Status waiting.

| # | Class | Finding | Verdict | Handling |
|---|---|---|---|---|
| 1 | b | An `ASK` naming a track (`pm/<track>.md`) on a socket with no vote: `_asked_on` returned None, the time went to `workers[None]`, `Index.tracks()` raised TypeError. Regression against main | VERIFIED (reproduced: `measure_window` raised) | Fixed in 4d11a94: `_asked_on` only for a socket in `socks`. Test added, failed before |
| 2 | b | `_asked_on` took the first boss session that ever served the voted track and was alive at T; two live bosses gave a scan-order-dependent answer | VERIFIED (reproduced, both orders) | Fixed in 4d11a94: the vote stands unless every such boss on a track at T agrees. Test over both orders added, failed before |
| 3 | c | An ASK exactly at a re-register instant goes to the old track (windows inclusive) | VERIFIED, far-fetched | Not built. With the fix the two windows disagree there and the vote decides |
| 4 | c | `T in ask_msgs` matches by timestamp | VERIFIED, far-fetched | Not built |
| 5 | d | the item 3 test hard-codes 30 s | Fixture spacing | Not built |
| d | d | Standards items above, `sys.path.insert` in the test body | | The `sys.path` one moved to module level in 4d11a94; the rest not built |

## Round 2 (fresh Opus, on 4d11a94)

No class a or b. Both round-1 tests fail on 257fde0 (the first with the TypeError, the second on the assertion) and pass on 4d11a94, which the reviewer checked by running the old core from `git archive`; the whole `test_boss_efficiency.py` file passed (85 tests). Class c, not built: a socket owner that moves alpha to beta while another boss that once served alpha sits on gamma gets the ask on alpha (the vote, as the docstring says); an ASK in the very second a boss switches track goes to the voted track.

Rounds: two (under 100 added code lines, round 2 for the class b fixes). Codex owed.

## Citations

Each file:line in this file and in the PR comment was read on the head named there: VERIFIED. None NOT FOUND.
