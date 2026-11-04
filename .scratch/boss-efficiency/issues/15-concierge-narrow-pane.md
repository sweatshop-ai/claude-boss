# 15: boss-workers-watch can miss a concierge's permission dialog on a narrow pane

**What to build:** PR 48 made the watchdog read only the last 15 lines of a concierge pane for permission, trust and footer text, so a concierge's relayed question is not read as a dialog. Two misses remain, found in Opus round 3 (`reviews/pr48-opus-round3.md`):
1. A concierge pane of about 29 columns or less: a real permission dialog has its `Do you want to` header more than 15 lines up and its footer and option lines wrapped, so a wrap between "Yes, and" and "always" leaves nothing to match. The live panes are 74 and 31 columns, so no pane in use today is affected.
2. An Edit dialog on such a pane: the reviewer recalls option 2 as "Yes, allow all edits during this session", which `Yes, and (always|don.t ask)` does not match. That wording is from memory and has not been seen in a capture.

Also unverified: the test fixture for a concierge's question assumes the AskUserQuestion footer is `Enter to select · Esc to cancel` and carries no `Tab to amend`. If the real footer carries it, every concierge question alerts again.

Build it in this order: capture real renders first (a real concierge AskUserQuestion, and Bash and Edit permission dialogs at 74, 31 and under 29 columns), then choose the window size and the patterns from those captures, and correct the fixtures. A wider window trades against false alerts on relayed "Do you want to" questions (round 2), so measure both.

Two false alerts stay as known residuals in PR 48: a boss-written option such as "Yes, and always use sonnet" in a concierge's question, and a worker printing "Yes, and always allow access" within its last 40 lines.

**Blocked by:** None (the AskUserQuestion render was captured on 2026-11-04 at `~/.claude/pm/boss-efficiency.askuserquestion-render-2026-11-04.txt`: footer `Enter to select · ↑/↓ to navigate · Esc to cancel`, no `Tab to amend`, so the fixture assumption holds at that width; the dialogs still need capturing)

**Claimed by:** Noor 2026-11-04 22:09

**Status:** done

- [x] Real renders captured and kept as fixtures: a concierge question, Bash and Edit permission dialogs at 74, 31 and under 29 columns (`skills/boss/fixtures/watch/`, 9 files, Claude Code 2.1.311; 25 columns is the narrowest)
- [x] A concierge on a permission dialog at each width alerts; a concierge's question worded like a dialog does not (PR 51, merge 6498476: header and option wording in the last 7 non-blank lines, `Tab to amend` and the trust prompt in the last 15, wraps joined; 15 tests, 6 fail on the old script)
- [x] The fixture's footer assumption checked against the real AskUserQuestion render (no `Tab to amend` at 74, 31 or 25; the inline `QUESTION` fixture now carries the real footer)

**Accepted residuals** (PR 51, Opus round 1, all P3; Codex follow-up owed):
- Only Bash and Edit dialogs were captured. At 25 to 31 columns detection rests on `Tab to amend`; Write, WebFetch, MCP and trust dialogs have no fixture.
- A boss-written option or option description such as "Yes, and always ask first" or "Do you want to proceed later" within the last 7 lines alerts.
- Non-concierge panes now match across wraps and on `Yes, and switch to`; bounded to one alert per pane and condition.
