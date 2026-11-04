# 15: boss-workers-watch can miss a concierge's permission dialog on a narrow pane

**What to build:** PR 48 made the watchdog read only the last 15 lines of a concierge pane for permission, trust and footer text, so a concierge's relayed question is not read as a dialog. Two misses remain, found in Opus round 3 (`reviews/pr48-opus-round3.md`):
1. A concierge pane of about 29 columns or less: a real permission dialog has its `Do you want to` header more than 15 lines up and its footer and option lines wrapped, so a wrap between "Yes, and" and "always" leaves nothing to match. The live panes are 74 and 31 columns, so no pane in use today is affected.
2. An Edit dialog on such a pane: the reviewer recalls option 2 as "Yes, allow all edits during this session", which `Yes, and (always|don.t ask)` does not match. That wording is from memory and has not been seen in a capture.

Also unverified: the test fixture for a concierge's question assumes the AskUserQuestion footer is `Enter to select · Esc to cancel` and carries no `Tab to amend`. If the real footer carries it, every concierge question alerts again.

Build it in this order: capture real renders first (a real concierge AskUserQuestion, and Bash and Edit permission dialogs at 74, 31 and under 29 columns), then choose the window size and the patterns from those captures, and correct the fixtures. A wider window trades against false alerts on relayed "Do you want to" questions (round 2), so measure both.

Two false alerts stay as known residuals in PR 48: a boss-written option such as "Yes, and always use sonnet" in a concierge's question, and a worker printing "Yes, and always allow access" within its last 40 lines.

**Blocked by:** External: a real AskUserQuestion capture, which the boss takes at the next question through its concierge

**Status:** waits for a capture

- [ ] Real renders captured and kept as fixtures: a concierge question, Bash and Edit permission dialogs at 74, 31 and under 29 columns
- [ ] A concierge on a permission dialog at each width alerts; a concierge's question worded like a dialog does not
- [ ] The fixture's footer assumption checked against the real AskUserQuestion render
