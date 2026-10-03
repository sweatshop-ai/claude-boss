# 03: Labelled fallback review

**What to build:** when Codex is not there or errors out, `boss_review.py` falls back to Claude Opus in read-only mode (decided by the owner 2026-10-03; do not reopen: only `codex` and `claude` are installed, so the fallback is the same family as the Claude workers, and the label, the recovery re-review of 06 and the gate of 04 make up for that). Its verdict is posted as "Fallback review (Codex unavailable: <reason>)" and recorded as a **provisional** GO or NO-GO. A provisional GO lets a merge go ahead only on a branch the repo marks non-deploying; 04 enforces that. This ticket also replaces the skill's two absolute merge sentences with that three-case rule.

**Scope:** amended 2026-10-04 after Codex review 1 of the plan (findings 3 and 4) and the owner-accepted premortem (R3 in part, R10, R11, R12, R13, R25). 03 adds the `provisional` value to the round record's `kind` (02 writes `codex`; 05 adds `waived`). The fallback stays inside the one code path of 02: same brief, same fence, same findings format, same redaction.

**Blocked by:** 02 (PR review becomes a command)

**Status:** ready-for-agent

Fallback spec (finding 3: "read-only" named and tested, R13):

- [ ] The fallback is the `claude` call `claude -p --model claude-opus-5-5 --tools "Read,Grep,Glob" --strict-mcp-config --disable-slash-commands --permission-mode dontAsk`, run with its working directory set to `--checkout`. The model id and each flag value are `policy.py` constants (`REVIEW_FALLBACK_MODEL`, `REVIEW_FALLBACK_TOOLS`, ...). Why these flags, checked 2026-10-04 with `claude` 2.1.288: `--tools` restricts the built-in tool set (its init event listed exactly `Glob`, `Grep`, `Read`); without `--strict-mcp-config` the same `--tools` value still left 511 tools in the init event, 508 of them MCP tools (mail drafts and file-store writes among them); `--allowedTools` only pre-approves tools and removes none, so it is not the mechanism
- [ ] 01's `Fallback` carries `allowed_tools`, which becomes `--allowedTools`. This ticket adds `extra_args: tuple[str, ...] = ()` to `Fallback` in `reviewer_chain.py`, placed on the `claude` argv before the prompt and covered by 01's stub-argv test style, unless 01 already has it. 03 passes `Fallback("opus", REVIEW_FALLBACK_MODEL, timeout=REVIEW_FALLBACK_TIMEOUT, when=("absent", "timeout", "error"), extra_args=(...))`
- [ ] The `claude` stub records its argv. A test asserts each flag and value above, that the `--tools` value is exactly `Read,Grep,Glob`, that `--model` is the policy constant, and that `--dangerously-skip-permissions`, `--allowedTools`, `--allowed-tools`, `--bare`, any `--mcp-config` and any `--permission-mode` other than `dontAsk` are absent
- [ ] `boss_review.py --check-fallback` starts the real fallback with those flags in stream-json mode and a one-word prompt, and exits 0 only if the init event lists exactly `Glob`, `Grep` and `Read`, no MCP servers, and the model id from the policy constant. The suite does not run it (it calls Claude). The author runs it once and pastes its output in the PR

When the fallback runs (R12) and what it is called (R13):

- [ ] The fallback is passed to 01's chain with `when=("absent", "timeout", "error")` (01's `Fallback.when`): it runs when Codex's attempt reason is one of those. On Codex `noverdict`, Codex answered: no fallback, exit 4 as in 02, and the `claude` stub's call log stays empty (01's default `when` would let it through; 03 narrows it). 06 adds one precondition: the fallback starts only with a usable `--track`. The round record, the comment and the log line carry the Codex reason and, for `error`, the exit code and a redacted stderr tail (last 2048 characters, through 02's redaction), so a Codex that fails on auth or quota reads differently from one that is down. To the gate they are the same outage; to the owner they are not
- [ ] The label's model name comes from 01's `Result.attempts` (the model id the fallback actually ran with), never from a constant string. A `claude` stub that rejects the model id gives no verdict, exit 4, and no "Opus" or model name anywhere in what is posted or written (R13)
- [ ] Codex and the fallback have separate timeout constants in `policy.py` (the Codex one is 02's, the fallback's is `REVIEW_FALLBACK_TIMEOUT`). A test makes a Codex stub sleep past a 1-second test timeout and shows the chain moves on to the fallback and logs the Codex attempt as `timeout`. (R3's boss-run side is 01's)

Verdict and record:

- [ ] A fallback GO is written as `kind: provisional` in `round<NN>.json`, with `reviewer` `opus` and `model` the id it ran with. A fallback NO-GO is `kind: provisional`, verdict `NO-GO`: it blocks like any NO-GO. Exit codes stay 0 GO posted and 3 NO-GO posted
- [ ] The comment's first line is `Fallback review (Codex unavailable: <reason>) - provisional GO` (or `... - NO-GO`), then the head SHA and the findings in 02's format. It is never headed "Codex review". The last line says: same model family as the workers, so Codex re-reviews this head before any deploy (R10)
- [ ] When both reviewers give nothing: exit 4, nothing posted, the round is `no-verdict`, both attempts are in `attempts.jsonl`

SKILL.md, the merge rule (finding 4, replace and not add):

- [ ] In `skills/boss/SKILL.md` the sentence "every PR gets a Codex review on the head that merges, before you merge it" and the sentence "No PR merges without a GO on record" are replaced by one rule with three cases: a Codex GO on the head that merges may merge; a provisional GO on the head that merges may merge only on a branch the repo marks non-deploying (04's gate decides); anything else does not merge. The sentence about merges "after Codex GO where nothing deploys" (in the paragraph on production steps) is reworded to match. The line "no merge order is given on a GO that exists only in a message" stays. A text test fails if `No PR merges without a GO on record` is still in the skill and checks that the new rule's wording appears exactly once

Tests:

- [ ] Cases: Codex absent + fallback GO, Codex timeout + fallback GO, Codex error + fallback NO-GO, both down, Codex `noverdict` (claude log empty), model rejected, argv assertion, Codex-sleeps-past-timeout. Each asserts the stub call logs and uses 01's harness with its PATH guard: the test fails if `codex`, `claude` or `gh` resolves outside the stub directory [R25]
