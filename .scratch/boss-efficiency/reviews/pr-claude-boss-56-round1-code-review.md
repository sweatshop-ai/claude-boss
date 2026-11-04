# PR 56 (ticket 25), code-review round 1 (mattpocock-skills:code-review), head da9f375

Standards: no documented-standard breach (CONTEXT.md is a glossary). Smells, judgement calls: the unit list in `bin/boss-link` repeats install.sh's; `concierge_of(blocked=)` is a boolean flag argument; `FLAG_ARGUMENT` name. None changed except the one below.

Spec: all 11 boxes addressed. One defect: `echo x | wc -c /repo/src/app.ts` was still accepted, because `-c` was treated as value-taking for every filter. FIXED in the next commit ("-c takes a value for head, tail and cut, not wc"), test red before, green after (`VALUE_FLAGS` per filter).
