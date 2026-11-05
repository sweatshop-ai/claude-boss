# 35: questions asked by the concierge are not counted as questions to the owner

**What to build:** `measure_track` in `routines/boss_efficiency_core.py` counts a track's questions only from boss sessions (`index.bosses`, `s["asks"]`). With a live concierge the guard refuses the boss's own `AskUserQuestion` (`skills/boss/references/concierge.md`), so the concierge asks instead, and the concierge is not a boss session. Questions per day, `asks_per_100M` and the questions alert in the verdict then read zero or too low in the standard workflow, and the weekly report states that as a measurement. Found by Codex on PR 49.

Fix to decide after reading `Index`: the concierge reaches a track by name (the boss's `SendMessage` to it), so it is already in `index.workers` for the boss's window; count `AskUserQuestion` calls of worker sessions inside their windows too (workers lack the tool by design). A question the boss asked itself still counts once; no session is counted twice.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Claimed by:** Tove 2026-11-05 05:16

**Status:** in-progress

- [ ] Test first: a track whose boss asks nothing and whose concierge asks 3 counts 3; a boss that asks 2 and a concierge that asks 3 count 5
- [ ] Show on a real concierge transcript, by path, that attribution reaches the track
- [ ] Say which figures already stated from this count (tickets 04, 17, 24, `~/.claude/pm/` reports) move and by how much
- [ ] Codex round via `/codex-review`; verdict on the PR
