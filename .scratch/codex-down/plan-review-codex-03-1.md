# Codex review 1 of ticket 03 (the fallback reviewer is confined to read-only)

Run by Amara (task #03), 2026-10-04 11:04-11:09 (+02:00). Reviewer: Codex (`codex exec -s read-only --skip-git-repo-check -c 'model_reasoning_effort="high"'`,
model `gpt-5.6-sol`, reasoning effort high), stdin closed, working directory the ticket-03 worktree (branch `feat/03-fallback-confined`, stacked on `feat/02-pr-review` at `75caada`),
brief `brief-codex-03-1.md`. Run in the background; answered after about 5 minutes. A spec round: the ticket against the code as it is, not a diff.

The brief handed Codex two facts established first on the installed `claude` (2.1.289, empty config directory and no credentials, so no model call): `--tools` and `--mcp-config` are
variadic (`claude -p --tools Read ok` swallows `ok` and fails with "Input must be provided either through stdin or as a prompt argument"; `claude -p --tools Read -- ok` reaches the login check), and
`claude -p --output-format stream-json ok` fails with "When using --print, --output-format=stream-json requires --verbose". The owner's decisions (the Opus fallback, the flag list, `extra_args` on
`Fallback`, `when=("absent","timeout","error")`) were marked not to argue.

**Verdict: NO-GO**, 8 findings (1 blocker, 6 major, 1 minor). Findings 1 to 4, 6 and 8 are about 03's own boxes; 5 and 7 are about the seam with 08.

## Codex's answer, verbatim

1. [severity: major] **“The check” (`03:21`)** - Stream-JSON under `claude -p` requires `--verbose`, but the ticket requests only “stream-json mode.” - A literal implementation adds `--output-format stream-json`, receives the CLI validation error before any init event, and makes the real smoke check always exit 1. - Require both `--output-format stream-json` and `--verbose`, and assert both in the stub’s exact argv.

2. [severity: major] **“The check” (`03:21`)** - The ticket does not require the diagnostic and production calls to use one argv builder. Production argv is currently assembled inline inside `_claude`; a separately assembled check can drift while all fixture tests pass. - `--check-fallback` could verify a confined command different from the command later used by the real fallback. - Require a shared `claude_argv(prompt, fallback, ...)` builder used by `_claude` and `--check-fallback`; the diagnostic argv must equal the production argv except for `--output-format stream-json` and `--verbose`.

3. [severity: major] **“Fallback spec,” second and third boxes (`03:16-17`)** - “Place `extra_args` before the prompt” is insufficient because `--tools`, `--mcp-config`, and `--allowedTools` are variadic. The proposed membership-style test also does not prove where option parsing ends. The current code deliberately puts `--allowedTools` before `-p` for this reason. - A future `extra_args` ending in `("--tools", "Read")` can swallow the prompt while the stub log still contains every required flag and value. - Specify one complete argv order, preferably `claude [--allowedTools VALUE] [extra_args...] -p --model MODEL PROMPT`, so `-p` terminates every preceding variadic option; reject a literal `--` inside `extra_args`. Test full-list equality and an `extra_args=("--tools", "Read")` case. Update the displayed “exact call” to that order.

4. [severity: major] **“run with its working directory set to `--checkout`” and `boss_review.py --check-fallback` (`03:15,21`)** - Ticket 03 has no function that supplies that directory: `_run` and `_claude` inherit cwd, while only `_ask_codex` sets `cwd=checkout`, and it currently starts a Codex-only child. The literal check command is also impossible today because `--repo`, `--pr`, `--checkout`, and `--author` are all required, yet the ticket does not define which are required in check mode or what cwd it uses. - A builder can complete 03 with the production fallback and diagnostic both running from the invoker’s directory, leaving the checkout confinement claim unproved; alternatively, `boss_review.py --check-fallback` simply exits 2. Exit 1 itself is available and does not clash with the existing boss-review codes. - Define the syntax as, for example, `boss_review.py --check-fallback --checkout DIR`; make `--repo`, `--pr`, and `--author` unnecessary in that mutually exclusive mode, validate the directory, and start the diagnostic with `cwd=DIR`. Rewrite the production claim to say `_claude` inherits cwd and ticket 08 must retain `_ask_codex(..., cwd=checkout)` and test the recorded Claude cwd.

5. [severity: blocker] **“08 passes `fallback_spec()` to the chain” (`03:16`, `08:5,13`)** - A `Fallback` object cannot cross the existing child-process boundary. `reviewer_chain.py` has CLI flags for name, model, timeout, tools, and `when`, but none for `extra_args`; `_ask_codex` invokes that CLI with `--no-fallback`. - An 08 builder can serialize the old fields but silently lose the confinement flags, causing the real fallback to run without `--tools`, `--strict-mcp-config`, `--disable-slash-commands`, or `dontAsk`. - Make 03 own an unambiguous CLI transport for `extra_args`, preferably one JSON-encoded argument, and test its CLI-to-`Fallback` round trip and exact Claude argv. Amend 08 to require `_ask_codex` to serialize the complete result of `fallback_spec()`, not merely name/model/timeout/when.

6. [severity: major] **“The check” and its four fixtures (`03:21,29`)** - The fail-closed init-event contract is under-specified and under-tested. “Otherwise 1” does not say whether exactly one init event is required or how missing keys, malformed types, duplicate tools, malformed JSON, or a suffixed model are handled. - Implementations may accept the first of two init events, treat missing `mcp_servers` as empty, compare only tool sets, or use prefix matching for the model; all four listed fixtures can still pass. - State that stdout is parsed as newline-delimited JSON and success requires exactly one init event; `tools` must be a list containing exactly the three distinct strings `Glob`, `Grep`, and `Read`; `mcp_servers` must be present and exactly empty; and `model` must be a string exactly equal to `REVIEW_FALLBACK_MODEL`, with no suffix. No/multiple init events, missing keys, malformed JSON or types, duplicates, suffixes, timeout, or launch failure must return 1. Add corresponding fixtures; reserve exit 2 for CLI usage.

7. [severity: major] **“Timeouts” (`03:25`) versus ticket 08’s integration** - The elapsed test invokes `run_chain` directly and misses the outer timeout around the chain child. `_ask_codex` currently allows only `codex_timeout + REVIEW_CHAIN_SLACK`; adding a 600-second fallback inside that child does not extend this deadline. - After a hung 600-second Codex attempt, the production wrapper kills the chain about 30 seconds into the nominal 600-second fallback, even though the direct-chain test passes. - Amend 03/08’s interface contract so the outer deadline is `codex_timeout + fallback_timeout + REVIEW_CHAIN_SLACK` when fallback is enabled and remains `codex_timeout + REVIEW_CHAIN_SLACK` otherwise. Require an 08 test through the actual `_ask_codex` child boundary, not only `run_chain`.

8. [severity: minor] **“total elapsed … plus a slack stated in the test” (`03:25`)** - The ticket leaves the slack arbitrary and does not account explicitly for `TERM_GRACE`. `_stop` may spend two additional seconds after a reviewer’s timeout, while the proposed ordinary sleeping stub normally exits on TERM and therefore does not exercise that allowance. - A small slack is flaky; a very large one makes the asserted bound vacuous and leaves graceful termination untested. - Specify a stubborn Codex stub that ignores TERM and a bound such as `codex_timeout + fallback_timeout + TERM_GRACE + 5 seconds`, with the five seconds covering interpreter/stub startup and scheduler variance.

| Finding | Code citations |
|---|---|
| 1 | `skills/boss/boss_review.py:634-647` |
| 2 | `skills/boss/reviewer_chain.py:303-310` |
| 3 | `skills/boss/reviewer_chain.py:303-310`; `skills/boss/test_reviewer_chain.py:497-505` |
| 4 | `skills/boss/reviewer_chain.py:236-250`; `skills/boss/reviewer_chain.py:303-310`; `skills/boss/boss_review.py:384-394`; `skills/boss/boss_review.py:50-51`; `skills/boss/boss_review.py:634-647` |
| 5 | `skills/boss/reviewer_chain.py:335-379`; `skills/boss/boss_review.py:384-394` |
| 6 | `skills/boss/boss_review.py:634-647` |
| 7 | `skills/boss/boss_review.py:384-394`; `skills/boss/boss_review.py:608-625`; `skills/boss/policy.py:45-51` |
| 8 | `skills/boss/reviewer_chain.py:187-206`; `skills/boss/hermetic.py:104-159` |

VERDICT: NO-GO

## Citation check

Each `file:line` Codex gave was printed from the worktree (`75caada`, plus the ticket files as they stood before this round) and read against the finding that cites it. All 11 code citations
and the ticket lines they point at (`03:15`, `03:16`, `03:17`, `03:21`, `03:25`, `03:29`, `08:5`, `08:13`) hold the text the finding describes. Nothing cited is fabricated.

| Finding | Citation | Mark |
|---|---|---|
| 1 | skills/boss/boss_review.py:634-647 | VERIFIED (the argparse of `main()`, no stream-json option) |
| 2 | skills/boss/reviewer_chain.py:303-310 | VERIFIED (`_claude` builds the argv inline) |
| 3 | skills/boss/reviewer_chain.py:303-310 | VERIFIED |
| 3 | skills/boss/test_reviewer_chain.py:497-505 | VERIFIED (`--allowedTools` put ahead of `-p` for this reason) |
| 4 | skills/boss/reviewer_chain.py:236-250 | VERIFIED (`_run` takes no cwd) |
| 4 | skills/boss/boss_review.py:384-394 | VERIFIED (`_ask_codex` sets `cwd=checkout`) |
| 4 | skills/boss/boss_review.py:50-51 | VERIFIED (exit codes 0, 2, 3, 4, 6, 7; 1 is free) |
| 4 | skills/boss/boss_review.py:634-647 | VERIFIED (`--repo`, `--pr`, `--checkout`, `--author` all required) |
| 5 | skills/boss/reviewer_chain.py:335-379 | VERIFIED (no flag for `extra_args`) |
| 5 | skills/boss/boss_review.py:384-394 | VERIFIED (`--no-fallback` in the child's command line) |
| 6 | skills/boss/boss_review.py:634-647 | VERIFIED |
| 7 | skills/boss/boss_review.py:384-394 | VERIFIED (deadline `codex_timeout + REVIEW_CHAIN_SLACK`) |
| 7 | skills/boss/boss_review.py:608-625 | VERIFIED |
| 7 | skills/boss/policy.py:45-51 | VERIFIED |
| 8 | skills/boss/reviewer_chain.py:187-206 | VERIFIED (`TERM_GRACE`, `_stop`) |
| 8 | skills/boss/hermetic.py:104-159 | VERIFIED (`ignore_term` exists on the stub) |

## Disposition (Amara)

All eight are real. None is rejected. I checked the one claim that rested on the CLI rather than the code (finding 3) on the real `claude`: with an empty config directory and no credentials,
`claude --tools Read,Grep,Glob --strict-mcp-config --disable-slash-commands --permission-mode dontAsk -p --model claude-opus-5-5 ok` and `claude --tools Read -p ok` both reach the login
check, so `-p` ends a variadic option and the order Codex proposes holds.

| # | Verdict | What was done |
|---|---|---|
| 1 | Real | I had found it first (it is in the brief). The check box now says `--output-format stream-json --verbose`, and a test asserts both tokens in the diagnostic argv. |
| 2 | Real | One builder, `reviewer_chain.claude_argv(fallback, prompt)`, used by `_claude` and by the check; the diagnostic argv equals the real one but for the three stream-json tokens, and a test says so. |
| 3 | Real | The order is `claude [--allowedTools csv] [extra_args] -p --model M PROMPT`. The ticket's displayed call changes order accordingly (the flags move ahead of `-p`; the same flags and values). `Fallback` refuses a bare `--` and non-string `extra_args`. Tests: the whole argv as one list, an `extra_args=("--tools", "Read")` case, the order with `allowed_tools`. I did not choose `--` before the prompt: it would change the argv `boss-run` has always sent, and `-p` already ends every variadic option. |
| 4 | Real | The check is its own mode: `--check-fallback --checkout DIR`, `--repo`/`--pr`/`--author` refused (exit 2), `--checkout` required and never inferred from the current directory. It starts `claude` with `cwd=DIR` through `_spawn`. For production the ticket now says `_claude` inherits the directory, `_ask_codex` supplies it, and 08 keeps that (08's box already tests the directory its `claude` stub records). Exit 1 clashes with no code of the review command. |
| 5 | Real, the blocker | A `Fallback` object cannot cross the chain's command line, and 08 starts the chain as a child with `--no-fallback`. 03 now owns the transport: `reviewer_chain.py --fallback-extra-args JSON`, and `fallback_flags(fallback)`, which renders every field so that 08 cannot serialize a partial spec. Tests: round trip of a `Fallback` with every field set, and the stub receiving exactly `claude_argv(fallback_spec(), prompt)` through the command line. 08 gets a box saying `_ask_codex` hands over the whole spec (additive, marked as added by this round). |
| 6 | Real | The fail-closed contract is written out: newline-delimited JSON objects, exactly one init event, `tools` exactly `Glob`, `Grep`, `Read` (distinct), `mcp_servers` present and empty, `model` exactly the constant, `claude` exit 0; 15 fixtures (pass, extra tool, MCP server, wrong model, suffix, missing tool, duplicate tool, missing `mcp_servers`, wrong types, no init, two inits, non-JSON line, non-zero exit, timeout, `claude` absent). Exit 2 stays for usage. |
| 7 | Real, belongs to 08 | The outer deadline is `_ask_codex`'s, which 03 does not touch. 03's timeout box says so; 08 gets the deadline `codex_timeout + fallback_timeout + REVIEW_CHAIN_SLACK` when the fallback is on, and a test through `_ask_codex` itself. |
| 8 | Real | The Codex stub hangs and ignores SIGTERM, so the KILL after `TERM_GRACE` is exercised; the bound is `codex_timeout + fallback_timeout + TERM_GRACE + 5`, with a lower bound of the Codex timeout, both stated in the test. |

Not done: a second Codex round on the amended text. The fixes are Codex's own proposals applied as it wrote them (finding 5 with one addition, `fallback_flags`, so the transport cannot drop a
field), plus the facts checked on the real CLI. The review of the code, with the confinement argv asserted exactly, is where this ticket is looked at again.

Fix: the ticket's boxes (03 and one added box in 08), in the commit that adds this record.

## Settled (Amara)

My judgement on the spec: **settled, no second spec round.** Dispositions: 1 to 8 right, all applied; none declined. The two facts the design stands on (a variadic `--tools` swallows a trailing
prompt, `-p` ends it; stream-json needs `--verbose`) were checked on the installed CLI and are in the ticket with their dates. The seam with 08 is now written on both sides.
