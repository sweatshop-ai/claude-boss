# 02: PR review becomes a command

**What to build:** today the PR gate is prose in the boss skill: each worker types `codex exec` by hand. This ticket gives the worker one command to run on a PR head. It runs Codex read-only through the shared chain (Codex only, no fallback yet), writes the round's full output to a file that stays on disk, and posts "Codex review N (run by <name>)" on the PR with the reviewed head SHA and the verdict. The skill's review routine points to the command. Every outage now passes through one place where it can be seen and counted.

**Blocked by:** 01 (One reviewer chain, shared)

**Status:** ready-for-agent

- [ ] One command reviews a PR head: Codex read-only, stdin closed, output written to a per-round file
- [ ] It posts the verdict on the PR with the round number, reviewer, author name and head SHA
- [ ] When Codex does not answer it exits non-zero, posts nothing that reads as a verdict, and records the failure (time, PR, reason) where the boss can read it
- [ ] The skill's routine section names the command; the rules (a GO is per head, a GO only in a message does not count) still hold
- [ ] Tests with a stubbed `codex` and a stubbed `gh`: GO, NO-GO, timeout
