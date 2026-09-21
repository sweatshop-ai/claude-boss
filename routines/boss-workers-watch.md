# boss-workers-watch — external watchdog for boss/worker Claude sessions

**Built 2026-08-10.** Anatomy: **body** = `boss-workers-watch.sh` (pure bash, no
LLM), **pulse** = `boss-workers-watch.timer` (systemd user timer, every minute),
**brain** = this file (design record only — the body never invokes Claude).

## Why it exists

The `/boss` skill's Phase D monitoring is deliberately **event-driven**: worker
messages and idle notifications re-invoke the boss; there is no polling loop.
That design has a blind spot: a worker that dies on an API error (e.g. after a
power/network blackout, 2026-08-10 incident) emits no message and no idle event
— nothing ever wakes the boss. Worse, the boss session is usually frozen on the
same API error. So the watchdog must live **outside every Claude session**, in
plain bash, with no dependency on the Claude API, Claude Code, or any MCP.

## What it checks (per tmux pane, last 40 visible lines)

| Condition | Signal | Alert after |
|---|---|---|
| `api-error` | error banner (API Error, overloaded, rate limit, timeout, connection failure, expired OAuth), not currently retrying | 2 consecutive minutes |
| `api-retrying` | `Retrying in Ns…` visible — auto-retry usually heals itself | 5 consecutive minutes |
| `permission-prompt` | a tool-permission dialog sitting unanswered | 2 consecutive minutes |
| `frozen` | `esc to interrupt` shown but pane content hash identical across runs (a live TUI redraws its spinner constantly) | 3 consecutive minutes |
| `at-shell` | a pane with `@worker_name` set (spawned by `boss-lifecycle.sh`) back at a bare shell — crashed or retired | 2 consecutive minutes |

Silent when healthy; no tmux server running → immediate silent exit, so the
timer costs nothing outside boss sessions.

## Alerting

- **One alert per pane+condition** (tracked in `state/boss-workers-watch.state`),
  aggregated into a single message per run; a **recovery note** when it clears.
- **`notify-send` first** (works with no internet — the blackout case), then
  **Slack #claude-ops** (creds `~/.config/tiroir/slack.env`), best-effort.
- Recovery = the boss/the owner acts on the alert; the watchdog is **read-only**,
  it never restarts panes or injects keys.

## Test hooks

```bash
DRY_RUN=1 FAKE_PANES=<tsv> FAKE_CAP_DIR=<dir> ~/.claude/routines/boss-workers-watch.sh
```

`FAKE_PANES` = `tmux list-panes` TSV (`pane_id  index  cmd  path  @worker_name`);
`FAKE_CAP_DIR` contains `<pane-id-without-%>.txt` captures. `DRY_RUN` prints
would-be notifications and leaves state untouched. Log:
`~/.claude/routines/logs/boss-workers-watch.log` (self-rotating at 512K).
