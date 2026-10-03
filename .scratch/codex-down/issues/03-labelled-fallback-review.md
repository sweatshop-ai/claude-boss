# 03: The fallback reviewer is confined to read-only

**What to build:** when Codex is not there, the PR gate falls back to Claude Opus in read-only mode (decided by the owner 2026-10-03; do not reopen: only `codex` and `claude` are installed, so the fallback is the same family as the Claude workers, and the label, the recovery re-review of 10 and the gate of 04 make up for that). This ticket builds and tests the confinement and nothing else: the exact `claude` call with its flags, the additive `extra_args` on 01's `Fallback`, `boss_review.py --check-fallback`, and the timeout bound. It does not yet run the fallback from `review()`; 08 does.

**Scope:** amended 2026-10-04 after Codex review 1 of the plan (finding 3) and the owner-accepted premortem (R3 in part, R13, R25), and split on 2026-10-04 after Codex review 3 (findings 1, 17, 23): this is the confinement half of the original 03; the review integration is 08. The fallback stays inside the one code path of 02 and 07: same brief, same fence, same findings format, same redaction.

**Blocked by:** 02 (PR review becomes a command)

**Status:** ready-for-agent

Fallback spec ("read-only" named and tested, R13):

- [ ] The fallback is the `claude` call `claude -p --model claude-opus-5-5 --tools "Read,Grep,Glob" --strict-mcp-config --disable-slash-commands --permission-mode dontAsk`, run with its working directory set to `--checkout`. The model id and each flag value are `policy.py` constants (`REVIEW_FALLBACK_MODEL`, `REVIEW_FALLBACK_TOOLS`, ...). Why these flags, checked 2026-10-04 with `claude` 2.1.288: `--tools` restricts the built-in tool set (its init event listed exactly `Glob`, `Grep`, `Read`); without `--strict-mcp-config` the same `--tools` value still left 511 tools in the init event, 508 of them MCP tools (mail drafts and file-store writes among them); `--allowedTools` only pre-approves tools and removes none, so it is not the mechanism
- [ ] 01's `Fallback` carries `allowed_tools`, which becomes `--allowedTools`; 03 leaves it `None`. This ticket adds `extra_args: tuple[str, ...] = ()` to `Fallback` in `reviewer_chain.py` itself, additively (the default, empty, changes nothing for `boss-run`), placed on the `claude` argv before the prompt; a test shows `Fallback` without it still produces today's argv. The boss decided on 2026-10-04 that 03 owns this change and 01 does not define the field. A function `boss_review.fallback_spec(timeout=REVIEW_FALLBACK_TIMEOUT)` returns `Fallback("opus", REVIEW_FALLBACK_MODEL, timeout=timeout, when=("absent", "timeout", "error"), extra_args=(...))`; 08 passes it to the chain
- [ ] The `claude` stub records its argv. A test asserts each flag and value above, that the `--tools` value is exactly `Read,Grep,Glob`, that `--model` is the policy constant, and that `--dangerously-skip-permissions`, `--allowedTools`, `--allowed-tools`, `--bare`, any `--mcp-config` and any `--permission-mode` other than `dontAsk` are absent

The check (finding 1):

- [ ] `boss_review.py --check-fallback` runs the fallback call with those flags in stream-json mode and a one-word prompt, and exits 0 only if the init event lists exactly `Glob`, `Grep` and `Read`, no MCP servers, and the model id from the policy constant; otherwise 1. The decision is a function over the parsed events and is tested with a `claude` stub that prints recorded stream-JSON fixtures: one pass, and one fail each for an extra tool, an MCP server and a wrong model. The suite never calls the real `claude`. The author runs the real check once as a manual smoke test and pastes its output in the PR; it is not a pass condition

Timeouts (R3 in part, finding 17):

- [ ] Codex and the fallback have separate timeout constants in `policy.py` (`REVIEW_CODEX_TIMEOUT` is 02's, `REVIEW_FALLBACK_TIMEOUT` is added there by 02 and used here), both 600 seconds in production. An elapsed-time test runs 01's chain with `fallback_spec(timeout=1)` and `codex_timeout=1` against a Codex stub that sleeps well past 1 second and a `claude` stub that answers: the Codex attempt is logged `timeout`, the fallback answers, and the total elapsed time is under the sum of the two test timeouts plus a slack stated in the test. The bound is stated, not removed: a hung Codex costs one timeout per review, an absent or failing Codex costs nothing

Tests:

- [ ] Tests use 01's stub-directory harness with its PATH guard (`codex` and `claude` stubs, a temp `HOME` and `CLAUDE_CONFIG_DIR`, `BOSS_TYPESAFE_ENV` pointing at a missing file): each test asserts its stub call logs and fails if `codex`, `claude` or `gh` resolves outside the stub directory [R25]. Cases: the argv assertion, `Fallback` without `extra_args` unchanged, the four `--check-fallback` fixtures, and the elapsed-time test
