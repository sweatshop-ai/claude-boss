# 40: a boss and a concierge show their role next to their name, wherever the owner reads it

**What to build:** Wherever the owner reads a session's name, a boss reads `Anton [boss]` and a concierge reads `Fatima [concierge]`. A plain worker stays as it is. Display only: the name is an address, so `ListAgents`, `SendMessage`, `boss-lifecycle.sh list`, the registry and the watchdog keep the bare name.

Why (the owner, 2026-11-05): a question arrived from a pane called Fatima and they did not know it was a concierge, or that it was new.

**Where the owner reads a name** (checked 2026-11-05):

| Place | Reads | Change |
|---|---|---|
| Claude Code status line, `cc-agent-names/scripts/statusline.py` | `session_name()`, bold, in front of row one | label added; boss from the marker file `pm/.boss-sessions/<session id>`, concierge from the pane's `@worker_role` (`$TMUX_PANE`) |
| tmux pane border (`~/.tmux.conf`, outside every repo) | `@worker_name`, then `@custom_title` | `@custom_title` gets the label (`Fatima [concierge] — dir`) in `mirror_name`; `@worker_name` stays bare, the watchdog and `fleet.py` read it |
| FleetView tile and project card, `agentview/fleet.py` + `index.html` | `name`, then a tag chip | a boss already has a `boss` chip; a concierge gets one, read from `@worker_role` of the session's tmux pane; `name` stays bare |
| The boss's own tmux pane | pane title Claude Code sets | not changed: nothing here shows a name for it |
| `boss-lifecycle.sh list`, `fleet.py` panes, registry, hooks | the bare name | not changed, on purpose; a test holds it |

- [ ] The status line shows `Name [boss]`, `Name [concierge]`, bare name otherwise; a boss or concierge with no marker or role shows the bare name.
- [ ] The pane title carries the role for a concierge; `@worker_name` and every parser stay bare.
- [ ] FleetView tags a concierge; `name` is untouched.
- [ ] A test in each repo: a label never reaches anything that resolves a name.

**Blocked by:** None (can start immediately)

**Claimed by:** Vikram 2026-11-05

**Status:** in progress

Codex owed: out until 2026-11-11 08:36; reviewed by a fresh Opus agent meanwhile.
