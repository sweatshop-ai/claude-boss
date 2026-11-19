# PR 170: Opus fallback, Codex unavailable (usage limit, retry 2026-11-20 14:10)

Round 1 on a4fc905. Verdict: **GO**, no P1.

P2 findings and what was done:

- A stray start marker above the block let `_span` replace the text between them: fixed (nearest start
  above the first end, outside fences), test added.
- The error line was not escaped (`<!--` could hide the rest of the page): fixed, test added.
- A claim on a GitHub graph waited up to 30 s or drew a cache under 120 s old: the claim now redraws in
  the background, and `goal_graph.py source` reads the graph again whatever the cache's age.
- The sweep could pass its 60 s timeout with slow GitHub tracks: folders first, TimeoutStartSec=300.
- Check-then-rename window of microseconds against a sheaf save: accepted (sheaf writes atomically).
- `read HH:MM` shows the time of the last change: by design (rule 7 keeps an unchanged block unwritten).
- A ticket caught mid-write costs two writes: accepted.

Codex follow-up owed on the merged diff once the limit resets.
