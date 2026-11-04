# Opus fallback review 2 (run by Amara) — PR 49

Codex was not used; fresh Opus agents reviewed the diff only (no transcripts, no real data). **Codex follow-up is owed on the head that merges.** Every citation checked with `grep -F` against the source at the head named: all VERIFIED (none NOT FOUND).

## Round 2 on 46b43e5 — no P1; 2 P2 (fixed in 021b0f2)

| # | Sev | Finding | Citation | Check | Answer |
|---|---|---|---|---|---|
| 1 | P2 | Subagent-transcript loop: only `json.loads` guarded; a non-object line or bad timestamp escapes `scan_session` and loses the week | `core:240` `if d.get("type") == "assistant":`; `:243` `if d.get("timestamp") and s0 is None: s0 = ts(d["timestamp"])` | VERIFIED | Fixed: whole body guarded, counted in `skipped`. Test `test_malformed_subagent_lines_are_skipped_not_fatal` |
| 2 | P2 | A failed socket lookup exits 0 and saves a bad baseline | `core:318` `if sock in socks: continue`; `:477` `if week["coverage"]["messages"] == 0:` | VERIFIED | Fixed: `FAIL_UNCOVERED = 0.90`, week fails and is not added to history. Test added |
| 3 | P3 | `skipped`/`unreadable` never surfaced | `core:204` `out["skipped"] = skipped` | VERIFIED | Fixed: total printed to stderr |
| 4 | P3 | String token count crashes `cost` | `core:227` `out["msgs"] = sorted(...)` | VERIFIED | Fixed: `usage()` coerces |
| 5 | P3 | DRY_RUN=1 still runs mkdir/log rotation | `sh:24` `mkdir -p "$ROUTINES/state" "$ROUTINES/logs" "$CFG/pm"` | VERIFIED | Open → ticket |
| 6 | P3 | `timeout` without `-k`; idle ionice can hit the cap | `sh:39` `timeout 3600 nice -n 19 ionice -c3 python3 "$CORE" "$@"` | VERIFIED | `-k 30` added; ionice/cap left as is |
| 7 | P3 | `__pycache__` written into the plugin dir | `core:43` `sys.path.insert(0, str(PLUGIN / "skills" / "boss"))` | VERIFIED | Fixed: `python3 -B` |
| 8 | P3 | Reruns of one week stack in history (dedupe on exact float) | `core:627` `history = [h for h in history if h["end"] != wend] + [week]` | VERIFIED | Open → ticket |
| 9 | P3 | Memory per week not measured | `core:144` `recs, tools, notif, msgs = [], {}, {}, {}` | VERIFIED | Open → ticket |

Answers asked: success on a failed/empty scan: only via finding 2 (fixed). Writes landing in the repo: only `__pycache__` (fixed). Safe under load: nice 19, ionice idle, flock 7200 s + cap 3600 s = 3 h under `TimeoutStartSec=4h`, scoped glob, no tree-wide grep. Round 1 fixes: all hold; finding 1 was the same bug in the subagent loop.

## Round 3 on 021b0f2 — no P1/P2 open

| # | Sev | Finding | Citation | Check | Answer |
|---|---|---|---|---|---|
| 1 | P3 | Early `return None` drops `skipped` of a zero-record file | `core:209` `if not recs: return None` | VERIFIED | Open → ticket |
| 2 | P3 | `FAIL_UNCOVERED` has no minimum sample: 1–3 worker messages all outside gives 100% and fails | `core:486` `elif week["coverage"]["share"] > FAIL_UNCOVERED:` | VERIFIED | Open → ticket (a quiet week alerts, loudly, it does not pass) |
| 3 | OK | `None` share cannot reach the `elif` | `core:484` `if week["coverage"]["messages"] == 0:` | VERIFIED | none |
| 4 | P3 | NaN/inf/negative still pass `usage()` (not new) | `core:121` `return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0` | VERIFIED | Open |
| 5 | P3 | Subagent cost assertion repeats the code under test | `test:181` `self.assertEqual(rec["subs"][0]["cost"], core.cost(core.usage(good["message"]["usage"])))` | VERIFIED | Open |
| 6 | P3 | No boundary test at 90% | `test:299` `def test_a_week_with_no_socket_ties_fails_instead_of_becoming_a_baseline` | VERIFIED | Open |
| 7 | — | Total lookup failure may give `messages == 0` (old fail) instead of a high share; reviewer did not trace `Index` | `core:437` `for T in index.worker_msgs.get(track, []):` | VERIFIED (snippet); behaviour not checked | Open |
| 8 | OK | Shell change correct | `sh:39` `timeout -k 30 3600 nice -n 19 ionice -c3 python3 -B "$CORE" "$@"` | VERIFIED | none |

Both new tests fail against the old code (reviewer's reading; I did not run them against it).

**Rounds used: 3 of 3 (round 1 by Bilal, 2 and 3 by Amara).** Open P3s become tickets; no security or lost-data item is open. Local tests at 021b0f2: 33 passed, imported from `/home/tiroir/Projects/boss-plugin-wt/Bilal/routines/boss_efficiency_core.py`.
