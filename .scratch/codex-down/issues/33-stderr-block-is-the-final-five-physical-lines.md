# 33: A Codex stderr tail is published as its five final physical lines

**Blocked by:** 08

**Status:** done (Amelie built it, PR PRNUM)

Found by the Codex re-review of PR 91 (class b, real on main; privacy). `boss_review.stderr_block` took the
last five non-blank lines of the tail. The text goes into a public PR comment, and redaction knows only the
patterns it has: with `sensitive line`, five blank lines, `login failed`, the sensitive line was published.
Ticket 08 says the last 5 lines of the tail; a blank line is a line.

## What to build

`stderr_block` takes the five final physical lines (the closing newline ends the last line and is not one).
A blank line is shown as an empty indented line and never pulls an older line in; five blank lines give "".

- [x] A test that fails on main: `sensitive line`, five blank lines, `login failed` publishes `login failed`
  and not the sensitive line; seven lines publish the last five; a closing newline is no line.
- [x] The test that pinned the wrong behaviour (`test_the_stderr_block_is_inert_text`'s "last five non-blank",
  and the posted-comment test's `![i](u)` line, which is older than the final five) now says the right one.
- [x] CHANGELOG.md.
