# 01: One reviewer chain, shared

**What to build:** the chain that picks a reviewer (Codex first, a fallback model next, otherwise "no reviewer answered") lives in one place that `boss-run` and the coming PR review command both call. `boss-run` behaves exactly as it does today: Codex, then Haiku, otherwise exit 4 with nothing run. The chain takes the fallback model as a parameter so the PR gate can choose a different one.

**Scope:** the chain as `boss-run` and the PR review command use it. `boss-goal`'s own copy of the chain (`ask_second_model`) is not moved here; it is logged as a follow-up. Amended 2026-10-04 after Codex review 1 of the plan (`plan-review-codex-1.md`, findings 1, 2, 3, 6), after Codex review 2 of this ticket (`plan-review-codex-2.md`, findings 1 to 5) and the owner-accepted premortem (R2, R3, R11, R12, R13, R25).

**Blocked by:** None (can start immediately)

**Claimed by:** Anouk 2026-10-03 23:54

**Status:** done

## The interface (fixed here so 02 and 03 build on it)

Module `skills/boss/reviewer_chain.py`, standard library only:

```python
@dataclass(frozen=True)
class Fallback:
    name: str                                   # what the result and boss-run's log call it ("haiku")
    model: str                                  # exact model id passed to `claude --model`
    timeout: int = 120                          # seconds, this reviewer only
    allowed_tools: tuple[str, ...] | None = None  # None: no flag; non-empty: `--allowedTools a,b`; empty: ValueError
    when: tuple[str, ...] = ("absent", "timeout", "error", "noverdict")  # Codex attempt reasons that let this fallback run

HAIKU = Fallback("haiku", "claude-haiku-4-5-20251001")

@dataclass(frozen=True)
class Verdict:
    word: str      # one of the caller's words, upper-case
    reason: str    # first line starting `REASON:` (case-insensitive) anywhere in the output, else "(no reason given)"

@dataclass(frozen=True)
class Attempt:
    reviewer: str            # "codex" or the fallback's name
    reason: str              # closed set: answered | absent | timeout | error | noverdict
    output: str              # the reviewer's raw answer; "" when it gave none
    exit_code: int | None    # None when absent or timed out
    stderr_tail: str         # last 2048 characters of stderr, "" when none
    model: str | None        # exact id for the fallback, None for Codex

@dataclass(frozen=True)
class Result:
    reviewer: str            # "codex", the fallback's name, or "none"
    output: str              # the answering attempt's output; "" when reviewer is "none"
    parsed: Verdict | None   # None when reviewer is "none"
    attempts: tuple[Attempt, ...]   # in the order tried, every one kept

def run_chain(prompt: str, *, words: tuple[str, ...], effort: str = "medium",
              codex_timeout: int = 120, fallback: Fallback | None = None,
              strict: bool = False) -> Result: ...
```

`fallback=None` means Codex only. `Fallback.when` names the Codex reasons that let the fallback run; the default is today's `boss-run` behaviour (any Codex failure, a Codex answer with no usable verdict included). Ticket 03 passes `("absent", "timeout", "error")`, so a Codex `noverdict` ends the chain with `none` and `claude` is never called (tested: the `claude` stub's call log stays empty, and with the default `boss-run` still falls through to Haiku). The module's default is Codex only; **`boss-run` passes `HAIKU` explicitly**, so "Haiku is `boss-run`'s default" and "the fallback is optional" are both true.

CLI, for `boss-run` (a bash script) to call: `python3 skills/boss/reviewer_chain.py --prompt-file F --words APPROVE,REJECT [--effort E] [--codex-timeout N] [--fallback-name N --fallback-model M [--fallback-timeout N] [--fallback-tools a,b] [--fallback-when absent,timeout,error] | --no-fallback] [--strict]`. It writes one JSON object (the `Result`, with `attempts` as a list) to stdout and nothing else there. Exit 0: a reviewer answered. Exit 1: none answered (the JSON is still written). Exit 2: usage.

**Verdict matching.** The `words` parameter carries the verdict vocabulary and the matching rule goes with it. `boss-run`'s vocabulary keeps today's anchored prefix match: the line must start `VERDICT:` and the word must follow it directly, so `VERDICT: APPROVED` is APPROVE and `VERDICT: REJECTED` is REJECT (pinned by tests; today's `boss-run` does the same). The `GO`/`NO-GO` vocabulary that tickets 02 and 03 use matches whole tokens, longest word first, so `VERDICT: NO-GO` is NO-GO, never GO, and `VERDICT: GOOD` is no verdict. The module exposes the rule as part of the vocabulary (the `words` value carries it; the exact spelling is the builder's, the two behaviours are pinned by tests).

**Which output counts, and which reason wins** (both as `boss-run` does today, which ignores the reviewer's exit status and reads only the answer channel). The answer channel is the one place the reviewer puts its answer: for Codex the `-o` last-message file (never its stdout or stderr progress, so `Attempt.output` for Codex is that file's content, `""` when it wrote none); for the fallback its stdout. The output is parsed whatever the exit status and even after a timeout. The reason is then decided in this order: (1) a usable verdict in the answer channel gives `answered`, even after a non-zero exit or a timeout (the exit code is still recorded, `None` after a timeout); (2) otherwise a timeout gives `timeout`; (3) otherwise a non-zero exit gives `error`; (4) otherwise `noverdict` (exit 0 and no usable verdict, an empty answer included); `absent` is a reviewer that is not on PATH, tried before any of these. `reviewer`/`parsed` on the `Result` come from the first `answered` attempt.

**Matching properties kept from today's grep** (`boss-run:131`), for the `APPROVE`/`REJECT` vocabulary: `VERDICT:` and the word are case-insensitive, any leading whitespace before `VERDICT:` is allowed, any whitespace (or none) after the colon is allowed, the line must start with `VERDICT:`, and the word is returned upper-case. The `GO`/`NO-GO` vocabulary has the same properties and adds the whole-token rule.

## Boxes

- [x] One module owns the reviewer chain; `boss-run` holds no reviewer logic of its own
- [x] The fallback model and the timeout are parameters (the `Fallback` spec and `codex_timeout`), with `boss-run`'s current values as the values it passes
- [x] The result says which reviewer answered (`codex`, the fallback's name, or `none`)
- [x] Existing tests pass unchanged; new tests cover the three outcomes with stubbed `codex` and `claude` binaries (no real calls)

Added after Codex review 1 and the premortem:

- [x] The fallback is optional: with none given, the chain is Codex only and a Codex failure gives `none` (ticket 02 uses this)
- [x] The result is structured as above (`reviewer`, `output`, `parsed`, `attempts`); the module leaves no file behind: it writes no artifact for the caller, and the temporary file it needs for Codex's `-o` last message is removed on every path (tested after an answer, an error and a timeout); the caller keeps the output
- [x] The verdict words are a parameter (`APPROVE`/`REJECT` for `boss-run`, `GO`/`NO-GO` for the PR command)
- [x] The fallback is a spec (name, exact model id, timeout, optional tool restriction) that the caller passes in; 01 carries the restriction to the `claude` call (the stub logs its argv and the test reads it), ticket 03 chooses and tests the actual restriction
- [x] Each attempt carries a reason from the closed set `answered`, `absent` (not on PATH), `timeout`, `error` (non-zero exit), `noverdict` (answered, no usable VERDICT line), and one test per reason; `timeout` and `error` stay distinct; `error` keeps the exit code and a stderr tail of at most 2048 characters (tested at the bound), and `boss-run` prints nothing new
- [x] Every attempt keeps its own raw `output`, so a Codex answer with no usable verdict is still on the result (ticket 02 needs the round's full output); `Result.output` is the answering attempt's output
- [x] Verdict words match as the section above says, and `VERDICT: NO-GO` never parses as `GO` (tested). The first usable VERDICT line wins by default (an earlier malformed line such as `VERDICT: maybe` is skipped, as today); the strict flag turns two usable lines with different normalized verdicts into `noverdict` (the same verdict twice is fine), off by default. `REASON:` parsing is kept and tested: first line starting `REASON:`, case-insensitive, anywhere in the output, default `(no reason given)`
- [x] The timeout is per reviewer (Codex and the fallback apart), defaults 120 and 120 as today
- [x] The result records the exact model id the fallback ran with (`Attempt.model`); `boss-run` still logs reviewer `haiku`
- [x] Tests are hermetic: a stub directory first on PATH, each stub appends to a call log the test asserts on, and a guard fails the test if `codex`, `claude` or `gh` resolves outside the stub directory; no real calls. `gh` stays in this guard although nothing in 01 calls it: `boss-run` runs the approved command with `bash -lc`, so a test that reaches that path must not be able to reach a real `gh`. (Codex review 2 asked to drop it; ticket 02 needs its own `gh` stub.)

Added after Codex review 2 and 3b. Two stages of tests. **Characterization tests** are written first, against `boss-run` as it is, and pass before and after the move. The one thing they need that `boss-run` lacks is the timeout variable, so the first and only edit to `boss-run` before they are green is the one line `TIMEOUT="${BOSS_RUN_REVIEW_TIMEOUT:-120}"`; every other characterization test is run against the unchanged file (a copy of `570d5d2`) and passes there. **Integration tests** (the `python3` stubs) need the chain CLI and are written during the move.

- [x] Characterization tests pin: `--dry-run` approved gives exit 0; a run command's own exit status passes through; exits 2, 3, 4 and 5; the exact stdout and stderr text of each outcome; the nine log fields (`ts, session, cwd, why, cmd, reviewer, verdict, reason, exit`) and their values for `haiku`, `codex`, `none` and `hard-rule`; the reviewer's stdin is closed; the Codex argv is `exec -s read-only --skip-git-repo-check -c model_reasoning_effort="medium" -o <file> <prompt>` and the Claude argv is `-p --model claude-haiku-4-5-20251001 <prompt>` (the stub logs them; the chain tests assert the same flags and the effort they were given); reviewer diagnostics never reach `boss-run`'s stdout or stderr; `VERDICT: APPROVED` is APPROVE and `VERDICT: REJECTED` is REJECT; lower-case `verdict: approve` and leading whitespace before `VERDICT:` and none after the colon are accepted; a usable verdict after a non-zero exit still counts; Codex progress output on stdout is never read as the answer (the `-o` file is)
- [x] A reviewer that hangs is killed at the timeout and its child processes with it (the process group); `BOSS_RUN_REVIEW_TIMEOUT` (default 120) lets a test make the timeout short, and the PR says so
- [x] Integration test, written with the move: the reason precedence above is tested on the chain (a verdict after a non-zero exit is `answered` with the exit code kept; a verdict in the `-o` file written before a timeout is `answered` with exit code `None`; a verdict only in Codex's stdout progress is not an answer; empty answer with exit 0 is `noverdict`)
- [x] `boss-run` fails closed (integration test): it runs the command only when the chain CLI exits 0 with valid JSON that names a reviewer and a verdict. A crash, garbage on stdout or a signal is exit 4 and the command never runs (tested with a stub `python3` first on PATH that crashes, and one that prints garbage)
- [x] The README "Tests" glob becomes `skills/boss/test_*.py skills/hand-to-boss/test_*.py`, and every test file in it passes with no real tool called (checked with recording stubs for `codex`, `claude`, `gh` and `tmux`); `boss-run --selftest` is not run, since it calls real reviewers (the PR says so)

## Evidence (Anouk, 2026-10-04, PR #11 at head `9fba517`)

Review: Codex reviews 1 to 12 on PR https://github.com/sweatshop-ai/claude-boss/pull/11; round 12 (on `a524aad`) was the last run, its three findings are answered in https://github.com/sweatshop-ai/claude-boss/pull/11#issuecomment-5977562983 (one fixed in `9fba517`, two declined with measurements). The owner's stop rule of 2026-10-04 makes the author's settled comment the end of the loop: https://github.com/sweatshop-ai/claude-boss/pull/11#issuecomment-5977564534. Branch `feat/01-reviewer-chain`, 18 commits ahead of `570d5d2`, pushed, not merged.

Tests at `9fba517`, run in the worktree: `python3 skills/boss/test_reviewer_chain.py -v` gives `Ran 70 tests ... OK`; `python3 skills/boss/test_boss_run.py -v` gives `Ran 56 tests ... OK` (verbose logs kept beside the reviews as `tests-9fba517-*.txt`). The whole glob, `bash fullsuite.sh` (recording stubs for `codex`, `claude`, `gh`, `tmux` first on PATH): 13 files `rc=0`, last line `recording-stub calls: 0`.

By box, in the order above:

1. `grep -n -E 'codex exec|claude -p|grep .*VERDICT|APPROVE\|REJECT' skills/boss/bin/boss-run` finds nothing (exit 1); the only reviewer call is `python3 "$CHAIN" --prompt-file ... --words APPROVE,REJECT ...` (`boss-run` lines 172 to 181); the chain is `skills/boss/reviewer_chain.py`.
2. That same call passes `--codex-timeout "$TIMEOUT" --fallback-name haiku --fallback-model claude-haiku-4-5-20251001 --fallback-timeout "$TIMEOUT"`; `test_boss_run_calls_the_chain_with_boss_runs_vocabulary_models_and_timeouts` and `test_the_fallback_flags_become_a_fallback_spec` pass.
3. `test_codex_answer_is_the_result_and_codex_is_called_as_boss_run_called_it`, `test_codex_absent_then_the_fallback_answers_and_claude_is_called_as_before` and `test_both_absent_is_none_with_both_attempts_kept` pass (codex, the fallback's name, `none`).
4. `git diff --stat 570d5d2..HEAD` lists 7 files: `CONTEXT.md`, `README.md`, `skills/boss/bin/boss-run`, `hermetic.py`, `reviewer_chain.py` and two new test files; no existing test file is touched, and the other 11 files of the glob stay `rc=0`. The three outcomes are the three tests of box 3, with stub `codex` and `claude`.
5. `test_without_a_fallback_the_chain_is_codex_only` and `test_no_fallback_is_codex_only_and_the_match_rule_defaults_to_whole_tokens` pass.
6. `test_an_answer_is_one_json_object_on_stdout_and_exit_zero`, `test_no_answer_is_exit_one_and_the_json_is_still_written`; no file left: `Leftovers.test_no_file_is_left_after_an_answer`, `..._after_an_error`, `..._after_a_timeout`, plus `test_the_file_codex_writes_to_is_in_the_temp_directory_while_it_runs`; all pass.
7. `test_approve_reject_matches_the_word_as_a_prefix_as_boss_run_always_did`, `test_go_no_go_matches_whole_tokens_longest_word_first`; `boss-run` passes `--words APPROVE,REJECT --match prefix`.
8. `test_allowed_tools_reach_claude_ahead_of_print_so_the_prompt_is_not_swallowed`, `test_an_empty_tool_list_is_refused_because_it_would_read_as_no_restriction`, `test_the_fallback_name_and_exact_model_id_come_from_the_spec` pass.
9. One test per reason: answered `test_codex_answer_is_the_result_...`, absent `test_codex_absent_then_the_fallback_answers_...`, timeout `test_a_hung_codex_is_timeout_with_no_exit_code_and_the_fallback_runs`, error `test_a_non_zero_exit_without_a_verdict_is_error_and_the_fallback_runs`, noverdict `test_exit_zero_and_no_usable_verdict_is_noverdict_and_the_raw_answer_is_kept`; the 2048 bound `test_the_stderr_tail_is_kept_whole_at_2048_characters_and_cut_at_2049`; `Prose.test_the_module_docstring_lists_exactly_the_reasons_the_chain_uses`; `boss-run` prints nothing new: `ReviewerIsolation.test_reviewer_noise_stays_out_of_an_approve`, `..._a_reject`, `..._a_no_answer`. All pass.
10. `test_exit_zero_and_no_usable_verdict_is_noverdict_and_the_raw_answer_is_kept`, `test_a_strict_conflict_is_a_noverdict_attempt_that_keeps_its_output`, `test_both_absent_is_none_with_both_attempts_kept` pass.
11. `test_no_go_never_parses_as_go_whatever_order_the_words_come_in`, `test_the_first_usable_line_wins_and_a_malformed_one_before_it_is_skipped`, `test_strict_turns_two_different_verdicts_into_noverdict_but_not_the_same_twice`, `test_the_reason_is_the_first_reason_line_anywhere_in_the_output` pass.
12. `test_each_reviewer_has_its_own_timeout` passes; `grep -n 'DEFAULT_TIMEOUT\s*=' skills/boss/reviewer_chain.py` gives `64:DEFAULT_TIMEOUT = 120`; `boss-run` line 41 `TIMEOUT="${BOSS_RUN_REVIEW_TIMEOUT:-120}"`.
13. `test_the_fallback_name_and_exact_model_id_come_from_the_spec` and `test_the_nine_log_fields_and_their_values_for_haiku_none_and_a_hard_rule` (the log still says `haiku`) pass.
14. `skills/boss/hermetic.py` seals the PATH and its `guard()` raises if `codex`, `claude`, `gh` or `tmux` resolves outside the stub directory; `SandboxSeal.test_the_guard_passes_and_the_env_is_built_from_scratch` and `test_inside_an_approved_command_no_real_reviewer_or_tool_resolves` pass; the full glob ended with `recording-stub calls: 0`.
15. `git show f429b11 -- skills/boss/bin/boss-run` is the single line `-TIMEOUT=120` / `+TIMEOUT="${BOSS_RUN_REVIEW_TIMEOUT:-120}"`. I put that version of `boss-run` (`570d5d2` plus the one line) under the head's test file and ran the ten characterization classes (`Approve Reject Fallback NoReviewer HardRules Usage VerdictParsing ReviewerIsolation SandboxSeal MoreCharacterization`): `Ran 39 tests ... OK`. They cover the exit codes, stdout and stderr text, the nine log fields, closed stdin, both argv, diagnostics never leaking, `APPROVED`/`REJECTED`, lower case and whitespace, a verdict after a non-zero exit, and Codex stdout never read as the answer.
16. `test_a_hung_codex_is_cut_off_with_its_children_and_haiku_answers` (`boss-run`) and `Timeouts.test_a_timeout_kills_the_reviewer_and_everything_it_started`, `test_a_reviewer_that_ignores_term_is_killed_after_the_grace_period` pass; the PR body says `BOSS_RUN_REVIEW_TIMEOUT` (default 120) sets both reviewers' timeouts.
17. `Reasons.test_a_verdict_after_a_non_zero_exit_is_still_answered_and_keeps_the_exit_code`, `Timeouts.test_a_verdict_written_before_the_timeout_is_answered_with_exit_code_none`, `Reasons.test_a_verdict_only_in_codex_stdout_is_not_an_answer`, `Reasons.test_an_empty_answer_with_exit_zero_is_noverdict` pass.
18. `FailClosed.test_a_crashing_chain_means_nothing_runs`, `test_garbage_on_stdout_means_nothing_runs`, `test_a_chain_that_dies_by_a_signal_means_nothing_runs`, `test_a_non_zero_exit_beats_json_that_looks_like_an_approval` (stub `python3` first on PATH) pass.
19. `git diff 570d5d2..HEAD -- README.md` changes the glob to `skills/boss/test_*.py skills/hand-to-boss/test_*.py`; `bash fullsuite.sh` runs those 13 files, all `rc=0`, `recording-stub calls: 0`; `boss-run --selftest` was not run and the PR body says so.
