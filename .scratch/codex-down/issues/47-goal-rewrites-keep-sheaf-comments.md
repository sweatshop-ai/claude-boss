# 47: Goal rewrites keep the owner's sheaf comments, and section lookups read a heading with a comment glued to it

**What to build:** The owner comments on goal pages in sheaf. A thread lives in the goal file as a `<!-- sheaf-comment … -->` block (sheaf writes `--` inside it as `-&#45;`, so the first `-->` ends it) and must survive every `boss-goal` rewrite. Measured by agentview's track on a copy of a goal file:
- `boss-goal set` with a hand-written body: `with_body` kept only the `# ` heading and the `_Status:` line, so the file went from 1 block to 0.
- `objective.py set-next` with a block inside `## Next, in priority order`: `set_next` replaced everything up to the next `##`, and the block went with it.
- Sheaf can glue a block to a heading line (`## Done when<!-- sheaf-comment … -->`). The section lookups did not recognise that heading and found 0 criteria; with the block on its own line they found 10.
- Already safe: `status`, `tick`, and `set` fed with `boss-goal show` unchanged (pinned now).

`objective.py` now treats a block as an opaque span, `<!--` + `sheaf-comment` (or the older `rd-comment`) up to the first `-->`, and never reads inside it:
- `with_body` and `set_next` carry over every block of the text they drop, byte for byte: `set` appends them after the new body, `set-next` at the end of the section they came from. A block the new body already holds is not carried twice (`show` output round-trips unchanged).
- Every section lookup (`section`, `criteria`, `next_items`, `tick`, `set_next`) matches a heading with trailing glued blocks. `set_next` leaves the heading line untouched. `with_body` glues a heading's blocks back onto that same heading of the new body, byte for byte; if the new body does not have that heading exactly once, it refuses (exit 1, file unchanged) and names the heading. A block is never merged into another heading or moved from its heading into a body.
- A block that opens and never closes is refused the same way: where it ends is a guess.

Out of scope: one of 59 live goal files writes `## Next` instead of `## Next, in priority order`. That is a naming difference in the file, not a code bug.

**Blocked by:** none

**Status:** done (Amir built it)

- [x] `set` with a hand-written body and `set-next` keep every sheaf-comment block, byte for byte
- [x] A heading with a glued block is found by every section lookup; its block stays on it
- [x] An unclosed block, or a glued block whose heading the new body lacks, is refused with the file unchanged
- [x] `status`, `tick` and the `show` round-trip keep the blocks (pins)
- [x] The new tests fail on the old code; `test_objective.py` and `test_hermetic.py` pass
- [x] CHANGELOG.md has the entry
