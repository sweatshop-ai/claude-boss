# Ticket 15, code-review (Matt Pocock skill) on de6eec3 by Noor, 2026-11-04

Standards: no documented-standard breach; no shell bug (grep -v on an empty capture only sets $? inside the substitution, no `-e`). Smells, judgement calls: bare window literals 7/15, repeated `tr -s`, name `dialog_foot` holds the wider window, duplicated kind/width loops in two tests. Not applied.

Spec: applied: real footer in the `QUESTION` constant; miss-side numbers and the new `Yes, and switch to` residual in the CHANGELOG. Left: only 25 columns captured for "under 29" (stated); `tr -s` also applies to worker panes (adds detection only, patterns unanchored); the 7-line window rests on the worst-case question starting at 8 lines, a 3-line margin for the footer window in the 15.
