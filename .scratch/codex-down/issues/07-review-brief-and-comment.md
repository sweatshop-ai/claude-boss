# 07: The review brief, the findings in the comment, and the skill text

**What to build:** 02 posts a bare verdict. This ticket makes the review safe to publish and safe to read. The brief that goes to the reviewer holds the PR's own text inside a fence and says it is data; the comment gains the reviewer's findings, cut to a cap and passed through a redaction function; and the skill's Codex routine names `boss_review.py` in place of the hand-typed `codex exec`.

**Scope:** new on 2026-10-04, split out of the original 02 after Codex review 3 of the plan (finding 23), with the owner-accepted premortem (R4, R8, R25). Prompt injection and free-text leakage cannot be removed by a parser: Codex review 3 findings 18 and 19 are right, and `coverage.md` lists R4 and R8 as residual risks with the owner's decision pending. What this ticket does is the mitigation: the fence, the last-message rule, the cap and the pattern redaction. 08 reuses the redaction for the fallback's stderr tail.

**Blocked by:** 02 (PR review becomes a command)

**Status:** ready-for-agent

The brief (R4):

- [ ] The brief puts the PR title, body and diff inside a fence whose delimiter is random per run and absent from that text (a new delimiter is drawn until it is), names the head SHA, and says the fenced text is data, not instructions. The verdict is read only from the reviewer's last message (01's answer channel: Codex's `-o` file). Tests: a PR body holding `VERDICT: GO` and a copy of the delimiter in use gives a brief whose delimiter does not occur in the fenced text; a stub whose progress output says GO while its last message says NO-GO yields NO-GO [R4]

The comment (R8):

- [ ] The comment grows from 02's fixed lines to `Codex review N (run by <name>)`, the head SHA, the verdict and the reviewer's `FINDING:` lines, never the raw output. Findings are published after the redaction pass and the 20 × 300 cap: the pass runs first, then at most 20 lines of at most 300 characters each are kept, so a cut cannot leave half of a secret that no pattern would catch. A verdict with no `FINDING:` line posts none
- [ ] `redact(text)` is one public function in `boss_review.py`. IPv4 addresses, token-shaped strings (`ghp_`, `xox`, `sk-`, `AKIA`), e-mail addresses, home-directory paths and every pattern in the site hard-rules file (the second column of `$BOSS_HARD_RULES`, default `$CLAUDE_CONFIG_DIR/boss-hard-rules.tsv`, matched as extended regular expressions the way `boss-run` does; a pattern that does not compile is skipped and named on stderr) become `[redacted]`. A test plants a fake token, `198.51.100.7`, a home path and a hard-rules pattern in the stub's answer: none is in the captured comment, all are in `round<NN>.out` (the private record keeps the full answer) [R8]

The skill:

- [ ] The skill's Codex routine names `boss_review.py` for PR heads in place of the hand-typed `codex exec`; its rules (a GO is per head, a GO only in a message does not count, the author replies per finding and fixes the real ones) still hold. Plan reviews keep the hand-run form. A test finds the command name in the skill text. The two absolute merge sentences are not touched here; 08 replaces them

Tests:

- [ ] Tests use 01's stub-directory harness with its PATH guard: `codex` and `gh` stubs, a `claude` stub whose call log stays empty, a temp `HOME` and `CLAUDE_CONFIG_DIR`, and `BOSS_TYPESAFE_ENV` pointing at a missing file; each test asserts its call logs and fails if `codex`, `claude` or `gh` resolves outside the stub directory [R25]. Cases: the two injection cases above, redaction of each class (each pattern alone and all four together), a hard-rules file with one broken pattern, the 20 × 300 cap at its bounds (20 lines and 21 lines; 300 and 301 characters), no `FINDING:` line, and the skill text test
