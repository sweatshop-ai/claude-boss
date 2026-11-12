# 16: Tracker writer edge cases

**What to build:** the class c and d findings of PR 92's review round 1 (Opus fallback on f058892, Codex unavailable), which 05a left open. Each box is one finding of `skills/boss/tracker.py` `update` / `add_line` / `mark_cleared` or of its tests.

**Scope:** found 2026-11-12 by Rumi in review round 1 of ticket 05a (PR 92). The finding numbers are round 1's. Findings 1, 2 and the empty-tag half of 4 were fixed in PR 92.

**Blocked by:** 05a (PR 92 merged).

**Status:** open

- [ ] Finding 3, class c: an `OSError` raised by `fn` inside `update` is caught by the writer's `except OSError` and returned as `failed: <name>`, against the docstring ("an exception from `fn` is not swallowed"). Let only the writer's own I/O be caught; test: an `fn` that raises `OSError` propagates and leaves the file and the lock as they were.
- [ ] Finding 4, class c: `add_line`'s `tag in text` is a substring test over the whole file, so a tag that is the prefix of a longer id (`id=ab12cd34` and `id=ab12cd345`) or text in prose or another section reads as "already there". Decide the rule (match on `marker_tag()`, or on a line in the section) and test the prefix, prose and other-section cases.
- [ ] Finding 5, class c: `mark_cleared` treats a marker with an empty `cleared=` as already cleared, but `validate` treats an empty `cleared` as not cleared, so such a line can never be cleared and the caller gets no signal. Make the two agree; test.
- [ ] Finding 6, class c: `add_line` on a CRLF tracker splits on `\n` and inserts the line without `\r`, leaving mixed line endings (`update` itself keeps CRLF). Insert with the file's own line ending; test.
- [ ] Finding 7, class d: `test_one_line_and_no_append_lost` has eight adders but only one rename, so it would most likely pass with no lock at all; the lock is proven only by the two lock tests. Make the concurrency test fail without the lock (distinct tags per adder, so every adder renames).
