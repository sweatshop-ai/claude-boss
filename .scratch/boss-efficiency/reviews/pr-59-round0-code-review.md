# PR 59 round 0: standards and spec review (mattpocock-skills:code-review, once)

Head reviewed: c358feb. No CODING_STANDARDS, CONTRIBUTING, AGENTS or CLAUDE.md in the repo; conventions taken from the surrounding SKILL.md and CHANGELOG.

## Standards (judgement calls)
- Added bullets run past the ~90-column wrap of the P6 prose (owner's wording kept; not rewrapped).
- Dispatch quote is ~90 words against one or two sentences for its neighbours; it must be copyable, so kept, with a drift note added in P6.
- "the stop rule below" had no name: named in 3963e70.
- Public-repo check: no client name, transcript text or measured data beyond what was already in P6 and CHANGELOG.

## Spec
- Missing: the old "unless security or lost data" exception after the last round. Restored as class a in 3963e70.
- Dispatch omitted the definition of sensitive and "in doubt". Added in 3963e70, completed in 1130547.
- Scope: "added lines are those of the PR's diff" and the PR 11 rationale are small additions; CHANGELOG entry is longer than one line.
- Grep for the old rule: no other statement as a rule; CHANGELOG history left.
