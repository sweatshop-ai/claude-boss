# sheaf PR 196, Opus round 1 on head a0f8d03: GO (Codex follow-up owed from 23:38)

- Gate cannot drop a real stop on Linux: BLOCKS adds a term that is always true on Linux; it is the only switch for the mask and open_to_signals. VERIFIED (sender.py:35).
- Finding 3 citations: core.py:961 force=True VERIFIED; core.py:982 decline (return False on 983) VERIFIED; stop_requested written only at core.py:126, :988 VERIFIED; server.py:326 _on_stop unconditional VERIFIED; server.py:334 _begun guard VERIFIED; server.py:448 first signal_row kept VERIFIED. Replay after RESTART_TOLD_TTL changes only the exit reason.
- Tests: 14 passed (-k siginfo/real_stopping/watcher_takes).
- Low (comment): reviewer reasoned from kernel source that tgkill/tkill give SI_TKILL, not SI_USER; could not probe. Answer, measured by me on kernel 7.0.0-2022 (x86_64): raw syscall tgkill(234) and tkill(200) from another process, read with sigtimedwait: si_code 0 for both. The comment stands. Behaviour unaffected either way (0 and -6 both accepted).
- Nit: the decline is at 983 (return False), 982 is the condition.
