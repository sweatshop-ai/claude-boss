# 14: claude_launch refuses a resolved claude inside the checkout, and a cwd of None

**What to build:** three small hardenings of `reviewer_chain.claude_launch` (the confined fallback's launcher, ticket 03):
- `realpath` the resolved executable and refuse it (return None, attempt "absent") when it lies inside the checkout: a symlink in a safe PATH directory (`/safe/bin/claude -> <checkout>/claude`) is followed today. Test with a planted symlink.
- Give the PATH filter an exclusion base when `cwd` is None (`os.getcwd()`): no caller passes None today, but a future one would filter nothing.
- Refuse `"PATH"` in `Fallback.env_unset` at construction: `child_env` removes it and `claude_launch` adds the filtered PATH back, so the field would be silently ignored.

**Origin:** Codex review 3 of PR #87, head 4f449d9 (findings 2 and 3 and the P2). Class b/c: each needs an unusual setup (a symlink in the owner's own PATH directory, a new caller, a new spec). Ticketed, not fixed in PR #87.

**Blocked by:** 03

**Status:** done (merged, PR 93, 1e99ab0; Codex re-review of the final head owed, edge cases ticketed as 17)

- [x] `claude_launch` takes the `realpath` of the `claude` it found and returns None (attempt "absent") when it lies inside the checkout; tested with a real symlink in a tmp PATH directory pointing into a tmp checkout, a relative symlink, a chain of links, a checkout that is itself a symlink (both ways), and a link to a `claude` outside the checkout that is still started
- [x] With `cwd` None the exclusion base is `os.getcwd()`; tested by changing into a tmp checkout
- [x] `Fallback(env_unset=...)` raises `ValueError` naming PATH at construction
