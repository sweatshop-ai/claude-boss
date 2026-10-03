# Codex review 1 of the codex-down plan

Run by Anouk, 2026-10-03 23:56–23:58 (+02:00). Reviewer: Codex (`codex-cli 0.147.0`, model `gpt-5.6-sol`,
reasoning effort high), `codex exec -s read-only --skip-git-repo-check`, stdin closed, working directory the
checkout root.

Reviewed: `.scratch/codex-down/plan.md` and the five tickets in `.scratch/codex-down/issues/` at commit
`a5fe5fa` (main), plus `CONTEXT.md`, `skills/boss/bin/boss-run` and the Codex gate section of
`skills/boss/SKILL.md`. Briefed to read and not execute, to answer GO or NO-GO first, and to cite paths.

**Verdict: NO-GO.** Findings 1, 2, 3 and 6 touch ticket 01. Findings 4, 5 and 7 touch tickets 03, 04 and 05.

The citation marks below are Anouk's, made by reading each cited line after the run. The checkout path prefix
is removed from the links in Codex's text; nothing else in it is changed. The full run log (every command
Codex ran) is kept outside the repository.

## Codex's answer, verbatim

NO-GO

1. **Touches ticket 01:** the shared-chain interface cannot express ticket 02’s Codex-only mode. Ticket 01 defines an unconditional Codex → fallback → none chain and parameterizes only the fallback model and timeout ([01-one-reviewer-chain.md:3](.scratch/codex-down/issues/01-one-reviewer-chain.md:3), checkbox 2), while ticket 02 explicitly requires “Codex only, no fallback” ([02-pr-review-command.md:3](.scratch/codex-down/issues/02-pr-review-command.md:3)). Ticket 01 must define an optional/disabled fallback.

2. **Touches ticket 01:** its result contract is insufficient for tickets 02–05. It promises only the answering reviewer’s name (01 checkbox 3), but downstream tickets need the full output artifact, normalized verdict, failure reason, and whether the primary Codex attempt failed before a fallback answered ([02-pr-review-command.md:9](.scratch/codex-down/issues/02-pr-review-command.md:9), [03-labelled-fallback-review.md:10](.scratch/codex-down/issues/03-labelled-fallback-review.md:10), [05-dead-reviewer-blocker.md:13](.scratch/codex-down/issues/05-dead-reviewer-blocker.md:13)). The existing implementation communicates verdict and reason through globals, accepts only `APPROVE|REJECT`, suppresses command output, and deletes its temporary file ([boss-run:127](skills/boss/bin/boss-run:127), [boss-run:139](skills/boss/bin/boss-run:139)). Tickets 02–03 instead specify `GO`/`NO-GO`. Ticket 01 needs an explicit structured result, output-file ownership, failure taxonomy, and verdict vocabulary.

3. **Touches ticket 01:** “Claude Opus, read-only” has no enforceable interface or acceptance test. The only configurable fallback property in ticket 01 is its model; the current Claude invocation supplies `-p --model` but no explicit read-only policy ([boss-run:154](skills/boss/bin/boss-run:154)). A stub proving that Claude ran does not prove it was read-only. Ticket 03 must define the actual permission/tool restriction and test the invocation ([03-labelled-fallback-review.md:9](.scratch/codex-down/issues/03-labelled-fallback-review.md:9)).

4. The proposed provisional merge changes—and currently contradicts—the documented gate. The plan allows a fallback GO to authorize some merges ([plan.md:16](.scratch/codex-down/plan.md:16)), while the skill requires a Codex review on the exact merging head before every merge ([SKILL.md:518](skills/boss/SKILL.md:518)) and says no PR merges without that GO ([SKILL.md:525](skills/boss/SKILL.md:525)). Ticket 03 checkbox 3 merely adds the provisional rule; it does not require the old absolute language to be replaced or reconciled, so both contradictory rules could remain.

5. Ticket 04 has no defined enforcement point for its central safety property. It says the boss “never gives a merge order” and that a merge is “refused,” but neither ticket 02’s review command nor ticket 04 identifies a merge command, hook, configuration schema, or executable gate that performs that refusal ([04-codex-rerun-before-deploy.md:3](.scratch/codex-down/issues/04-codex-rerun-before-deploy.md:3), checkbox 4). Existing `boss-run` only checks command-text hard rules before review and knows neither PR review state nor target-branch deployment status ([boss-run:81](skills/boss/bin/boss-run:81), [boss-run:219](skills/boss/bin/boss-run:219)). Consequently, “merge refused” is not objectively testable as written.

6. **Touches ticket 01:** ticket 01 does not pin `boss-run`’s observable compatibility. Today rejection is exit 3, no reviewer is exit 4 ([boss-run:23](skills/boss/bin/boss-run:23)), the fallback reviewer is exactly `haiku` ([boss-run:154](skills/boss/bin/boss-run:154)), and every outcome logs the fixed fields `ts, session, cwd, why, cmd, reviewer, verdict, reason, exit` ([boss-run:49](skills/boss/bin/boss-run:49)). “The fallback’s name” in 01 checkbox 3 could become `claude` or the model ID, and its tests cover selector outcomes rather than exact exit/log contracts (01 checkbox 4). Those contracts need explicit regression assertions.

7. Ticket 05 has the wrong dependency and an undefined counter. It is blocked only by ticket 02 ([05-dead-reviewer-blocker.md:5](.scratch/codex-down/issues/05-dead-reviewer-blocker.md:5)) even though its owner prompt includes “accept the fallback review,” which does not exist until ticket 03 ([05-dead-reviewer-blocker.md:12](.scratch/codex-down/issues/05-dead-reviewer-blocker.md:12)). It also says “failed PR reviews”: if fallback GO makes the overall review successful, a prolonged Codex outage never reaches N; if it means failed Codex attempts, that must be stated and recorded even when fallback succeeds. The “merge on tests alone” option must also be scoped against the plan’s rule that deploying branches never accept provisional approval ([plan.md:19](.scratch/codex-down/plan.md:19)).

## Citation check (Anouk)

Each citation is the `file:line` Codex gave, read after the run.

| Finding | Citation | Mark |
|---|---|---|
| 1 | 01-one-reviewer-chain.md:3 (unconditional chain, fallback model as the one parameter) | VERIFIED |
| 1 | 01 checkbox 2 (fallback model and timeout are parameters; line 12) | VERIFIED |
| 1 | 02-pr-review-command.md:3 ("Codex only, no fallback yet"; Codex quoted it without "yet") | VERIFIED |
| 2 | 02-pr-review-command.md:9 (per-round output file) | VERIFIED |
| 2 | 03-labelled-fallback-review.md:10 (provisional stored distinct from Codex GO) | VERIFIED |
| 2 | 05-dead-reviewer-blocker.md:13 (the line exists; it is the recovery box, not a failure-reason box, so it supports the claim only loosely) | VERIFIED |
| 2 | boss-run:127 and :139 (globals VERDICT/REASON set at :133-135, only APPROVE\|REJECT at :131, output to /dev/null at :147, `rm -f` at :150/:157/:161) | VERIFIED |
| 3 | boss-run:154 (`claude -p --model "$HAIKU_MODEL"` at :155, no read-only flag) | VERIFIED |
| 3 | 03-labelled-fallback-review.md:9 | VERIFIED |
| 4 | plan.md:16 (decision 1; the provisional-GO sentence is lines 19-21) | VERIFIED |
| 4 | SKILL.md:518 (Codex review on the exact merging head) | VERIFIED |
| 4 | SKILL.md:525 ("No PR merges without a GO on record") | NOT FOUND at 525 — the sentence is at SKILL.md:528 |
| 5 | 04-codex-rerun-before-deploy.md:3 and checkbox 4 (line 12) | VERIFIED |
| 5 | boss-run:81 (hard_rules) and :219 (`check_hard_rules || finish 5`) | VERIFIED |
| 6 | boss-run:23 (exit codes 3 and 4 at :27-28), :154 (reviewer name `haiku` is set at :157), :49 (log fields at :50-64) | VERIFIED |
| 7 | 05-dead-reviewer-blocker.md:5 (blocked by 02 only) and :12 (option "accept the fallback review") | VERIFIED |
| 7 | plan.md:19 ("never on a branch that deploys") | NOT FOUND at 19 — the words are at plan.md:20-21 |

Both misses are off-by-a-few line numbers; the text each points at exists. Nothing cited is fabricated.
