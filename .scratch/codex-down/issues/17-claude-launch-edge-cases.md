# 17: claude_launch edge cases left by review of PR 93

**What to build:** in `reviewer_chain.claude_launch` (from the Opus fallback review of PR 93, findings 1, 2, 4, 5):
- [ ] `cwd=None` with a deleted working directory records an "absent"/"error" attempt instead of raising `FileNotFoundError` from `os.getcwd()`
- [ ] A base of `/` excludes nothing (`base + os.sep` is `//`); compare with a normalised prefix
- [ ] Document that a refused link yields "absent" without trying a later PATH entry
- [ ] Test a relative symlink whose own target lies inside the checkout

**Origin:** class c/d findings of PR 93, ticketed not fixed.

**Blocked by:** 14

**Status:** open
