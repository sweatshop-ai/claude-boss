# Codex review 3b of the codex-down plan: ticket 01 with its interface

Run by Anouk, 2026-10-04 00:12–00:15 (+02:00). Reviewer: Codex (`codex-cli 0.147.0`, model `gpt-5.6-sol`,
reasoning effort high), `codex exec -s read-only --skip-git-repo-check`, stdin closed, working directory the
checkout root at commit `82f2746` (main). Named 3b because another worker uses 3, 4, ... for tickets 02 to 05.

Scope: `.scratch/codex-down/issues/01-one-reviewer-chain.md` as amended in `82f2746` (interface section,
verdict-matching rule, boxes). Briefed to read and not execute, to answer GO or NO-GO first, to cite paths, and
to say for each finding whether it changes the interface or only the wording. Not to re-raise: the `gh` guard,
review 1 findings 4, 5, 7, and the owner's two settled points (anchored prefix match for APPROVE/REJECT,
whole-token for GO/NO-GO; `boss-run` passes Haiku explicitly).

**Verdict: NO-GO.** Four findings, all change the ticket text. None challenges the agreed interface: the
dataclasses, the `run_chain` signature, the CLI and its exit codes stay as they are. Findings 1 and 2 define
semantics the interface left open, and the answer in both is "as `boss-run` does today". Findings 3 and 4 are
test staging and wording. All four are settled in the ticket text and a further run follows (3c).

The citation marks below are Anouk's, made by reading each cited line after the run (ticket lines at
`82f2746`). The checkout path prefix is removed from the links in Codex's text; nothing else in it is changed.
The full run log is kept outside the repository.

## Codex's answer, verbatim

NO-GO

1. The failure taxonomy conflicts with preserving current `boss-run` behavior. Ticket 01 defines any non-zero reviewer exit as `error` ([01-one-reviewer-chain.md:72](.scratch/codex-down/issues/01-one-reviewer-chain.md:72)). Today, `boss-run` ignores the process status and accepts a usable verdict from the output even after a non-zero exit ([boss-run:144](skills/boss/bin/boss-run:144), [boss-run:148](skills/boss/bin/boss-run:148), [boss-run:155](skills/boss/bin/boss-run:155)). The ticket must decide precedence among a usable verdict, timeout, and non-zero exit, then test it. **Ticket text change: yes; interface change:** yes—the semantics of `Attempt.reason` and whether the CLI reports an answering reviewer change.

2. The interface does not define which Codex output becomes `Attempt.output`. Current `boss-run` parses only Codex’s `-o` last-message file and discards progress output ([boss-run:144](skills/boss/bin/boss-run:144), [boss-run:147](skills/boss/bin/boss-run:147), [boss-run:148](skills/boss/bin/boss-run:148)); ticket 02 depends on that distinction ([02-pr-review-command.md:27](.scratch/codex-down/issues/02-pr-review-command.md:27)). Ticket 01 merely calls it the reviewer’s “raw answer” ([01-one-reviewer-chain.md:36](.scratch/codex-down/issues/01-one-reviewer-chain.md:36)), while its compatibility box only prevents diagnostics from reaching `boss-run`’s streams ([01-one-reviewer-chain.md:81](.scratch/codex-down/issues/01-one-reviewer-chain.md:81)). A worker could parse captured progress output and still satisfy the stated tests. Require the Codex last-message channel and a progress-output-versus-final-answer test in 01. **Ticket text change: yes; interface change:** yes—this defines `Attempt.output`/`Result.output`.

3. The pre/post-test requirement is impossible literally. The heading says all subsequent compatibility tests must pass on unchanged `boss-run` ([01-one-reviewer-chain.md:79](.scratch/codex-down/issues/01-one-reviewer-chain.md:79)), but unchanged `boss-run` neither reads `BOSS_RUN_REVIEW_TIMEOUT` ([boss-run:38](skills/boss/bin/boss-run:38)) nor invokes `python3`; boxes 82–83 require tests of that new environment variable and crashing/garbage-emitting `python3` stubs ([01-one-reviewer-chain.md:82](.scratch/codex-down/issues/01-one-reviewer-chain.md:82), [01-one-reviewer-chain.md:83](.scratch/codex-down/issues/01-one-reviewer-chain.md:83)). Separate unchanged-code characterization tests from post-move integration tests. **Ticket text change: yes; interface change:** no, wording/test staging only.

4. “Today’s anchored prefix match” does not fully pin today’s parser. The existing expression is case-insensitive and permits leading whitespace and whitespace after the colon ([boss-run:131](skills/boss/bin/boss-run:131)); the amended rule specifies prefix behavior but not those properties ([01-one-reviewer-chain.md:57](.scratch/codex-down/issues/01-one-reviewer-chain.md:57)). State and test them if `boss-run` must behave exactly as today. **Ticket text change: yes; interface change:** yes—the verdict-matching semantics of `words` are part of the fixed callable contract.
## Citation check (Anouk)

| Finding | Citation | Mark |
|---|---|---|
| 1 | 01:72 (any non-zero exit is `error`) | VERIFIED |
| 1 | boss-run:144, :148, :155 (`timeout … codex exec`, `out=$(cat "$last")`, `claude -p …`): no `$?` is read anywhere in :139-163, so a usable verdict after a non-zero exit is accepted today | VERIFIED |
| 2 | boss-run:144, :147, :148 (Codex answer read from the `-o` file, stdout and stderr to /dev/null) | VERIFIED |
| 2 | 02-pr-review-command.md:27 ("read only from the reviewer's last message"; a stub whose progress says GO while its last message says NO-GO yields NO-GO) | VERIFIED |
| 2 | 01:36 (`output` is "the reviewer's raw answer"), 01:81 (diagnostics must not reach boss-run's streams) | VERIFIED |
| 3 | 01:79 (heading: all compatibility tests pass on the unchanged `boss-run`), 01:82 (`BOSS_RUN_REVIEW_TIMEOUT`), 01:83 (stub `python3`); boss-run:38 (`TIMEOUT=120`, no env var) | VERIFIED |
| 4 | boss-run:131 (case-insensitive `-i`, `^[[:space:]]*VERDICT:[[:space:]]*`), 01:57 (the rule names prefix behaviour only) | VERIFIED |

Nothing cited is fabricated; no line number was off.
