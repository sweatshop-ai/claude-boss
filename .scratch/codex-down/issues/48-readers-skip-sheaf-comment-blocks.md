# 48: Readers skip sheaf-comment blocks, and the section-end scan ignores a `## ` line inside one

**What to build:** Ticket 47 made writers carry a `<!-- sheaf-comment … -->` block byte for byte, but the readers still looked inside a multi-line block that sits in a section (findings 2 and 4 of PR 142's Opus round 2):
- `next_items`, `criteria` and `tick` read the block's lines as section content: a `- x` line in a thread showed up as a NEXT item in the pulse, and a `- [ ] x` line counted as a criterion and could be ticked.
- The section-end scan (`section`, `_section_span`) stopped at any line starting with `## `, even inside a block, so a thread quoting the file cut the section short and a write could split the block.

Now one masking step, `_masked` in `skills/boss/objective.py`, built on 47's block matcher (`_block_spans`, shared with `comment_blocks`; no second matcher): every block is blanked to spaces with its newlines kept, so lines keep their indices.
- Readers (`section`, `next_items`, `next_count`, `criteria`, `unmet`, `tick`) see the text with every block removed.
- The section-end scan runs on the masked lines, so a `## ` line inside a block ends nothing.
- Writers still carry blocks byte for byte as 47 does: `set_next` replaces the section's original lines and appends the blocks it dropped, whole.
- An unclosed block is not masked by the readers (they do not raise); the writers still refuse it.

Parked, out of scope: finding 3 of the same review (`with_body` splits with `splitlines()`, so a block holding `\r\n`, U+2028 or `\x85` is not carried byte for byte) and finding 1 (blocks `set-body` cannot reglue land at the end of the file, in whatever section is last; section-aware placement needs a decision).

**Blocked by:** 47

**Status:** done (Joaquin built it)

- [x] A block in `## Next` with list-looking lines adds no NEXT items
- [x] A block in `## Done when` holding `- [ ] x` adds no criterion and is not ticked
- [x] A block holding a `## X` line neither ends its section nor is split by `set-next`
- [x] The new tests fail on the old code; `test_objective.py` and `test_hermetic.py` pass
- [x] CHANGELOG.md has the entry
