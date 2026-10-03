# Codex review 3c of the codex-down plan: ticket 01 after review 3b

Run by Anouk, 2026-10-04 00:16–00:20 (+02:00). Same setup as `plan-review-codex-3b.md` (Codex `codex-cli 0.147.0`,
`gpt-5.6-sol`, effort high, read-only, stdin closed), checkout root at commit `f93bd1d` (main). The brief added
review 3b and asked whether its four findings are answered.

**Verdict: NO-GO.** Codex confirms the four 3b findings are resolved. Three new points, all change the ticket
text. Point 1 changes the interface (additive: a trigger set on `Fallback`, default = today's `boss-run`); it is
reported to the boss. Points 2 and 3 are wording and test requirements. All three are settled in `b25ce2f` and a
run 3d follows. The citation marks are Anouk's; the checkout path prefix is removed from Codex's links.

## Codex's answer, verbatim

NO-GO

1. The shared interface cannot express ticket 03’s fallback policy. Current `boss-run` falls through to Haiku when Codex produces no usable verdict ([boss-run:149](skills/boss/bin/boss-run:149), [boss-run:154](skills/boss/bin/boss-run:154)), while ticket 03 requires that `noverdict` stop without invoking Claude ([03-labelled-fallback-review.md:20](.scratch/codex-down/issues/03-labelled-fallback-review.md:20)). Ticket 01 distinguishes `noverdict`, but its fixed signature only enables or disables the fallback wholesale ([01-one-reviewer-chain.md:48](.scratch/codex-down/issues/01-one-reviewer-chain.md:48), [01-one-reviewer-chain.md:59](.scratch/codex-down/issues/01-one-reviewer-chain.md:59)). Implementing either policy globally therefore breaks one caller. **Ticket text change: yes. Interface change: yes**—add a fallback-trigger policy to `Fallback` or `run_chain`, with `boss-run` including `noverdict` and ticket 03 excluding it.

2. “The module writes no file” contradicts the required Codex answer channel. The box forbids file writing ([01-one-reviewer-chain.md:73](.scratch/codex-down/issues/01-one-reviewer-chain.md:73)), but the contract requires reading Codex’s `-o` last-message file ([01-one-reviewer-chain.md:59](.scratch/codex-down/issues/01-one-reviewer-chain.md:59)); today that requires creating and deleting a temporary file ([boss-run:141](skills/boss/bin/boss-run:141), [boss-run:147](skills/boss/bin/boss-run:147)). Clarify that the module writes no persistent/caller-owned artifact and must remove its temporary file. **Ticket text change: yes. Interface change: no; wording/acceptance criterion only.**

3. No box pins Codex’s explicit read-only invocation. Today `boss-run` supplies `-s read-only`, `--skip-git-repo-check`, and the configured reasoning effort ([boss-run:144](skills/boss/bin/boss-run:144)). The characterization box checks stdin, diagnostics, and last-message handling, but not those argv values ([01-one-reviewer-chain.md:85](.scratch/codex-down/issues/01-one-reviewer-chain.md:85)). The move could silently drop the explicit sandbox while all named tests pass. Require the Codex stub’s recorded argv to assert these flags and the selected effort. **Ticket text change: yes. Interface change: no; test wording only.**

The amendment does resolve all four findings from review 3b: precedence at lines 59/87, Codex output selection at lines 59/85/87, staged tests at line 83, and matching properties at lines 61/85.
## Citation check (Anouk)

| Point | Citation | Mark |
|---|---|---|
| 1 | boss-run:149, :154 (a Codex answer with no usable verdict falls to `claude`) | VERIFIED |
| 1 | 03-labelled-fallback-review.md:20 (fallback runs on `absent`, `timeout`, `error`; Codex `noverdict`: no fallback, `claude` call log empty) | VERIFIED (the working copy of 03, which the other worker has edited and not yet committed) |
| 1 | 01:48, 01:59 (signature and "which output counts" paragraph at `f93bd1d`) | VERIFIED |
| 2 | 01:73 ("the module writes no file"), boss-run:141 (`mktemp`), :147 (`-o "$last"`) | VERIFIED |
| 3 | boss-run:144 (`-s read-only`, `--skip-git-repo-check`, effort at :146), 01:85 (characterization box has no argv) | VERIFIED |

Nothing cited is fabricated; no line number was off.
