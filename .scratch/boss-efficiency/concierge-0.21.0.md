# Concierge 0.21.0: one track's evidence for ticket 05

What this is: the first measured evidence on how the 0.21.0 concierge behaved, from one track (boss-efficiency), written for ticket 05. First evidence only: no verdict. Ticket 05 waits for three finished tracks run with a concierge, and this track is not finished.

The first five sections below were measured on the evening of 2026-11-04 and stop at 23:23 CET (last record of the boss transcript, 22:23Z); the track started 20:46 CET, so 2 h 37 min are covered. The sections "Measured over the whole track so far", "What the owner said about the concierge" and "What is not measured" were added on 2026-11-05 at about 19:00 CET. Times are CET. Sources: the boss and concierge transcripts, read by file path under the transcripts flock at `nice`/`ionice`, the boss's tracker, and `routines/boss_efficiency_core.py`'s own count.

## Questions

Three questions sent to the concierge, three answered, none unanswered.

| Q | Sent | Shown to owner | Answer reached boss | Send to answer | On screen to answer |
|---|---|---|---|---|---|
| q1 | 20:52:48 | 20:52:57 | 20:54:34 | 1 min 46 s | 1 min 32 s |
| q2 | 21:28:11 | 21:28:21 | 21:44:02 | 15 min 51 s | 15 min 34 s |
| q3 | 21:32:27 | 21:44:06 | 21:45:20 | 12 min 53 s | 1 min 14 s |

q3 was queued behind q2 for 11 min 39 s: the concierge shows one question at a time. Its answer came 78 s after q2's closed.

## Did the boss's turn stop, and what it handled while a question was open

Counts are from the boss transcript between send and answer. Worker messages and idle notices are inbound records with the concierge's own answers excluded, counted once each. `end_turn` is the number of assistant records that ended a turn inside the window (a turn can span several records). Longest gap is the longest stretch without any assistant record inside the window.

| Q | Worker messages | Idle notices | `end_turn` records | Assistant records | Gaps over 60 s |
|---|---|---|---|---|---|
| q1 | 0 | 0 | 4 | 8 | none |
| q2 | 8 | 3 | 11 | 56 | 77, 83, 115, 204 s |
| q3 | 7 | 2 | 9 | 41 | 83, 115, 204 s (inside q2's window) |

The boss kept dispatching and answering workers while q2 and q3 were open: 8 worker messages, 3 idle notices, 4 dispatches and 56 assistant records in q2's window. No question was asked by the boss itself with `AskUserQuestion`: 0 calls in the boss transcript, 3 in the concierge's. The turn did end (`end_turn`) in every window; each end was the boss having nothing left to do, not a wait on the question. Not confirmed: whether any worker was blocked on a ticket the boss would have released had it known the answer earlier.

## Cost of the concierge against the boss

Unique assistant messages, priced with `transcript.py`'s weights (input 1, cache write 1.25, cache read 0.10, output 5).

| | Turns | Output tokens | Cache read | Cache write | Weighted | Context at end |
|---|---|---|---|---|---|---|
| Concierge, whole life (20:47 to 21:45) | 8 | 2,993 | 428,659 | 68,628 | 143,634 | 68,630 |
| Boss, same window (20:52:48 to 21:45:20) | 100 | 84,221 | 24,804,964 | 180,582 | 3,127,553 | 347,300 |
| Boss, to 23:23 | 241 | 200,847 | 54,882,018 | 603,596 | 7,247,476 | 213,399 (max 413,945) |

The concierge's weighted cost is 4.6% of the boss's over the same window and 2.0% of the boss's to 23:23. The boss compacted once, at 22:09 CET. The concierge's transcript ends at 21:45 (idle after q3); it has had no turn since.

## Ticket 05's measures

- Share of duration with no worker active and a question open (audit: 21%): cannot be read from these records. Question-open time was 1 min 46 s + 15 min 51 s + the q3 overlap, a union of 17 min 37 s, which is 11% of 157 min. Worker activity needs the workers' own transcripts, which were not read. Workers were dispatched at 20:50 and sent messages in both long windows, so a "no worker active" share is smaller than 11%; for q1 not confirmed.
- Questions per active day (audit: 18): 3, on one day (2026-11-04), in 2 h 37 min so far.

## Measured over the whole track so far

From `boss_efficiency_core.py`'s own count (`measure_track`), window 2026-11-04 19:00 to 2026-11-05 about 18:50, on the 63 transcripts of the track's repos' project directories and the concierge directory modified since 19:00 on 11-04 (48 worker sessions, the boss, three concierge sessions: one is this track's, two belong to other tracks and are not counted here). Tokens are the routine's weighted units (the weights of `transcript.py`).

| Measure | This track | Audit (30 tracks) |
|---|---|---|
| Questions to the owner (`AskUserQuestion` calls) | 13: 6 by the boss in its own turns, 7 in the track's concierge session | 18 per active day |
| Questions per day of the window | 13.1 (window 0.99 day) | 18 |
| Share of the track's duration with a question open and no worker active | 35.5% (28,190 s of 79,448 s) | 21% |
| Share with nobody working and no question open | 22.4% (17,782 s) | not in the audit |
| Concierge session, this track, weighted tokens | 660,493 over 20 messages: 0.8% of the track's 82,569,198, and 3.1% of the boss's 21,458,256 | not in the audit |

The 35.5% includes the nights: the track ran for 22 h of wall time and questions stayed open while the owner was away, so it is not comparable with the audit's 21% without that correction. The 7 concierge questions are the `AskUserQuestion` calls of the session; 3 of them came in as `ASK` messages from the boss (q1 to q3 above), and the other 4 are not identified by the count. The boss's own 6 calls are all on 2026-11-05, between 11:29 and 18:36, after the evening covered above (which reads 0 up to 23:23).

## What the owner said about the concierge

Words as the tracker records them, in English; this is the owner on two other occasions, not a measure.

- 2026-11-05 about 17:35, first contact with a concierge on another track, reported by that track's boss: the concierge is "only a Sonnet" and asks questions "clearly not very intelligent"; why does a worker ask and not the boss. The tracker adds that the card did not say whose question it was, that four questions came in one call against the brief's "one question", that all four were answered with the recommended option and no text, and that which part he objected to is not known.
- 2026-11-05 18:3x, same track's second report: again the same complaint, "is it resolved or not". Not resolved at that point: PR 73 only labels the questions and was not installed.
- 2026-11-05 18:3x, answer in the boss's own turn on this track: he wants to experiment, so the concierge stays on (not off), and he did not know it was new. He asks for "[boss]" after a boss's name and "[concierge]" after a concierge's, and asks why not Haiku, since the concierge only relays. Ticket 05 stays.

What followed from it, as the tracker has it: ticket 39 (PR 73, merged) makes a question name the boss that wrote it and holds one question per `ASK`; ticket 40 (labels) and ticket 41 (Haiku against Sonnet as concierge) are open. No measured reason for Sonnet exists: the code comment says only "needs no Opus".

## What is not measured

- No verdict: keep, change or remove is ticket 05's second box, and it needs three finished tracks.
- Whether any worker was blocked on a ticket the boss would have released had it known an answer earlier: not read from these records.
- Question-open time with the owner away against with the owner present: the count does not tell them apart.
- Cost of the concierge on the other two tracks' sessions: counted in the files, not attributed to this track.
- Codex-side tokens (reviews run by Codex are on OpenAI's side) and any session whose directory was not scanned: not in the numbers.

## Watchdog on the concierge pane

- False alarm: PR 48 round 2 found false prompt alerts on the concierge pane; round 3 merged with two misses only on panes at 29 columns or less. Tickets 11 and 15. Source: the boss tracker, not re-read from alert logs.
- Pane width at the time of q2: 95 columns; the tracker notes live panes at 74 and 31 columns later in the evening.
- A false alarm or miss on the concierge pane during q1 to q3 themselves: not confirmed, no alert log read.

## What did not work

- The answer address: the boss shows as `boss-plugin-28` in the concierge's inbox and `ListAgents`, while the SessionStart hook names it Anton. Delivery worked for all three (tracker Evidence).
- The pulse says "spawn N more" from the count it knows (12), not the track's cap, and asks the boss to raise blockers the brief already holds (tracker Evidence).
- The skill's `bin/` path: `skills/boss/bin/` holds `boss-alert`, `boss-goal`, `boss-run`, `boss-start`, `boss-tracker`, `boss-version-gap`; `boss-lifecycle.sh` is in `skills/boss/`, so the `bin/` path in SKILL.md misses it (checked just now). `boss-tracker append` reading stdin and hanging when given an argument: tracker Evidence, not re-run.
- A track's restart defects: `restart` refused idle panes (fixed in PR 50, worked live at 22:20 CET); a restart that found "another live session holds" a name and brought the pane back under a new one (archive, roster 21:13); `restart --require-idle` stopping a job that waits on a Monitor (PR 52 sent back, open).
- q3 waited 11 min 39 s behind q2 for the screen (table above).
