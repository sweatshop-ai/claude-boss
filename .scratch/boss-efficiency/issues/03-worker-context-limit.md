# 03: A limit on worker context that holds

**What to build:** find out why `CTX-OVER` at 250k does not stop workers, and make it hold where a restart pays: more than about 35 turns left.

**Why:** 77% of workers pass 150k and 38% pass 250k. A turn costs 19k units at 100-150k of context, 39k at 250-400k, 53k above 400k. A restart costs about 425k units of orientation, so it pays after about 35 turns. Upper bound on the saving: 14% of tokens.

**Decided by Thierry, 2026-11-05:** both tests together ("1 & 2"), for a worker past 250k:

- Waiting on CI or merging, with the PR open: never restart.
- Anything else, fixing findings from a review round included: the boss asks the worker how much is left, and restarts at the next boundary if that is more than about 35 turns. On review fixes the estimate wins over the list; the new session picks up the findings from the handoff.

Not a decision, already true of `restart` (`skills/boss/SKILL.md`, "Session age"): a worker whose turn is over and who waits on CI with a Monitor is not finished. It reads `shell` and the restart is refused.

**Blocked by:** None (can start immediately)

**Claimed by:** Aurelio 2026-11-05 00:53

**Measured, 2026-11-05** (`routines/ctx_over_measure.py`, 14 days, 371 worker sessions): 32 past 250k (9%). Asked for a boundary after the crossing: 5 of 32 (16%); 3 more were asked between 150k and 250k only; 24 never. All 5 asked ended within 15 turns of the ask (median 8). Turns left at the crossing: median 30; more than 35 in 14 of 32. Share of worker cost above 250k: 9%.

**Why 9% here and 38% in the audit** (checked 2026-11-05, same transcripts, three definitions, `routines/ctx_over_measure.py` and a scratch variant): the window. Over the audit's span, 35 days from 2026-10-01, 731 worker sessions: 71% past 150k and 29% past 250k (the audit: 77% and 38%). Over the last 14 days: 59% and 9%. The older 21 days hold far more long workers. Definition does not matter: a dispatch anywhere in the file instead of in its first 256 KB moves 731 to 738 sessions and changes nothing; peak context as cache-read alone (the audit's `msgs` field) instead of input + cache write + cache read moves the 35-day count by 0 to 4 sessions. What I cannot reproduce is the audit's last 8 points (29% against 38%): the audit counted the 30 most recent tracks and attributed sessions by dispatch wording as well as by message, which is not the same population as every worker session in the window. Read the 9% as the recent window, not as the audit's number corrected. Why recent workers pass 250k less is not measured here.

**Same measure over the 35 days** (731 worker sessions): 210 past 250k; 28 asked after the crossing (13%), 10 asked between 150k and 250k only, 172 never; of the 28 asked, 17 ended within 15 turns (61%), median 15 turns after the ask; turns left at the crossing median 50, more than 35 in 126 of 210 (60%); 32% of worker cost spent above 250k. The "all 5 ended" of the 14-day window is a small sample: over 35 days asking ended 17 of 28 within 15 turns.

**Why `CTX-OVER` did not stop workers:** nothing enforces it and the boss did not act on it. `policy.flag_for` is called only from `boss-panes.py` (`flags_of`), which puts the word in the `list` row; no pulse, hook or script reads it or sends anything. The wording said "ask now" but the boss has to read the row and write the message, and it did in 16% of the cases. Asking helps but is not a guarantee: 5 of 5 ended in 14 days, 17 of 28 in 35. No code change: the rule is in SKILL.md.

**Status:** done (PR 60 merged, 482b0e4)

- [x] Measured: of the workers past 250k, how many the boss asked for a boundary, and what happened
- [x] The rule states when not to restart a worker near the end of its task
- [ ] Share of worker cost above 250k, before and after, on the same measure. Moved to ticket 28 (waiting on time): the "before" is stated there, the "after" is read there.

**Left from review (class c, round 3 GO on 717b402):** the SKILL.md and team text say "each tool call is its own turn"; parallel calls in one message count once, as the script and the cost figures do. A 134-character line in SKILL.md and the script's docstring naming words the regex does not match. Fix with the next edit to "Session age".
