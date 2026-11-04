# Ticket 19 — second-model verdict (fresh Opus agents, run by Rune)

Codex was not used (out until 23:38). **Codex follow-up is owed on the head that merges.** Diff only, no transcripts. Every citation checked with `grep -F` at the head named.

## Round 1 on 852dd58 — NO-GO
| Sev | Finding | Citation | Check | Answer |
|---|---|---|---|---|
| P2 | `math.isfinite` raises OverflowError on a 10**400 JSON integer; uncaught, it kills the scan | `core:126` `ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0` | VERIFIED | Fixed in 7f4aaf9: `0 <= v < MAX_TOKENS` (1e18); test added |
| P3 | Dedupe by date label misses across DST | `core:650` `history = [h for h in history if day(h["end"]) != label] + [week]` | VERIFIED | Fixed: `abs(h["end"] - wend) >= 86400` |
| P3 | MIN_MESSAGES lets 1–9 all-outside messages pass | `core:492` `elif week["coverage"]["messages"] >= MIN_MESSAGES and ...` | VERIFIED | Intended by the spec ("a quiet week is not a failure") |

## Round 2 on 7f4aaf9 — GO
| Sev | Finding | Citation | Check | Answer |
|---|---|---|---|---|
| — | Both fixes hold; cost() safe for every value usage() returns | `core:133` `return sum(u[k] * COST_WEIGHT[k] for k in COST_WEIGHT)` | VERIFIED | none |
| — | New dedupe cannot drop a different week | `core:646` `history = [h for h in history if abs(h["end"] - wend) >= 86400] + [week]` | VERIFIED | none |
| P3 | A dry run with an existing `pm/` opens (creates/truncates) the empty lock file; the doc says "writes nothing" | `sh:35` `if [ -d "$CFG/pm" ]; then exec 9>"$TRANSCRIPTS_LOCK"; else exec 9>/dev/null; fi`; `md:99` `writes nothing (no directory, no log)` | VERIFIED | Accepted residual: an empty lock file, nothing harmed. Doc wording to "no report, state or log" at the next touch |

Rounds used: 2 of 3. Local tests at 7f4aaf9: 37 passed, imported from `/home/tiroir/Projects/boss-plugin-wt/Rune/routines/boss_efficiency_core.py`.
