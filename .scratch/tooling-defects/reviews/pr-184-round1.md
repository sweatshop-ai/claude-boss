# PR 184, round 1 (head f0b9333)

Opus fallback, Codex unavailable (usage limit, `codex-review.sh` exit 7; retry after 2026-11-27 14:15 local).
Code review (standards, spec) and the Opus bug hunt ran once each.

## Opus bug hunt: GO, no P1
- [P2] The printed next step started with a bare `boss_review.py` (not on PATH) and `--track <your track>` (a shell redirect). Fixed: `python3 <absolute path> ... --track T`, and it says pm/T.md must be the caller's own file.
- [P2] A boss parking on a track another live boss is marked with was refused and told to re-register, which would move its own marker. Fixed: only a track no marker names is refused.
- [P2] Between two bosses (old marker reaped, new one not yet registered) a worker's `ci:` park is refused. Kept: nothing would read it, and the refusal tells the worker to ask its boss.

## Spec review
- Same command and other-boss findings as above (fixed).
- `--list` warning reused the refusal wording. Fixed: "no pulse reads these parks".
- An unreadable limit file reports "asks Codex first": that is what the review then does (it asks Codex when the file cannot be read), so kept.

## Standards review
No hard violation. Judgement calls kept: `CLAUDE_CODE_SESSION_ID` read inline as in consent.py, unask.py, boss_store.py.

Codex re-review of the merged head is owed after the limit resets; its findings become tickets.
