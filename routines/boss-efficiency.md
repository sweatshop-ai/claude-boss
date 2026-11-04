# boss-efficiency — where the time and the tokens of the boss tracks go

**Built 2026-11-04** from the audit of that day. Anatomy: **body** =
`boss-efficiency.sh` (takes the transcripts lock, runs at nice 19), **core** =
`boss_efficiency_core.py` (the measures and the verdict, no LLM), **pulse** =
`boss-efficiency.timer` (Monday 06:17, `Persistent=true`), **brain** = this file.
The routine calls no model, so it has no token cost of its own.

## What it reports, per track, for the last seven days

| Measure | Where it comes from |
|---|---|
| Share of wall time by state: work, fix, test, review, ci, bg_other, ask, bossact, parked, nobody | segments of worker and boss transcripts, clipped to the window |
| Tokens by phase: build, fix (after the first review), sub_rev, sub_oth, boss | `usage` per assistant message, in cost units (input 1, cache write 1.25, cache read 0.1, output 5), plus subagent transcripts |
| Questions to the owner per day | `AskUserQuestion` calls in the track's boss sessions |
| CI waits | count and hours of `gh run watch`-style tools and monitors |
| Share of the week's token budget | the track's tokens over all tracks' |

The weekly usage cap itself is not readable from a transcript; the share of the
token budget is the proxy. `measure_track(index, track, start, end)` and
`coverage(index, track, start, end)` are callable per track (ticket 05).

## How workers are found

Through the boss's socket. Every message a boss sends carries
`<cross-session-message from="uds:...sock">`. A socket is tied to a track when it
sent at least two explicit "Boss dispatch ... track X" messages and 60% of its
dispatches name X; the tie is kept in state, so a boss that changes name or socket
is found again from its new dispatches. From a tied socket's first message, the
worker session belongs to that track until its next message. A boss session is a
marker in `pm/.boss-sessions/` or a `boss-marker register <track>` call. Only
tracks with a `pm/<track>.goal.md` (or seen before) are accepted as names.

**By name, for the workers no dispatch reaches** (ticket 17). A session records the
name it started with ("Your name in this session is X"). When the boss sent to X
(`SendMessage`) or heard from X (`from-name` is the name the session started with,
not the one the boss claims it under), the session counts for that track, from the
start of the boss's window on the track to the end of the session. The session must
have been alive at the message, because names are reused. Time a dispatch already
gave to a track stays with that track, and no stretch is counted twice. A session with
no recorded name is not guessed at.

## Where a track ends

A track whose goal was last marked met (`boss-goal status <track> met`, read from the
boss's command) ends at that mark or at its last commit whose command says "done",
whichever is later, plus a minute. The boss session left open after that is not the
track: its time, its tokens and the worker messages it gets are left out. A track not
marked met, or reopened after, runs to the end of its sessions as before. The commit
is read from the `git commit` command in the transcript, not from git history.

## Coverage check

Share of worker messages to a boss that no tracked worker session of that track
was active within ten minutes of. The audit of 2026-11-04 put it at 19%, but that was
an average. Over five weekly windows the fleet figure ranged from about 2% in quiet
weeks to about a third in busy ones, and on single busy tracks it was higher still.
So the report prints the count per track in an **Outside** column, and a line when
the fleet is above 40%, because a busy track's numbers can rest on a third of its
messages being unattributed. An anomaly on a track with 20% or more outside says so
in its own line. Coverage never triggers an alert by itself: it moved with the number
of workers, not with a change in the routine. Zero sessions found, a check run on
zero messages, or more than 90% of at least ten worker messages outside (the socket lookup found no workers; fewer than ten messages cannot show it) is a **failure** (exit 2, Slack), never a pass; a failed week is not
kept as a baseline.

## When it speaks

Slack `#claude-ops`, posted by the core (not `boss-alert`, whose messages all start
"blocked"), numbers and track names only, never transcript text. Silent otherwise;
the report is written every week.

An anomaly is a change in **how a track spends**, compared with the week before,
for a track live in both weeks with at least 100 M cost units in each (about a tenth
of a week's budget):

| Phase | Threshold |
|---|---|
| Tokens: build, fix (after the first review), review subagents, other subagents, boss | its share of the track's tokens moved 20 points |
| CI wait | its share of the track's worker time moved 20 points |
| Questions | per 100 M tokens, at least tripled and up by at least 1 |
| The routine failed | no tracked sessions; coverage on 0 messages; a lock not taken in two hours; an alert that could not be sent |

A track's share of the fleet is in the report and never speaks: it moves every week
because tracks start and end, so it says who was running.

### Where the thresholds come from

Five weekly windows ending 2026-10-07 to 2026-11-04 (about 10,000 sessions); eleven
track-week pairs were live in consecutive weeks, three of them with 100 M or more in
both. A first rule on the fleet share spoke in all four weeks that have a week before,
each time because a track started or ended (moves of 25 to 60 points), so it was
dropped. Among the three pairs above the floor the largest phase move was 0.08, 0.15
and 0.20; the 100 M floor removes the other eight, the tiny weeks (a track at a few
million tokens swings 55 to 85 points on a handful of messages). Replaying the final
rule over the five weeks, **it would have spoken once in four comparable weeks**,
about one track, on a fourfold rise in questions per 100 M tokens, with more than half
of that track's worker messages outside tracked activity, so the line itself says the
number is shaky. Two CI-wait moves of 0.20 and 0.21 sit on the threshold; whether
they should speak is to re-judge after eight weeks of history. With four comparable
weeks this threshold is a first estimate, not a calibration. The per-track replay is
kept outside the repository, because the transcripts name clients.

## Files, all outside the plugin

`~/.claude/routines/reports/boss-efficiency-<date>.{md,json}`,
`~/.claude/routines/state/boss-efficiency.json` (socket ties, eight weeks of
history, last eight weeks), `~/.claude/routines/logs/boss-efficiency.log`. The core refuses to
write inside the plugin. The scan takes `~/.claude/pm/.boss-efficiency-transcripts.lock`
(`flock`), shared with the gap scan of ticket 07, and runs at nice 19 and best-effort I/O class 2, priority 7 (not idle: an idle scan can starve on a busy disk and hit the 1 h cap, which loses the week). A boss whose dispatches no longer read "Boss dispatch from X, track Y" gets no socket tie (two such messages are the vote); its workers then show up as coverage lost, not as a wrong track.

## Test hooks

```bash
DRY_RUN=1 ~/.claude/routines/claude-boss/routines/boss-efficiency.sh --end 2026-11-04 --weeks 5
```

Prints the reports and what would be alerted, writes nothing (no directory, no log). A five-week scan of
about 10,000 sessions took 33 minutes at nice 19 on a loaded machine.

## Limits

Same as the audit: a review running beside a build does not lengthen the wall time;
tracks have no size, so a long week may be more work, not slowness; the cost unit
is a weighting, not a bill.
