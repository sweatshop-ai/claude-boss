# claude-boss

One Claude Code session coordinates the others. It dispatches work to worker
sessions, keeps its tracker on disk, escalates a blocker on a timer, and asks
you one question when it needs you.

The hard part is not dispatching. It is a coordinator that quietly stops
coordinating — starts writing the code itself, forgets a worker went idle, or
ends its turn while blocked and says nothing. Six hooks exist for that, and each
one came from a measured failure rather than a guess.

## What the hooks do

| Hook | Event | What it catches |
|---|---|---|
| `boss-guard.py` | PreToolUse | The boss implementing instead of delegating. Says so once, then keeps a running count — measured across 21 sessions, the old version repeated one sentence 2,589 times, about 215,000 tokens. |
| `boss-pulse.py` | Stop | A boss going quiet with idle workers, an overdue escalation rung, or an open blocker it never put to anyone. |
| `boss-compact.py` | PreCompact, SessionStart | Hands the tracker back after an autocompact, so a 450k compaction costs the boss nothing. |
| `boss-jev.py` | UserPromptSubmit | Idle notices that carry no news, swallowed before they wake the boss. |
| `boss-reap.py` | SessionEnd | Per-session state outliving its session. |

They all early-exit unless the session registered itself as a boss, so an
ordinary session pays a process spawn and nothing else.

## Install

```bash
/plugin marketplace add sweatshop-ai/cc-agent-names
/plugin install claude-boss@sweatshop-ai
```

Then, from the checkout, for the parts a plugin cannot do — state directories
and the two systemd timers:

```bash
./install.sh          # BIN=1 also puts boss-start on your PATH
```

Start a boss inside tmux:

```bash
skills/boss/bin/boss-start [track]     # then type /boss
```

## What it needs

**tmux.** A boss spawns workers into panes and reads their state from them. It
cannot start without one.

Everything else is optional and degrades quietly:

| | For | Move it with |
|---|---|---|
| a Slack credentials file | escalation alerts to a channel | `BOSS_SLACK_ENV` (default `~/.config/tiroir/slack.env`) |
| a TypeSafe API key file | the TypeSafe half of the jev filter | `BOSS_TYPESAFE_ENV` (default `~/.config/tiroir/typesafe.env`) |
| a session dashboard that watches `status: waiting` | the chime that rings when the boss is waiting on you | — |
| [cc-agent-names](https://github.com/sweatshop-ai/cc-agent-names) | human names in the roster instead of machine strings | — |

cc-agent-names is **not** a dependency. Claude Code writes the session registry
and names sessions itself; the plugin swaps a machine name for a human one. A
roster of eight just reads better. With it installed, a name the boss gives a
worker (`spawn <dir> <name>`, `claim <pane> <name>`) goes through its
`agent-name set` and survives the next prompt and a resume; without it the
name is written straight into the session's peer file.

Two more files are yours and deliberately not in this repo, because putting them
here would publish what they exist to protect:

| File | What it holds |
|---|---|
| `$CLAUDE_CONFIG_DIR/boss-redact.json` | `hosts`, `persons` and `owner` — the names `tools/boss-event-jev.py` replaces with `<HOST>`, `<PERSON>` and `OWNER` before anything leaves the machine. `owner` is separate because the model is asked whether a step needs your own hand, so it has to tell you from everyone else. See `tools/boss-redact.example.json`. Absent, the pattern rules still run and no name is invented. |
| `$CLAUDE_CONFIG_DIR/boss-hard-rules.tsv` | `name<TAB>regex` lines naming your own off-limits hosts, paths and services. `boss-run` checks them exactly like its built-in rules. Absent, only the generic rules apply. |

Point `BOSS_REDACT_LIST` and `BOSS_HARD_RULES` elsewhere if you prefer.

## The board

Phase C reads a GitHub project board, and which board is yours, not this
plugin's. Set `BOSS_BOARD_OWNER`, and optionally `BOSS_BOARD_REPO` and
`BOSS_BOARD_NUMBER`. With none set the boss skips Phase C and says so.

## Where things live

Code is this repo. State is your Claude config dir, and neither install nor
uninstall touches it:

```
$CLAUDE_CONFIG_DIR/pm/              trackers, objectives, markers
$CLAUDE_CONFIG_DIR/routines/        timer state and logs
```

Every path is an environment variable with a sensible default, so the plugin
installs on a machine that looks nothing like the one it grew up on.

## Upgrading from the pre-plugin layout

If you ran the boss out of `~/.claude/skills/boss/` with the six hooks typed
into `settings.json`, those hooks now fire twice — once from the file, once from
the plugin. Strip the hand-written ones:

```bash
python3 scripts/unwire-legacy-hooks.py --dry-run ~/.claude/settings.json
MIGRATE=1 ./install.sh
```

It removes only entries naming a boss script, leaves every other hook alone, and
writes a timestamped backup first.

## Tests

```bash
for t in skills/boss/test_boss_*.py; do python3 "$t"; done    # 119
```

They run each hook the way the harness does — as a process, JSON on stdin,
against a throwaway `CLAUDE_CONFIG_DIR`. Nothing touches your real state, calls
TypeSafe, posts to a channel or moves a tmux pane.

## License

MIT.
