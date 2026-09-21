# boss-ladder — the escalation clock that runs without a boss turn

**Brain.** Body `boss-ladder.sh` + `boss_ladder_core.py`, pulse
`boss-ladder.timer` (every 5 min). Built 2026-09-18 (Suraya, #79, dispatched by
Lucas on track `acme-groups`).

## The failure this exists to prevent

The P12 ladder (`${CLAUDE_PLUGIN_ROOT}/skills/boss/references/escalation.md`) posts rungs at
T+5, T+15, T+30 and every 30 after. Its timer is a detached `sleep` that
re-invokes the boss session, so **a rung only fires when the boss wakes**. Once
the Jev hook (`~/.claude/plans/2026-09-18-boss-jev-hook.md`) absorbs no-action
events, the boss wakes less often and can sleep straight through a rung. A
ladder nobody climbs is the same as no ladder, and the blocker it was raised for
sits there while workers idle behind it.

This reads the marker left on a tracker's `## Open blockers` line and posts the
rung that is due. No boss, no session, no LLM: the decision is arithmetic on two
timestamps.

## The marker

Agreed with Berit 2026-09-18 (her hook writes it, this reads it). Appended to
the blocker line:

    - boss-jev a1b2c3d4: Ottilie (20:0.2) blocked on OWNER: <first sentence> — T+0 2026-09-18 10:53 [ladder id=a1b2c3d4 t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 pane=20:0.2 ask="put /root/door-e2e-u2.txt on lab-0"]

| field | | |
|---|---|---|
| `id` | required | `[a-z0-9]{4,16}`, the hook's `id8`. **The key.** Survives any rewording of the line, and keys the state journal. |
| `t0` | required | ISO 8601 **with offset**. When the blocker was raised. Never rewritten by anyone. |
| `last` | required | The rung already posted. Born `0` — the hook posts rung 0 itself. |
| `next` | required | ISO 8601 with offset. **Authoritative gate: nothing posts before `now >= next`.** |
| `ask` | required | Double-quoted, no `"` inside. The one action. This is the Slack text. |
| `pane` | optional | `sess:win.pane`. |
| `cost` | optional | Quoted. What is idle behind it. |
| `cleared` | optional | ISO 8601. Present → the line is skipped forever. |

**`next` is how you defer a rung by hand.** Push it forward and the ladder holds
without losing `t0`, which is what the tracker already does in words ("Slack
rungs held while the owner is at the keyboard"). The rung label stays the elapsed
minutes, so a blocker that has held two hours still announces itself as two
hours when the hold ends — more urgent, not less, as the reference says.

**Clearing is not this routine's job.** It never posts `boss-alert clear`.
Whoever sets `cleared=` posts it, because only they know it actually cleared.

**A marker that vanishes from the tracker counts as cleared** (Lucas,
2026-09-18): the boss rewriting a blocker line wholesale is how a clear usually
looks in practice — that is exactly what happened to the u2 marker at 14:57. The
journal entry is dropped, the fact is logged once, and nothing is ever posted
about it. Only for tracks actually walked this run: a goal going closed hides
its markers, and that is not a clear.

**A line without `[ladder` is ignored**, and `boss-pulse.py`'s `due_rungs` was
changed the other way on 2026-09-18 to ignore lines that *have* one — otherwise
the boss and this timer both post the same rung.

## What it does, every 5 minutes

1. Every `~/.claude/pm/<track>.md` whose `<track>.goal.md` says `_Status: OPEN_`.
   No goal file, or a goal that is not OPEN → skipped.
2. `flock` on `~/.claude/pm/.<track>.md.lock` — a sibling, not the tracker's own
   inode, because both writers replace that inode by rename. Berit's hook takes
   the same lock.
3. **Only the `## Open blockers` section**, like `boss-pulse.py`'s `due_rungs`.
   A marker means nothing anywhere else, and reading the whole file makes prose
   that *documents* the format — a roster row, a state note — parse as a
   malformed marker. That happened at 14:59 on 2026-09-18 and put the routine
   into exit 1 on every tick.
4. For each marker: `elapsed = now - t0`; the rung is 5 → 15 → 30 → 60 → 120 →
   then every 120, **stopping for good at 24 h** since `t0` with one last line
   saying so (the staleness guard `due_rungs` already had). Posts the highest
   rung that is due and greater than `last`, **one per run** — with
   `Persistent=true` a laptop waking after three hours would otherwise fire
   several rungs at once. It catches up one rung per tick instead.
5. Posts through `${CLAUDE_PLUGIN_ROOT}/skills/boss/bin/boss-alert <rung> "<text>"`, then
   rewrites `last=` and `next=` in place. Every other byte of the line is left
   alone.
6. Re-stats the tracker before the rename. If it changed under us (the boss's
   Edit tool takes no lock), re-read and redo, up to 3 times.

Silent unless a rung is due. The log is `logs/boss-ladder.log`.

## The one judgement call: `ask="(boss names it)"`

The hook writes that placeholder and the boss fills it in seconds later. Posting
the placeholder at T+5 would tell the owner nothing, and `escalation.md` is explicit
that an alert without one named action is what turns the channel into wallpaper.
So the rungs **hold** while `ask` is still the placeholder. But a blocker nobody
has defined after 30 minutes is itself worth knowing, so at T+30 it says exactly
that, **once, ever**, and then goes quiet. Fill `ask` in and the normal ladder
resumes from wherever the elapsed time has reached.

## Not posting the same rung twice

The state journal `state/boss-ladder.json` records `last_posted` per
`<track>/<id>` **before** the Slack call. If the process dies between the post
and the file write, the next run finds a journal ahead of the file, **adopts**
the rung and fixes the file without re-posting. A failed post rolls the journal
back, so a rung that never went out is not counted as sent. The bias is
deliberate: a repeated alert trains the owner to ignore the channel, a rung 30
minutes late does not.

## Tests

```bash
python3 ~/.claude/routines/boss_ladder_core.py --selftest   # 107 checks, posts nothing
DRY_RUN=1 ~/.claude/routines/boss-ladder.sh                 # real trackers, writes nothing
```

The selftest builds fixture trackers in a temp dir with a fake `boss-alert` and
covers: the ladder arithmetic including the 24 h stop; an unreadable marker
reported once and then forgotten when it goes; the scoping to
`## Open blockers`, with prose documenting the format left alone; a marker that
vanishes from the tracker; parsing, including `]` inside a quoted value;
every malformed shape (missing field, bad id, naive timestamp, unknown field,
unterminated quote, duplicate key); a rewrite that leaves `ask`/`t0`/`pane`
untouched; due, held-by-hand, cleared and non-OPEN tracks; one rung per run
after a long sleep; the placeholder hold, its single alert, and the resume; a
failed post leaving the marker alone; a foreign write landing during the Slack
call; and `DRY_RUN` writing and posting nothing.

`--now <ISO>` drives it at any instant, which is how the fixtures work.

## An unreadable marker

A marker that does not parse is **never guessed at**. It is skipped, and it is
reported to `#claude-ops` once — naming the file, the line and the reason, and
saying plainly that nothing is escalating from that line — then remembered in
the journal so it never says it again. **The run still exits 0** (Lucas,
2026-09-18): a unit left red on every tick hides the next failure, which is the
opposite of what a watchdog is for.

The journal key is a hash of the marker fragment, not the `id` — the `id` is
often the thing that is wrong. That key survives the line moving within the
section, and changes when the breakage changes, so a *different* fault on the
same line is its own report. When the bad line goes away the entry is dropped,
so the same breakage returning later is news again rather than being swallowed.

## Escalation and blast radius

It reads `~/.claude/pm` and writes back only the `last=`/`next=` inside a marker
it parsed. It touches no device, no remote host and no git tree. The only
outbound action is `boss-alert`, which is one Slack post to `#claude-ops`.
Wrong-way failure is a missing rung, not a wrong one: everything it cannot parse
is skipped, reported once and never guessed at. It exits 0 in every case it
handles, so a red unit means something it did not anticipate.
