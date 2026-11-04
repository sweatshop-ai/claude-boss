# Ticket 20, sheaf sender follow-ups: Matt code-review, round 0 (diff 11ae952...5074fa4)

No repo coding standards exist in sheaf; smell baseline only.

## Standards (agent report, condensed)
- Comment above SI_USER... grew to 7 lines; part of it belongs in SPEC. Kept: it corrects a wrong comment.
- Bare -2..-5 in SENDER_CODES unnamed (pre-existing, not touched).
- BLOCKS now bundles platform and capability; LINUX_SIGINFO = sender.BLOCKS alias keeps skip reasons. Fine.
- Literal si_codes in the test are deliberate but undocumented -> fixed: one-line comment added.
- sender_of for -6 said "tkill/tgkill on kernels that mark them", at odds with the new comment -> fixed.
- SPEC said SI_TIMER to SI_ASYNCIO for -2..-5; Linux -5 is SI_SIGIO -> fixed (VERIFIED against the sender.py comment and Linux values: TIMER -2, MESGQ -3, ASYNCIO -4, SIGIO -5).

## Spec (agent report, condensed)
- Finding 1: leave, written in SPEC. Finding 2: gated on linux, tests follow BLOCKS. Findings 4, 5 applied.
- Finding 3 VERIFIED in code: request_stop("signal") force=True never declines (core.py:961, 982); stop_requested written only at core.py:126 and :988, never reset; server._on_stop (:326) starts stop() unconditionally and stop() is guarded by _begun (:334); on_signal keeps the first signal_row (server.py:448). A replay cannot stop a hub with no stop coming; no test. Edge: replay after RESTART_TOLD_TTL turns "upgrade" into "signal" on a hub already stopping (exit reason only).
- Scope creep: SPEC sentence goes slightly beyond "say in SPEC"; mild.

Worst per axis: Standards, SPEC range name (fixed). Spec, same (fixed).
