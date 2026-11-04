# 20: sheaf sender.py follow-ups from the review of PR 195

**What to build:** five Low findings the Opus review of sheaf PR 195 (head 8d03fbc, nightly red on py3.14) left open, in `src/sheafmd/hub/sender.py` and `tests/test_hub_lifecycle.py`. They were not applied in the PR because any production change after the GO would have needed another round. One small PR, one review round. Sheaf is pinned by sha on another track: do not tag.

1. A real stop sent with `rt_sigqueueinfo` or `rt_tgsigqueueinfo` and a negative si_code outside -1..-6 (-7 SI_DETHREAD, -60 SI_ASYNCNL, any other) is logged as `signal-unread` and ignored; before PR 195 it stopped the hub. No ordinary sender does this. Decide: leave, or accept every si_code <= 0 plus SI_KERNEL (the kernel's own SI_FROMUSER test), which lets the garbage seen on 3.14 and 3.11 (negative ints such as -1910714544 and 943711976) through again. The narrow set is the reason the bug is fixed; if anything changes, it needs a probe over the three Pythons first.
2. The si_code numbers are Linux's, but `BLOCKS` is a capability test (`hasattr(signal, "sigtimedwait")`). On FreeBSD (unsupported, SPEC 14.2) SI_USER is 0x10001, so every kill would be dropped. Gate `stopping` on `sys.platform.startswith("linux")` or say in SPEC that only Linux is supported for the siginfo path.
3. Stale siginfo: the unfilled `siginfo_t si` is a C local, so it can still hold an earlier real siginfo from a previous call at the same stack address, a perfect replay that passes the guard. View of Oskar: it can only follow a real signal that was delivered and did not end the hub, and the one place that takes the signal, `on_signal` in `src/sheafmd/hub/server.py:448`, calls `request_stop("signal")` and keeps the first `signal_row`, so a replay asks for a stop that is already asked for. It cannot stop a hub that had no stop coming. Not proven: whether `request_stop` can decline a stop (an upgrade in progress) and the hub then keep running; read that first. A test: deliver a real SIGTERM to a fake `_wait` and then an EINTR-garbage answer carrying the same bytes.
4. The real-senders twin test is parametrized with `sender.SI_USER`, `SI_QUEUE`, `SI_TKILL`, `SI_KERNEL`: a wrong constant would pass its own test. Use the literals 0, -1, -6, 0x80.
5. The comment above `SI_USER, ...` says tgkill and pidfd_send_signal give SI_USER; the kernel gives SI_TKILL for a thread-scoped send. Both are accepted, so only the comment is wrong. Measured here on kernel 7.0: tgkill and tkill from another process read 0.

**Why:** all five are Low and none blocked the merge; finding 3 is the only one where a mistake would stop a hub that should keep running.

**Blocked by:** None (can start immediately)

**Claimed by:** Layla 2026-11-04 22:16

**Status:** in-progress

- [x] Finding 3: read `request_stop` and say whether a replayed stop can reach a hub that had no stop coming, with the code line, and a test if it can
- [x] Findings 1 and 2 decided and written into the PR or the SPEC; 4 and 5 applied
- [ ] One PR, one review round, CI green; no tag
