# PR 60, standards axis (mattpocock-skills:code-review), commit e683298

No documented standards beyond CONTEXT.md and README.md. No hard violations. Judgement calls:

- CONTEXT.md "Flag" entry still reads `CTX-OVER` (overdue): stale glossary.
- routines/ctx_over_measure.py: lock path in the docstring (boss_store owns pm paths); `text_of` shares a name with boss_efficiency_core.text_of but takes content; the tool_result test is written twice (is_worker, scan); a second transcript reader beside the core (needs per-turn arrays); row is a loose dict; 35 appears as RESTART_TURNS and in the prose.
- Speculative generality: none.

# Spec axis

Findings and what was done in the follow-up commit:
- `--days` default was 7 against a 14-day quoted figure: now 14.
- "Overdue" left in CONTEXT.md:56 and policy.py:28: reworded.
- Figures (5 of 32) in the public SKILL.md and CHANGELOG: removed; they stay in tickets 03 and 28.
- Bullet 2 lost its subject "the boss": restored.
- "Ended within 15 turns" is a proxy for reaching the boundary (a worker that finished also ends): stated as a limit of the measure, not changed.
- Only `usage`/`cost` reused from the core, not transcript.py: that module reads a 4 MB tail, the measure needs whole sessions. Kept.
- team/SKILL.md worker-side sentence: follows from the owner's first test; kept.

# Round 1 (Opus) follow-up
F1 off by one at the crossing, F2 ASK regex too loose: fixed with one test each; the measure rerun (5 of 32 unchanged; 4 between became 3, 23 never became 24). F3 team text vs boss rule, F4 unit of "turns": reworded in team and boss SKILL.
