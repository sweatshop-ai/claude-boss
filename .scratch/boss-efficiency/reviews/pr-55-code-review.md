# PR 55 code-review (mattpocock-skills:code-review), head 1f22b73

## Standards
No hard violations. SKILL.md: the *"..."* quote markers are intact, the sentence is copyable word for word. CHANGELOG: no client name, measured data or transcript text. Two optional smells, not applied (scope was one sentence): (1) "them" sits far from its antecedent after the parenthetical; (2) "never the URL as a whole and never a password or token" says the same thing twice.

## Spec
No missing requirements, no scope creep, nothing wrong. grep over skills/ routines/ docs/ .github/ finds no other copy of the instruction; the only other hit is the 0.20.0 CHANGELOG history line, left as written. No version bump: Unreleased accumulates without one (PR 52 did the same, plugin.json stays 0.21.3).

Summary: Standards 2 judgement calls (optional), Spec 0 findings.
