# Codex review, sheaf PR 195, merge 11ae952 (first parent as base)

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  sheaf-checkout
scope: base 11ae952^1
diff:  2 file(s), 71 changed line(s)
files:
  src/sheafmd/hub/sender.py
  tests/test_hub_lifecycle.py
Codex reads with your user's rights: it can open any file on this machine, not only under sheaf-checkout.
The secret check covers the diff listed above, not what Codex opens on its own.

The new whitelist can consume and ignore valid Linux stopping signals whose sender supplies another permitted negative `si_code`. This can prevent a requested clean shutdown.

Review comment:

- [P2] Accept all valid queued-signal codes — sheaf-checkout/src/sheafmd/hub/sender.py:29-29
  Linux `rt_sigqueueinfo`/`rt_tgsigqueueinfo` and `pidfd_send_signal` can deliver SIGTERM or SIGINT with negative codes outside this tuple, including defined values such as `SI_DETHREAD` (-7) and `SI_ASYNCNL` (-60). `_wait()` consumes such a legitimate stop but records it as `signal-unread`, leaving the hub running until the sender times out or hard-kills it; validity therefore cannot be determined solely by this incomplete whitelist.

## Answers

Verdict: GO. Class a/b/c/d: 0/0/1/0. Citation VERIFIED at the merge commit (11ae952, `src/sheafmd/hub/sender.py:29`, `SENDER_CODES`) and on main (line 34, unchanged).

- [P2] `src/sheafmd/hub/sender.py:29`, the si_code whitelist leaves out other negative codes (`SI_DETHREAD` -7, `SI_ASYNCNL` -60) that rt_sigqueueinfo or pidfd_send_signal can attach to SIGTERM/SIGINT, so such a stop is logged as `signal-unread` and the hub keeps running. Class c: it needs a sender that writes those codes by hand; `kill`, `systemctl stop`, tkill and Ctrl-C all carry listed codes. Not ticketed.
