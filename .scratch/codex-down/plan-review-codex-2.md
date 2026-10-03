# Codex review 2 of the codex-down plan: ticket 01 as amended

Run by Anouk, 2026-10-04 00:02–00:07 (+02:00). Reviewer: Codex (`codex-cli 0.147.0`, model `gpt-5.6-sol`,
reasoning effort high), `codex exec -s read-only --skip-git-repo-check`, stdin closed, working directory the
checkout root at commit `50af3d3` (main).

Scope: `.scratch/codex-down/issues/01-one-reviewer-chain.md` as amended in `50af3d3`. The plan, tickets 02 to 05,
`plan-review-codex-1.md`, `CONTEXT.md` and `skills/boss/bin/boss-run` were given as context. Findings 4, 5 and 7
of review 1 (tickets 03 to 05) were excluded from the brief. Briefed to read and not execute, to answer GO or
NO-GO first, and to cite paths. The brief also described the intended design (a Python module with a CLI that
`boss-run` calls); the signature in that brief is where finding 1 comes from.

**Verdict: NO-GO.** All five findings ask for a change to the ticket 01 text.

The citation marks below are Anouk's, made by reading each cited line after the run. The checkout path prefix
is removed from the links in Codex's text; nothing else in it is changed. The full run log is kept outside the
repository.

## Codex's answer, verbatim

NO-GO

1. The callable contract is contradictory and cannot be implemented literally. The intended Python signature places required `effort` after defaulted `codex_timeout`, which is invalid unless reordered or made keyword-only. The ticket never specifies `effort` or the CLI contract; it also says Haiku is a default, then describes an optional fallback, while the fallback spec omits the separate timeout required later ([01:14](.scratch/codex-down/issues/01-one-reviewer-chain.md:14), [01:20](.scratch/codex-down/issues/01-one-reviewer-chain.md:20), [01:23](.scratch/codex-down/issues/01-one-reviewer-chain.md:23), [01:26](.scratch/codex-down/issues/01-one-reviewer-chain.md:26)). **Ticket text change: yes.** State a valid exact signature, the CLI serialization/exit contract, `effort`, and a fallback spec containing `name`, exact model ID, timeout, and optional tool restriction. Clarify that `fallback=None` is Codex-only and `boss-run` explicitly supplies Haiku.

2. The result contract can discard output ticket 02 requires. `output` is defined only as the answering reviewer’s raw answer ([01:21](.scratch/codex-down/issues/01-one-reviewer-chain.md:21)); when Codex emits text without a verdict, nobody “answered,” and `attempts` is not required to retain stdout. Ticket 02 nevertheless requires the round’s full output to remain available ([02:3](.scratch/codex-down/issues/02-pr-review-command.md:3), [02:9](.scratch/codex-down/issues/02-pr-review-command.md:9)). `parsed` is also undefined, the location of the fallback model ID is unspecified, and “a stderr tail” has no testable bound ([01:24](.scratch/codex-down/issues/01-one-reviewer-chain.md:24), [01:27](.scratch/codex-down/issues/01-one-reviewer-chain.md:27)). **Ticket text change: yes.** Define the exact `Parsed` and `Attempt` fields, null values, stdout retention for unsuccessful attempts, model-ID placement, and tail limit; require tests for every closed-set reason.

3. The compatibility box does not pin enough observable `boss-run` behavior. It names only exits 2–5, reviewer names, and log keys ([01:29](.scratch/codex-down/issues/01-one-reviewer-chain.md:29)). It omits dry-run exit 0, pass-through command status, exact log values, existing stdout/stderr text, closed reviewer stdin, suppression of reviewer diagnostics, and timeout/interruption behavior. Those behaviors currently appear at [boss-run:143](skills/boss/bin/boss-run:143), [boss-run:147](skills/boss/bin/boss-run:147), [boss-run:155](skills/boss/bin/boss-run:155), and [boss-run:221](skills/boss/bin/boss-run:221). “Prints nothing new” is weaker than preserving existing output. **Ticket text change: yes.** Require pre/post characterization tests for these behaviors, including timeout child cleanup and the guarantee that SIGINT/SIGTERM never reaches command execution.

4. “The first VERDICT line wins … as `boss-run` does today” is inaccurate ([01:25](.scratch/codex-down/issues/01-one-reviewer-chain.md:25)). Today’s grep selects the first line containing a usable `APPROVE|REJECT`, skipping earlier malformed `VERDICT:` lines ([boss-run:131](skills/boss/bin/boss-run:131)). The box also does not pin today’s case-insensitive `REASON:` parsing and `(no reason given)` default ([boss-run:133](skills/boss/bin/boss-run:133)). **Ticket text change: yes.** Say “first usable VERDICT line,” define strict conflict detection over usable normalized verdicts, and preserve/test reason parsing.

5. The hermetic-test box unnecessarily requires guarding `gh` ([01:28](.scratch/codex-down/issues/01-one-reviewer-chain.md:28)). Neither the shared chain nor `boss-run` invokes it; the only external reviewer commands are Codex and Claude ([boss-run:143](skills/boss/bin/boss-run:143), [boss-run:154](skills/boss/bin/boss-run:154)). `gh` belongs to ticket 02’s PR command. **Ticket text change: yes.** Remove `gh` from ticket 01’s guard and require it under ticket 02 instead.

## Citation check (Anouk)

| Finding | Citation | Mark |
|---|---|---|
| 1 | 01:14 (fallback model and timeout are parameters, `boss-run`'s values as defaults), 01:20 (fallback optional), 01:23 (fallback spec, no timeout in it), 01:26 (timeout per reviewer) | VERIFIED |
| 1 | "The intended Python signature places required `effort` after defaulted `codex_timeout`" | VERIFIED — in the brief Anouk gave Codex (`run_chain(prompt, words, codex_timeout=120, effort, fallback=…)`), not in the ticket; the ticket never mentions `effort`, which `boss-run` sets to medium at :146 |
| 2 | 01:21 (`output` is the answering reviewer's raw answer), 01:24 (attempts, "a stderr tail"), 01:27 (model id recorded; place unstated) | VERIFIED |
| 2 | 02-pr-review-command.md:3 and :9 (round's full output stays on disk; per-round file) | VERIFIED |
| 3 | 01:29 (exits 2-5, reviewer names, nine log fields) | VERIFIED |
| 3 | boss-run:143 (`command -v codex`; the `timeout … codex exec` call is :144), :147 (`</dev/null >/dev/null 2>&1`), :155 (`claude -p … </dev/null 2>/dev/null`), :221 (`PROMPT=$(render_prompt) || finish 2`) | VERIFIED |
| 4 | 01:25 ("first VERDICT line wins … as `boss-run` does today") | VERIFIED |
| 4 | boss-run:131 (grep takes the first line that matches `VERDICT:` + `APPROVE\|REJECT`) — run against samples: `VERDICT: maybe` then `VERDICT: REJECT` gives REJECT (the malformed line is skipped); `VERDICT: APPROVED` gives APPROVE (no word boundary), `VERDICT: approve` gives APPROVE | VERIFIED, and the second sample shows a prefix match that the whole-token rule in 01:25 will change |
| 4 | boss-run:133 (case-insensitive REASON parsing, `(no reason given)` default) | NOT FOUND at 133 — line 133 normalizes VERDICT; REASON parsing is :134 and the default is :135 |
| 5 | 01:28 (guard names `gh`); boss-run:143 and :154 (the only external reviewer commands are `codex` and `claude`) | VERIFIED — `boss-run` does not call `gh`, but it runs the approved command with `bash -lc` (:242), which is why Anouk read the `gh` guard as cheap protection for the tests of that path |

One wrong line number (133 for 134). Nothing cited is fabricated.
