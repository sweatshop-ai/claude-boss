# 18: A refused restart is retried on a timer, not waited on

**What to build:** diagnose, then change the boss's restart step. In one sampled gap the boss asked a worker to end its turn so it could restart it fresh with `--require-idle`, subscribed to the worker's idle notice, and waited. The worker's turn ended within seconds. No idle notice arrived for 92 minutes, the boss did nothing until an unrelated notice woke it, and the pane still read busy when it tried again. A ready job, the full suite in a fresh session, sat the whole time. In another gap the boss looped the same refusal and the restart went through in 16 seconds. Find out why the pane read busy and why the notice did not come, and make the restart step retry after the worker's last turn at a fixed interval (and say so on the tracker) instead of waiting on a notice that can be lost.

**Why:** ticket 07's sample: 1 gap of 50, 92 minutes, an estimated 4.5 h of the 214 h of short gaps (plus or minus 8.7), and the only gap where a ticket was ready and a worker was free. One case: the first box is to find out how often it happens.

**Blocked by:** None (can start immediately)

**Claimed by:**

**Claimed by:** Otilia 2026-11-04 22:23

**Status:** done

- [x] How often a restart was refused as busy and not retried within 10 minutes, counted over the boss transcripts of the last five weeks under the transcript lock, with the count of cases where no idle notice followed
- [x] The restart step retries on a timer, with a test that a refused restart is retried once the worker's last turn has ended

## Result (Otilia, 2026-11-04; PR 50)

- Count, boss transcripts since 2026-09-30 (60 files, under the lock): 237 refusals as not idle in 14 sessions (193 busy, 41 shell, 3 waiting). 49 not retried within 10 minutes (a later restart/retire command naming the pane); 32 of those with no restart or retire command at all; 17 of the 32 with no idle-notice text within 90 minutes (text heuristic).
- Cause of the false "a turn started": with the exit dialog up the status is `waiting`, the check wanted `idle`. Reproduced in the stub harness and read live in an isolated tmux server. Separate finding: `shell` is read mid-turn too.
- Box 2 stays open: why the sampled gap's pane read busy and why no notice came is not shown. 41 of the 237 refusals read `shell`; the link to the missing notice is not shown.
- Retry: `--wait-idle <seconds>` (PR 50).
- Follow-ups: tell "turn over, background shell left" from "turn in flight" for `shell`; `self_register` stamps the calling pane as a boss on every invocation (a worker that runs the script becomes a boss pane).

PR 50 merged fa2062c; box 2 goes to the next worker: reproduce a worker that ends its turn with a background shell, with an idle subscription, and read whether the notice fires.


## Box 2: reproduction (Otilia, Anton's request, 2026-11-04 22:25-22:38)

Claude Code 2.1.311, sonnet probe in a throwaway tmux server, real config dir (the peer files are read from there), subscribed with `notify_when_idle`, status read from the probe's `~/.claude/sessions/<pid>.json` every 0.5 s. Probe and server killed; all 7 one-shot subscriptions consumed.

| State when the turn ended | Status read afterwards | Notice | After |
|---|---|---|---|
| (a) nothing running | `idle` 9 s after the request | yes | at the end of the subscriber's own turn, not before |
| (b) background shell (`sleep 170`) | `shell` for 2m48s, then `busy` 9 s (the shell's completion woke a turn), then `idle` | yes, at the turn end (the final text), with the shell still running | same |
| (c) Monitor armed | `shell` | yes, at the turn end | same |
| (d) background subagent (about 2m10s) | `busy` the whole time (the screen says "Waiting for 1 background agent to finish"); `idle` only when the agent finished and its report was handled, 2m24s after the final text | only then, 2m24s late | at the end of the subscriber's turn |
| (e) already idle at subscribe (pure subscription, no message) | `idle` | yes, at once, reporting the last finished turn | at the end of the subscriber's turn |

Not tested: a scheduled wake (ScheduleWakeup/Cron); a `waiting` pane.

**Cause, shown.** (1) The pane reads `busy` after the worker's last words while a background subagent runs: the turn does not end until the agent reports, so the idle notice is not sent until then (here 2m24s, as long as the agent runs). The final text is not the end of the turn. (2) A background shell or Monitor reads `shell` and does not delay the notice. (3) A notice is not lost: it was delivered in every state, but only at a turn boundary of the subscriber. A boss that is inside a long turn sees it late, and it reports the time the worker's turn ended, so it can describe a turn that ended long before the notice is read (the 22:16 datum). (4) Subscribing to an idle session fires at once: state (e) does not lose a notice.

**What this does not show.** Which state the sampled worker was in during its 92 minutes. A background subagent (or any long task the worker waited on) fits both readings, busy pane and late notice; no transcript was read to confirm it, and a scheduled wake was not tried. The notice code is in Claude Code, not in this repo. The retry on a timer (`--wait-idle`, PR 50) does not depend on any of it: it reads the status itself.

### The sampled gap read against the table (Otilia, 2026-11-04; worker and boss transcripts, structure only: record types, tool names, durations)

Times are seconds from the boss's first refused restart (T).

- T+0: restart refused as busy. The worker's last turn had ended 5 s earlier (its stop hooks had finished).
- T+3: the boss subscribed (`notify_when_idle`) with a message; the worker took a turn that ended at T+30.
- T+27: second restart refused as busy, in the same second the worker's turn ended (T+30).
- T+33: the boss subscribed again with a message; the worker took a turn that ended at T+41.
- The boss's turn ended at T+38 and it slept 92 minutes. It was not in a long turn. Its transcript holds no idle notice between T+38 and T+92 min; the first notice it reads then is an expiry for another session.
- Background work in the worker: none running at its last words. Its last background shell and its last Monitor had completed 62 s and 75 s before them; nothing was started in the four hours before.

**It fits none of states (a) to (e).** (d) needs a background agent, there was none. (b) and (c) read `shell` and notify at the turn end. (a) and (e) notify at once or at the subscriber's turn end: both subscriptions were followed by a worker turn end and the boss's own turn end, and neither notice reached it, although all seven did in the probe. The first `busy` read, 5 s after the worker's stop hooks finished, is also not explained by any probe state.

**Missing.** (1) Why a status read 5 s after a finished turn says `busy`: the probe shows `idle` within the second, so a lag in the status file or a queued wake is a candidate, not shown. (2) Why two subscriptions made 3 s and 33 s before a worker turn end gave no notice: a subscription made while the worker was between turns and with a message in the same call is the closest probe state ((a), (b), (c), (d) all did that and notified); what differs is the worker's two back-to-back turns (T+3, T+33) and the earlier restart attempts. A probe with two such back-to-back messages is the next step. Box 2 stays open.

### Back-to-back probe (Otilia, 2026-11-04 22:47-22:55): not reproduced

Same setup as the table above (2.1.311, sonnet probe, status logged every 0.5 s). Five rounds, each mirroring the sampled gap: a message plus `notify_when_idle` to the probe, a turn of 33 to 40 s (three `sleep 6` calls), a second message plus subscription sent in the second after that turn's idle line (round 2: 70 s after, a looser copy), a turn of 10 to 17 s, and my own turn ended about 3 s after the second send, with nothing else to do, so the notices landed on a quiet session.

- Notices: 10 subscriptions, 10 notices, each carrying the right turn. 0 missed. Each wake delivered one notice; the second came at the next turn end of mine, so back-to-back subscriptions arrive one per boundary, not lost.
- Status: busy spans of 33.0 to 40.5 s and 10.2 to 16.8 s, matching the turn lengths the probe's screen reported (e.g. "33s" against a 33.5 s span); every turn ended on an `idle` line with no `busy` tail afterwards. The 5 s busy read after a finished turn did not show.

**Answers neither question.** The miss and the early busy read were not reproduced in 10 subscriptions, so no cause is shown. What the probe did not copy: the worker's own Stop hooks and background-task completions seconds before the turn ends, a boss that had just run `boss-lifecycle.sh` (the refused restarts) before subscribing, and the worker's session being a long one (about 6 h old, many tasks). Box 2 stays unticked and Status stays in-progress; how the ticket closes is the boss's decision.

## How this ticket closed (Anton, 2026-11-04)

The cause of the sampled gap's busy reading and missing notice is NOT shown. Two probes (7 and 10 subscriptions) did not reproduce it, and the notice code is in Claude Code, not in this repo. A third probe would cost more than the gap: the retry (`--wait-idle`, PR 50) reads the status itself and does not depend on the notice, and it worked on live panes tonight. Shown along the way: a background subagent holds a pane busy and delays its notice. The open question moved to ticket 23, which waits on a recurrence. It is not answered.
