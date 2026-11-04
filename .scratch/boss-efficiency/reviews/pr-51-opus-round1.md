# PR 51 (ticket 15), Opus fallback round 1 of 3, head 78fe68f, run by Noor. Codex unavailable until 23:38; Codex follow-up owed.

Verdict: GO, no P1. Reviewer ran the one test file: 15 pass.

Checked by hand on the fixtures: edit-25 is caught only by the footer (`Tab to / amend`, lines 1-2 of the 15 window; a 3-5 line status bar still leaves it at 6-7). ask-25/31/74: the last 7 non-blank lines hold no header and no "Yes, and": no false alert. Empty capture is safe (no `set -e`). Docs row matches the code.

Findings (all P3):
1. Only Bash and Edit dialogs captured; at 25-31 columns detection rests on `Tab to amend`. Write, WebFetch, MCP and trust dialogs have no fixture. routines/boss-workers-watch.sh:120-121 VERIFIED; CHANGELOG.md:13-14 VERIFIED.
2. A boss-written option description in the last 7 lines ("Yes, and always ask first", "Do you want to proceed later") alerts; the documented residual names only the option. routines/boss-workers-watch.sh:119 VERIFIED; CHANGELOG.md:15-16 VERIFIED.
3. Non-concierge panes: the 40-line capture is now joined and `switch to` added, so wrapped phrases and chat mentioning "Yes, and switch to" match. Bounded to one alert per pane and condition. routines/boss-workers-watch.sh:103,119 VERIFIED.
Also: "matching starts at 8" holds because every AskUserQuestion option carries a description line.

Outcome: findings 1-3 go to the PR body as residuals; no head change, so this verdict stands for 78fe68f.
