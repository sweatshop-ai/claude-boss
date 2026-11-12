# 29: claude_launch tests, precision found in the review of 17

**What to build:** class d findings of the Opus fallback review, round 1, of PR 108 (ticket 17), in `skills/boss/test_boss_review_fallback.py` and `skills/boss/reviewer_chain.py`.
- [x] `test_a_base_that_is_a_prefix_of_a_sibling_name_keeps_out_only_itself` cannot catch a bare `startswith(base)`: the sibling's `claude` links to the stub, and the stubs directory is later on PATH, so the same stub starts either way. Make the sibling the only place a `claude` is found, or assert `claude_launch(...)[0][0] == str(sibling / "claude")`
  Done: asserts the argv names the sibling's `claude`; fails when `startswith(prefix)` is mutated to `startswith(base)`.
- [x] `test_a_refused_link_is_absent_even_when_a_later_entry_holds_a_good_claude` repeats `test_a_symlink_in_a_safe_directory_that_leads_into_the_checkout_is_refused` line for line; assert `self.claude_calls() == []` explicitly or drop it
  Done: asserts `claude_calls() == []` and `claude_launch(...) is None`.
- [x] The comment at the `except OSError` in `claude_launch` names only a deleted current directory; it also covers a `PermissionError` from `getcwd` and a relative `cwd` with a deleted process cwd (all fail closed). Say so
  Done: comment names all three; new test `test_with_a_deleted_current_directory_a_relative_cwd_is_absent_too` pins the third.

**Origin:** class d findings 1, 2 and 4 of review round 1 of PR 108.

**Blocked by:** 17

**Status:** done (Otilia built it, PR <N>)
