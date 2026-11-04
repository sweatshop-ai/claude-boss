# PR 58 (claude-boss), fresh Opus verdict on head 6e12be1

Verdict: GO.

1. Cause: confirmed. First status read at skills/boss/boss-lifecycle.sh:383 (VERIFIED) comes before `t0` at :391 (VERIFIED); the loop at :394 (VERIFIED) checks `SECONDS - t0 < WAIT_IDLE`; the give-up at :399 (VERIFIED) reaches the CI message at :370 (VERIFIED). Correction: bash `SECONDS` counts whole seconds, so the 2 s budget can also run out on a fast runner (measured by the reviewer: `t0=$SECONDS; sleep 1.15` gave a difference of 2 in 2 of 12 runs). A slow read makes it likelier; it is not required.
2. No assertion weakened: skills/boss/test_boss_lifecycle.py:321 and :352 (VERIFIED) can only exit 0 after the third row is read (stub serves one row per read, :192-197 VERIFIED); the 2 s refusal path stays covered by :327, :347, :380, :398 (VERIFIED), unchanged.
3. No missed test: the others need one non-idle read at most (:333, :373, :425, :466-476 VERIFIED) or expect a refusal (:398-401 VERIFIED).
4. Cannot hang: subprocess timeout=60 at :245 (VERIFIED) is above the 30 s budget. Cannot pass for the wrong reason: exit 0 requires the idle row. Both changed tests ran once at nice 19: 2 passed in 8.4 s.
Optional, not blocking: assert `reads == 3` to pin the retry count.
