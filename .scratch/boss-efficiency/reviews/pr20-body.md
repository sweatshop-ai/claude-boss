Five Low follow-ups from the review of #195 (no tag; sheaf is pinned by sha elsewhere).

1. **Left as is.** The narrow si_code set is why the 3.14 bug is fixed; a stop sent with `rt_sigqueueinfo` and an odd negative code is logged `signal-unread`. Written into SPEC 8.4.
2. **Linux only.** `BLOCKS` now requires `sys.platform.startswith("linux")` (FreeBSD's SI_USER is 0x10001); SPEC 8.4 says so; the tests' `LINUX_SIGINFO` follows `sender.BLOCKS`.
3. **No change, no test.** A replayed stop cannot reach a hub with no stop coming: `request_stop("signal")` takes `force=True` and never declines (`core.py:961`, decline only at `:982` for an upgrade); `stop_requested` is written only at `core.py:126` and `:988` and never reset; `_on_stop` (`server.py:326`) starts the stop unconditionally and `stop()` is guarded by `_begun` (`:334`); `on_signal` keeps the first row (`server.py:448`). Only effect: a replay after `RESTART_TOLD_TTL` turns an "upgrade" stop into "signal" on a hub already stopping (exit reason).
4. The twin test uses the literals 0, -1, -6, 0x80.
5. The SI_TKILL comment corrected (tgkill and tkill from another process read 0 on kernel 7.0).

Tests: the 14 that touch this ran locally on 3.14; the rest in CI.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
