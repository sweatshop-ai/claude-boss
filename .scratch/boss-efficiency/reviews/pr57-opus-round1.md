# PR 57 (ticket 24): second-model verdict, fresh Opus agent, round 1, head d1ab68a

Codex was out of tokens (back 04:38): a Codex follow-up on PR 57 is owed.

Verdict: GO. No P1 or P2. Tests 64 passed. Six P3, all VERIFIED by synthetic probe, none blocking:

1. VERIFIED core.py:256-268: a compound `boss-goal status X met && git push` whose later part fails loses the mark (per call, not per command); the track then ends at the last done commit.
2. VERIFIED: a `met` whose result never arrives (session killed, result line skipped) records nothing.
3. VERIFIED: a background Bash call gets a non-error "running in background" result, so its mark is kept even if it fails later.
4. VERIFIED core.py:231-233: a ListAgents result before the name attachment loses the ref (name still None); the name hook fires at session start, so not a live risk.
5. VERIFIED core.py:461-462: the holder of the ref, ended inside the slack while another Mira is live, is dropped (`near = live or near`); the send is attributed to nobody.
6. VERIFIED core.py:122-125: refs compared case-sensitively; OWN_REF captures lowercase hex only. Real ref format seen: 6 lowercase hex.
NOT FOUND: crash on non-dict result blocks (guarded); crash on odd recipients; stale `refs` from persisted scans (nothing persisted).

Import path: /home/tiroir/Projects/boss-plugin-wt/Oskar/routines/boss_efficiency_core.py. Probe: session scratchpad, synthetic only.
