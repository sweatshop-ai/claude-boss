# 41: The merge hard rule refuses `gh pr -Ro/r merge`

**What to build:** The built-in hard rule `PR merge outside boss_merge` in `skills/boss/bin/boss-run` allowed a repo option between `pr` and `merge` only as `-R` or `--repo` followed by whitespace or `=` and a non-empty value. `gh pr -Ro/r merge 5` (the value attached to the short flag) and `gh pr --repo= merge 5` (an empty value after `=`) were not refused, and went on to the reviewer. A hard rule is the part no reviewer can override, so this was a hole in the gate (found by the Codex re-review of PR 121, class a, reproduced on main).

The forms `gh` accepts between `pr` and `merge` come from its flag parser (cobra/pflag): the only flag of `pr` is the repo option, and it takes `--repo VALUE`, `--repo=VALUE` (also empty), `-R VALUE`, `-RVALUE` and `-R=VALUE` (pflag reads the value as `VALUE`), in any number and any mix. `-h` and `--help` print help and merge nothing. A repo option before `pr` (`gh -Ro/r pr merge`) is covered by the part of the pattern that allows anything between `gh` and `pr`. The pattern now takes exactly those forms between `pr` and `merge`.

`boss-run` joins an argument list with a space, so an empty argument (`--repo ''`, `-R ''`) leaves two spaces and no value: the option's value may therefore be empty too (found by Codex round 1). The cost is that `gh pr --repo merge ...` is refused as well; it fails closed.

Not refused, as before: `gh pr view`, `gh pr checks`, `gh pr comment`, `boss_merge.py` and the other non-merges, also with the repo option in each form.

**Blocked by:** none

**Status:** done (Bruno built it)

- [x] Every repo-option form above, alone and mixed, before or after `pr`, is refused with exit 5 and no reviewer asked
- [x] Tests fail on the old pattern for `-Ro/r`, `--repo=` (empty), and the two mixed lists with `-Ro/r`, and pass on the new one
- [x] An empty argument as the option's value (`--repo ''`, `-R ''`), passed as an argument list, is refused; the test fails on the first pattern
- [x] The non-merge commands, also with `-Ro/r`, `-R=o/r` and `--repo=`, are not refused
- [x] CHANGELOG.md has the entry
