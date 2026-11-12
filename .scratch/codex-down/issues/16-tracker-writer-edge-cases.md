# 16: Tracker writer edge cases

**What to build:** the class c and d findings of PR 92's review round 1 (Opus fallback on f058892, Codex unavailable), which 05a left open. Each box is one finding of `skills/boss/tracker.py` `update` / `add_line` / `mark_cleared` or of its tests.

**Scope:** found 2026-11-12 by Rumi in review round 1 of ticket 05a (PR 92). The finding numbers are round 1's. Findings 1, 2 and the empty-tag half of 4 were fixed in PR 92.

**Blocked by:** 05a (PR 92 merged).

**Claimed by:** Marit 2026-11-12 17:00

**Status:** in-progress

- [x] Finding 3 and round 2's first P3, class c: an `OSError` or a `UnicodeDecodeError` raised by `fn` inside `update` is caught by the writer's `except (OSError, UnicodeDecodeError)` and returned as `failed: <name>`, against the docstring ("an exception from `fn` is not swallowed"). Let only the writer's own I/O be caught; test: an `fn` that raises `OSError`, and one that raises `UnicodeDecodeError`, propagate and leaves the file and the lock as they were.
- [x] Finding 4, class c: `add_line`'s `tag in text` is a substring test over the whole file, so a raw tag that is the prefix of a longer id (`id=ab12cd34` and `id=ab12cd345`; a tag from `marker_tag()` ends in a space and cannot) or text in prose or another section reads as "already there". Decide the rule (match on `marker_tag()`, or on a line in the section) and test the prefix, prose and other-section cases. Round 2 adds a case: a cleared marker stays in the file, so a second raise with the same id returns `done (already there)`, and ticket 10's deterministic `fx<sha1 of repo#N>` id would lose the alert of a second NO-GO on the same PR after the first blocker was cleared. Regrade to class b if 10 keeps that id; either skip cleared lines here or make 10's id per round.
- [x] Finding 5, class c: `mark_cleared` treats a marker with an empty `cleared=` as already cleared, but `validate` treats an empty `cleared` as not cleared, so such a line can never be cleared and the caller gets no signal. Make the two agree; test.
- [x] Finding 6, class c: `add_line` on a CRLF tracker splits on `\n` and inserts the line without `\r`, leaving mixed line endings (`update` itself keeps CRLF). Insert with the file's own line ending; test.
- [x] Finding 7, class d: `test_one_line_and_no_append_lost` has eight adders but only one rename, so it would most likely pass with no lock at all; the lock is proven only by the two lock tests. Make the concurrency test fail without the lock (distinct tags per adder, so every adder renames).
- [x] Round 2, class d: the non-UTF-8 test returns `failed: UnicodeDecodeError` only under a UTF-8 locale (`open()` has no `encoding=`, as the ladder's); pin the encoding or the test's locale. Add a test for an inode-only change (same mtime and size, new inode).
