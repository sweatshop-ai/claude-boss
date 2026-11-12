# 18: Codex health, edge cases found in the review of 05b

**Blocked by:** 05b (merged, PR 94)

**Status:** ready-for-agent

Found by the fallback review of PR 94 (class c and d, no round blocked on them). Each is a small box.

- [ ] Class c: a blank or whitespace-only line inside `attempts.jsonl` is dropped by `codex_health.health` without being counted as skipped, and `test_blank_lines_are_neither` pins it. The ticket says a line that is not a JSON object is skipped and counted. Decide which is right, then make code, test and ticket agree. `append_attempts` never writes a blank line.
- [ ] Class c: `health()` catches only `FileNotFoundError`. A `PermissionError`, `IsADirectoryError` or `NotADirectoryError` is a traceback and `python3 codex_health.py` exits 1, where the box says it exits 0. Decide whether the CLI should print the error and exit non-zero on purpose, and test it. 05c already reports a failed sync on stderr.
- [ ] Class c: a write that tears without a newline (full disk) is followed by the next append on the same line, so the merged line is unparseable and one real attempt goes uncounted; `down` can come one attempt late. Accepted by the "torn or not parseable" rule; record it in the module docstring, or make the reader resynchronise on a `{"ts"` boundary.
- [ ] Class d: after F,F,F,ok the state is still `down` with `failures` 0 and `prs` 0, while `last_repo`, `last_pr` and `last_reason` still name the old failure. 05c must build the blocker text only when `failures >= policy.CODEX_DOWN_AFTER`; pin it with a test or clear `last` on an answer.
- [ ] Class d: duplicate JSON keys in a line resolve to the last value, so a hand-edited line could change its reviewer. Not reachable through the writer; reject duplicates with `object_pairs_hook` or leave it.
