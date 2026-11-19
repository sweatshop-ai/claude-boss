# boss-goal-graph — the ticket graph on every open goal page

**Built 2026-11-19** (goal-graph ticket 01). Anatomy: **body** = `boss-goal-graph.sh`, which runs
`skills/boss/goal_graph.py sweep` (no LLM); **pulse** = `boss-goal-graph.timer` (systemd user
timer, every minute); **brain** = this file (design record only).

## Why it exists

A goal with a `## Tickets` source carries a mermaid flowchart of its tickets at the top of the
page, which sheaf renders. Two callers redraw it the moment something happens: the boss pulse
after every worker turn, and `frontier.py claim` after a claim. A ticket edited by hand or by the
boss, with no worker turn after it, reaches the page through this sweep, within a minute.

## What it does

For every open track whose goal names a ticket source, it reads the frontier (a folder at once; a
GitHub graph from the pulse's cache, read again when older than two minutes) and rewrites the
block between the `ticket-graph` markers when, the read time aside, it changed. Nothing outside
the markers is touched, and an unchanged graph writes nothing, so an open page does not reload.

Each claimed ticket also carries its worker's sign (🔨 🧪 🔍, goal-graph ticket 02) when
`pm/goal-graph.signs-url` names an activity feed; a sign that changes is a changed graph, so the
sweep is what brings a worker starting or ending a turn onto the page, within a minute.

Silent when nothing changed. A track that cannot be read is one line on stderr, in the journal
(`journalctl --user -u boss-goal-graph`); a broken ticket source is named on the graph's own
summary line, under the last diagram that could be drawn.
