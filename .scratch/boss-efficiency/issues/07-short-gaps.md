# 07: What happens in the gaps under two hours

**What to build:** nothing yet; a diagnosis. For 214 hours across 30 tracks nobody was active, in gaps under two hours, during the day. Sample them: what was the last event, what ended the gap, was a ticket ready.

**Why:** it is the largest unexplained share of duration, and nobody has looked.

**Blocked by:** None (can start immediately)

**Claimed by:** Otilia 2026-11-04 21:32

**Status:** done

- [x] A sample of at least 30 gaps, classified
- [x] Each class with its hours, and a ticket for any that a change could close

## Result

**Sample.** 50 of the 2,416 gaps under two hours (214.3 h) in 30 tracks: 42 drawn with probability proportional to length, 8 more from the under-5-minute gaps, which the first draw under-covered (1 of 42 against 4.6 expected). Hours are stratified by gap length. Each gap was read in the boss and worker transcripts: the last event, what ended it, and whether a ticket was ready with a worker free. Detail with names is outside the repo.

| Class | Gaps | Hours (of 214) | Plus or minus |
|---|---:|---:|---:|
| Hidden work: a worker of the track was active, not counted | 16 | 74 | 29 |
| Owner-held: a decision, command, review or reply | 14 | 56 | 26 |
| Track finished or closed, boss session still open | 5 | 23 | 19 |
| Waiting on CI or a long remote suite | 3 | 14 | 16 |
| Message latency under 5 minutes | 4 | 10 | 8 |
| Session changeover (worker restart, new boss reading the tracker) | 2 | 10 | 13 |
| Unknown | 2 | 9 | 13 |
| Codex out of usage | 1 | 5 | 10 |
| Restart refused, boss waiting for an idle notice | 1 | 5 | 9 |
| External party | 1 | 5 | 9 |
| Scheduled window | 1 | 5 | 9 |

**Artefact of the 19%.** Hidden work is the same fault as the 19% of worker messages outside tracked activity: 8 of its 16 gaps involve a session never scanned, 8 a session scanned but filed under another track or outside its dispatch windows. About a third of the short-gap hours (and 8% of the 962 h "nobody active") are not gaps.

**Ticket ready and worker free.** 1 gap in 50. Ready work parked behind a limit instead (worker cap of 3, the full-suite slot, laptop load): 3 gaps. In the other 46 the boss's reason is one no change here removes: workers busy, a dependency, the owner, CI, a window.

**Unknown** is 4% of the sample, under the quarter that would mean the work is unfinished.

**Tickets.** 17 (count workers by name, end a track at its last done ticket) and 18 (retry a refused restart). The owner-held class is the question wait of tickets 02 and 06; the CI class belongs to tickets 01, 13 and 16; the Codex class was a past outage. No ticket for the rest.

**Weight of the reading.** One reader, no second rater, no subagent. Firm: the hidden-work counts (records in a named session in the gap), gaps that ended on a human message, and tracks the boss itself called closed. Softer: the CI, scheduled, external and Codex classes rest on one to three gaps each, and the intervals cover sampling error only. The ticket said "during the day"; 5 of 50 gaps start between 00:00 and 07:00, and gaps starting before 07:00 hold 39 h of the 214 h.
