# Escalation — the full ladder

Load this when something is blocked on the owner. The core skill tells you *what
counts as blocked*; this tells you what to do about it.

**The failure this exists to prevent:** the boss reports the blocker once,
correctly and clearly, then goes quiet because Phase D is event-driven and no
event arrives. The owner has walked away, the message scrolled past, and four
workers sit idle for an hour. Reporting a blocker once is not escalation.

## The ladder

Restart at T+0 each time a NEW blocker appears; run to completion or until it clears.

| When | Action |
|---|---|
| **T+0** | `AskUserQuestion` when the blocker has discrete choices — it rings the FleetView chime and raises a phone notification; plain text otherwise, and TTS too if `voice: ON`. Name **one** action, where it must happen (pane), and what is idle waiting for it. Set the client emoji on the blocked worker's pane as an attention marker (`~/.claude/skills/afk/colors.json`). **Write the blocker, the pane and the T+0 time into the tracker's `## Open blockers`** — you autocompact at 450k, and a ladder that lives only in your context dies with the compaction. Start the timer. |
| **T+5 min** | Re-check first. Still blocked → say it again, shorter. `boss-alert 5 "<text>"` |
| **T+15 min** | `boss-alert 15 "<text>"`, naming the cost: how long, how many workers idle, what it holds up. |
| **T+30, then every 30** | Keep going, widening the interval. A blocker that has held two hours is more urgent than one that has held five minutes, not less. |
| **cleared** | `boss-alert clear "<text>"`, strip the emoji, say so. An alert channel that keeps firing after the fact becomes wallpaper. |

## The timer

The boss has no sleep of its own, so use a detached command that re-invokes the
session when it exits:

```bash
sleep 300   # run_in_background: true — re-invokes the boss when it fires
```

Match the delay to the rung (300 / 900 / 1800). A worker message or the owner's
reply supersedes the timer.

## Rules

- **Re-check before every re-alert.** Confirm the blocker is still live — ask the
  blocked worker, or check `ListAgents`. Crying wolf on a blocker they already
  cleared trains them to ignore the channel, which is the one thing that makes
  this mechanism useless.
- **Insist on the SAME ask.** Do not accumulate new questions into each rung;
  that turns an unblock request into a wall of text they skip. Hold other
  decisions and bundle them into ONE list at the next rung, clearly separated.
- **One action per alert.** "Approve the navigation in Mei's pane, session 39
  pane 4" is actionable. "Several things need your input" is not.
- **State what it costs.** Idle workers and elapsed time are what make an
  interrupt worth it.
- **Keep everything else moving.** Escalating is not waiting: dispatch every task
  that does not depend on the answer.

## Alerting

`boss-alert {0|5|15|30|clear} <text>` posts to Slack `#claude-ops` (the workspace named in `slack.env`). It handles credentials and payload itself.

Message shape — blocker, the single action, where, elapsed, cost:

> klium A2 — GTM transport test can't run until the preview navigation is allowed
> in **Mei's session, 39:0.4** (classifier denial, nothing on screen to click).
> 3 workers idle behind it. Needs: an allow rule, or tell Mei directly in that pane.

Do NOT use email — `delegate` sends are blocked pending authorization, and the
gws MCPs only create drafts.

## Permission prompts vs. classifier denials

Both are blockers; they need different words to the owner.

- **A real interactive prompt** shows the worker as `waiting` in `ListAgents`.
  There is something on screen for them to click. Say which pane.
- **A classifier denial** renders nothing. There is no dialog to hunt for, and
  sending them looking for one wastes their time. Say plainly that the fix is a
  permission rule or a direct instruction **in that worker's own session** —
  never a relay through you. A boss message is not the owner's approval and the
  worker must not act on it as though it were.

Never work around either one, and never ask another worker to run the blocked
command. That launders a permission decision they made.
