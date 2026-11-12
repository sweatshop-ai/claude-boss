# 28: Tracker writer, edge cases found in review of 16 (class c and d)

**What to build:** the findings of Opus fallback review 1 on PR 107 (Codex was out of tokens) that were graded class c or d and filed instead of fixed.

**Blocked by:** 16 (Tracker writer edge cases)

**Status:** ready-for-agent

- [ ] **A prose line holding the tag counts as "already there" (class c).** `add_line` (`tracker.py`, `there`) takes any line of the section that holds the tag and has no marker as present, so a note `- resolved id=ab12cd34, see PR 90` in `## Open blockers` hides a new blocker with that id; a malformed marker holding the tag does the same. The docstring says prose does not count. Decide (count only lines with a readable marker, or document it) and test. No production caller yet; ticket 10 should use `marker_tag(id)`.
- [ ] **CRLF file without a final newline gets mixed endings (class c).** `insert_in_section` on `"## Open blockers\r\n- a"` yields `"...\r\n- a\nnew\r"`. Add the `\r` to the last line's break when the file has none at its end; test.
- [ ] **Readers that do not pin the encoding (class c).** `boss_review.py` `_listed` and `prune_provisional` open the tracker with the locale encoding, and `routines/boss_ladder_core.py` reads and writes with it, while `tracker.update` is now UTF-8. Under a non-UTF-8 locale the ladder rewrites the file as that encoding and every later `update` returns `failed: UnicodeDecodeError`. Pin `encoding="utf-8"` in those places; test under `LC_ALL=C` with coercion off.
- [ ] **`update` drops an exception's cause (class d).** `raise raised.args[0] from None` clears the `__cause__` of an `OSError` that `fn` raised `from inner`. Re-raise without touching the cause.
- [ ] **ASCII boundary, Unicode test (class d).** `add_line` switches its word boundary on `tag[0].isalnum()`, which accepts non-ASCII letters, while the boundary class is ASCII-only. Use the same class for both.
