# 01: One reviewer chain, shared

**What to build:** the chain that picks a reviewer (Codex first, a fallback model next, otherwise "no reviewer answered") lives in one place that `boss-run` and the coming PR review command both call. `boss-run` behaves exactly as it does today: Codex, then Haiku, otherwise exit 4 with nothing run. The chain takes the fallback model as a parameter so the PR gate can choose a different one.

**Scope:** the chain as `boss-run` and the PR review command use it. `boss-goal`'s own copy of the chain (`ask_second_model`) is not moved here; it is logged as a follow-up. Amended 2026-10-04 after Codex review 1 of the plan (`plan-review-codex-1.md`, findings 1, 2, 3, 6), after Codex review 2 of this ticket (`plan-review-codex-2.md`, findings 1 to 5) and the owner-accepted premortem (R2, R3, R11, R12, R13, R25).

**Blocked by:** None (can start immediately)

**Claimed by:** Anouk 2026-10-03 23:54

**Status:** in-progress

## The interface (fixed here so 02 and 03 build on it)

Module `skills/boss/reviewer_chain.py`, standard library only:

```python
@dataclass(frozen=True)
class Fallback:
    name: str                                   # what the result and boss-run's log call it ("haiku")
    model: str                                  # exact model id passed to `claude --model`
    timeout: int = 120                          # seconds, this reviewer only
    allowed_tools: tuple[str, ...] | None = None  # None: no flag; non-empty: `--allowedTools a,b`; empty: ValueError

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

`fallback=None` means Codex only. The module's default is Codex only; **`boss-run` passes `HAIKU` explicitly**, so "Haiku is `boss-run`'s default" and "the fallback is optional" are both true.

CLI, for `boss-run` (a bash script) to call: `python3 skills/boss/reviewer_chain.py --prompt-file F --words APPROVE,REJECT [--effort E] [--codex-timeout N] [--fallback-name N --fallback-model M [--fallback-timeout N] [--fallback-tools a,b] | --no-fallback] [--strict]`. It writes one JSON object (the `Result`, with `attempts` as a list) to stdout and nothing else there. Exit 0: a reviewer answered. Exit 1: none answered (the JSON is still written). Exit 2: usage.

**Verdict matching.** The `words` parameter carries the verdict vocabulary and the matching rule goes with it. `boss-run`'s vocabulary keeps today's anchored prefix match: the line must start `VERDICT:` and the word must follow it directly, so `VERDICT: APPROVED` is APPROVE and `VERDICT: REJECTED` is REJECT (pinned by tests; today's `boss-run` does the same). The `GO`/`NO-GO` vocabulary that tickets 02 and 03 use matches whole tokens, longest word first, so `VERDICT: NO-GO` is NO-GO, never GO, and `VERDICT: GOOD` is no verdict. The module exposes the rule as part of the vocabulary (the `words` value carries it; the exact spelling is the builder's, the two behaviours are pinned by tests).

**Which output counts, and which reason wins** (both as `boss-run` does today, which ignores the reviewer's exit status and reads only the answer channel). The answer channel is the one place the reviewer puts its answer: for Codex the `-o` last-message file (never its stdout or stderr progress, so `Attempt.output` for Codex is that file's content, `""` when it wrote none); for the fallback its stdout. The output is parsed whatever the exit status and even after a timeout. The reason is then decided in this order: (1) a usable verdict in the answer channel gives `answered`, even after a non-zero exit or a timeout (the exit code is still recorded, `None` after a timeout); (2) otherwise a timeout gives `timeout`; (3) otherwise a non-zero exit gives `error`; (4) otherwise `noverdict` (exit 0 and no usable verdict, an empty answer included); `absent` is a reviewer that is not on PATH, tried before any of these. `reviewer`/`parsed` on the `Result` come from the first `answered` attempt.

**Matching properties kept from today's grep** (`boss-run:131`), for the `APPROVE`/`REJECT` vocabulary: `VERDICT:` and the word are case-insensitive, any leading whitespace before `VERDICT:` is allowed, any whitespace (or none) after the colon is allowed, the line must start with `VERDICT:`, and the word is returned upper-case. The `GO`/`NO-GO` vocabulary has the same properties and adds the whole-token rule.

## Boxes

- [ ] One module owns the reviewer chain; `boss-run` holds no reviewer logic of its own
- [ ] The fallback model and the timeout are parameters (the `Fallback` spec and `codex_timeout`), with `boss-run`'s current values as the values it passes
- [ ] The result says which reviewer answered (`codex`, the fallback's name, or `none`)
- [ ] Existing tests pass unchanged; new tests cover the three outcomes with stubbed `codex` and `claude` binaries (no real calls)

Added after Codex review 1 and the premortem:

- [ ] The fallback is optional: with none given, the chain is Codex only and a Codex failure gives `none` (ticket 02 uses this)
- [ ] The result is structured as above (`reviewer`, `output`, `parsed`, `attempts`); the module writes no file, the caller keeps the output
- [ ] The verdict words are a parameter (`APPROVE`/`REJECT` for `boss-run`, `GO`/`NO-GO` for the PR command)
- [ ] The fallback is a spec (name, exact model id, timeout, optional tool restriction) that the caller passes in; 01 carries the restriction to the `claude` call (the stub logs its argv and the test reads it), ticket 03 chooses and tests the actual restriction
- [ ] Each attempt carries a reason from the closed set `answered`, `absent` (not on PATH), `timeout`, `error` (non-zero exit), `noverdict` (answered, no usable VERDICT line), and one test per reason; `timeout` and `error` stay distinct; `error` keeps the exit code and a stderr tail of at most 2048 characters (tested at the bound), and `boss-run` prints nothing new
- [ ] Every attempt keeps its own raw `output`, so a Codex answer with no usable verdict is still on the result (ticket 02 needs the round's full output); `Result.output` is the answering attempt's output
- [ ] Verdict words match as the section above says, and `VERDICT: NO-GO` never parses as `GO` (tested). The first usable VERDICT line wins by default (an earlier malformed line such as `VERDICT: maybe` is skipped, as today); the strict flag turns two usable lines with different normalized verdicts into `noverdict` (the same verdict twice is fine), off by default. `REASON:` parsing is kept and tested: first line starting `REASON:`, case-insensitive, anywhere in the output, default `(no reason given)`
- [ ] The timeout is per reviewer (Codex and the fallback apart), defaults 120 and 120 as today
- [ ] The result records the exact model id the fallback ran with (`Attempt.model`); `boss-run` still logs reviewer `haiku`
- [ ] Tests are hermetic: a stub directory first on PATH, each stub appends to a call log the test asserts on, and a guard fails the test if `codex`, `claude` or `gh` resolves outside the stub directory; no real calls. `gh` stays in this guard although nothing in 01 calls it: `boss-run` runs the approved command with `bash -lc`, so a test that reaches that path must not be able to reach a real `gh`. (Codex review 2 asked to drop it; ticket 02 needs its own `gh` stub.)

Added after Codex review 2 and 3b. Two stages of tests. **Characterization tests** are written first, against `boss-run` as it is, and pass before and after the move. The one thing they need that `boss-run` lacks is the timeout variable, so the first and only edit to `boss-run` before they are green is the one line `TIMEOUT="${BOSS_RUN_REVIEW_TIMEOUT:-120}"`; every other characterization test is run against the unchanged file (a copy of `570d5d2`) and passes there. **Integration tests** (the `python3` stubs) need the chain CLI and are written during the move.

- [ ] Characterization tests pin: `--dry-run` approved gives exit 0; a run command's own exit status passes through; exits 2, 3, 4 and 5; the exact stdout and stderr text of each outcome; the nine log fields (`ts, session, cwd, why, cmd, reviewer, verdict, reason, exit`) and their values for `haiku`, `codex`, `none` and `hard-rule`; the reviewer's stdin is closed; reviewer diagnostics never reach `boss-run`'s stdout or stderr; `VERDICT: APPROVED` is APPROVE and `VERDICT: REJECTED` is REJECT; lower-case `verdict: approve` and leading whitespace before `VERDICT:` and none after the colon are accepted; a usable verdict after a non-zero exit still counts; Codex progress output on stdout is never read as the answer (the `-o` file is)
- [ ] A reviewer that hangs is killed at the timeout and its child processes with it (the process group); `BOSS_RUN_REVIEW_TIMEOUT` (default 120) lets a test make the timeout short, and the PR says so
- [ ] Integration test, written with the move: the reason precedence above is tested on the chain (a verdict after a non-zero exit is `answered` with the exit code kept; a verdict in the `-o` file written before a timeout is `answered` with exit code `None`; a verdict only in Codex's stdout progress is not an answer; empty answer with exit 0 is `noverdict`)
- [ ] `boss-run` fails closed (integration test): it runs the command only when the chain CLI exits 0 with valid JSON that names a reviewer and a verdict. A crash, garbage on stdout or a signal is exit 4 and the command never runs (tested with a stub `python3` first on PATH that crashes, and one that prints garbage)
- [ ] The README "Tests" glob becomes `skills/boss/test_*.py skills/hand-to-boss/test_*.py`, and every test file in it passes with no real tool called (checked with recording stubs for `codex`, `claude`, `gh` and `tmux`); `boss-run --selftest` is not run, since it calls real reviewers (the PR says so)
