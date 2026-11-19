# 02: The ticket graph shows what each worker is doing

**Status:** done (PR 173, released 0.30.0; Opus fallback GO, Codex recheck owed after 2026-11-20 14:10)

**Why (2026-11-19, the owner):** the graph shows who holds a ticket, not whether they are working on
it. The session dashboard already shows a sign per worker (a hammer, a flask, a magnifier, a tick);
the same signs belong on the graph.

**Blocked by:** 01

## What it does

- A claimed ticket's second line is `<sign> <worker>`: 🔨 a turn in flight, 🧪 a job of its own
  open, 🔍 a review running (review beats a turn, which beats a job), and the name alone at rest.
- The other states carry the dashboard's signs: `✅ done`, `○ ready`, `⏸ waiting`.
- The signs come from an optional feed: a URL in `pm/goal-graph.signs-url` answering
  `{"signs": {track: {name: "busy"|"watching"|"reviewing"}}}`, read once per process with a 1 s
  timeout. No file or no answer: names without signs, nothing else changes.
- A changed sign is a changed block: the one-minute sweep redraws it.

## Done when

- [x] The fixture block, with the fixture's worker busy, is equal byte for byte to the checked-in file
- [x] A worker at rest has no sign; no feed or a dead one draws no signs; the feed is read once per run
- [x] A sign change rewrites the block through `update`
- [x] Checked live: cross-track drew 🧪 Rocco and 🧪 Kenji from the feed (2026-11-20 00:02)
