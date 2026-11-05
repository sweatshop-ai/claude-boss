# Codex review, claude-boss PR 65, merge 2dd5c82 (first parent as base)

Run 2026-11-05 by Britt for ticket 10. Raw Codex output below, then the answers.

Goes to OpenAI through the Codex CLI (read-only sandbox)
repo:  /home/tiroir/Projects/boss-plugin-wt/Britt-cr2
scope: base 2dd5c82^1
diff:  2 file(s), 81 changed line(s)
files:
  routines/boss_efficiency_core.py
  skills/boss/test_boss_efficiency.py
Codex reads with your user's rights: it can open any file on this machine, not only under /home/tiroir/Projects/boss-plugin-wt/Britt-cr2.
The secret check covers the diff listed above, not what Codex opens on its own.

Concierge questions can be assigned to the wrong track for multi-track bosses, undermining the metric this patch adds. The refusal detection also has a narrow but deterministic false-positive case.

Full review comments:

- [P2] Attribute concierge asks using the boss's active track — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/routines/boss_efficiency_core.py:546-546
  When one boss serves multiple tracks, its socket resolves to a single majority-voted track, so an incoming `ASK` attributes the concierge to that track before name attribution runs; `taken` then prevents reassignment to the boss's actual track window. This summation consequently reports questions on the wrong track and can produce incorrect per-track alerts. Attribute concierge questions from the boss window active when each `ASK` was sent.

- [P3] Require an error before treating a result as a guard refusal — /home/tiroir/Projects/boss-plugin-wt/Britt-cr2/routines/boss_efficiency_core.py:270-271
  When a successful `AskUserQuestion` answer or selected option contains the literal text `Send it to your concierge`, this substring check removes the legitimate question even though the guard did not reject it. Combine the guard-text check with the result's error/rejection status so owner-visible answers cannot decrement the count.

## Answers

Verdict: GO. Class a/b/c/d: 0/1/0/1, both already fixed. Both citations VERIFIED at the merge commit (2dd5c82: line 546 is the concierge `asks` sum, lines 270-271 the `GUARD_REFUSAL` check).

- [P2] `routines/boss_efficiency_core.py:546`, a boss serving two tracks gets its concierge's asks on the one voted track. Class b. Already fixed by PR 70 (904c1d6, ticket 36 item 1: `Index._asked_on` places an `ASK` by the boss's window at that moment). No ticket.
- [P3] `routines/boss_efficiency_core.py:270-271`, an answered question that quotes the guard's words is dropped because `is_error` is not checked. Class d (found by the Opus rounds already; no real transcript showed it). Already fixed by PR 70 (ticket 36 item 5: the line on main reads `b.get("is_error") and GUARD_REFUSAL ...`). No ticket.
