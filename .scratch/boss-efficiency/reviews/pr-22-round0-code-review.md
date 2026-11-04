# Ticket 22 branch, round 0: mattpocock-skills:code-review, head eae39a4

Two sub-agents, fresh contexts: Standards (CONTEXT.md and neighbouring code) and Spec (ticket 22).

## Standards

- Hard: CONTEXT.md says "boss file", avoid "marker"; two comments said marker. Fixed.
- Minor: the `turn_over(records)->` line broke the aligned column in transcript.py. Fixed.
- Smells (judgement calls):
  - The rule "`shell` is idle only with the turn over" was written twice in boss-lifecycle.sh. Fixed: the final gate calls `still_busy`.
  - `over2` read and never used. Fixed (`_`).
  - `first` renamed `first_pin`. Fixed.
  - `turn_over` repeats the record test of `pin`. Left: the two walks differ (reverse, different skips); a shared predicate would be Speculative Generality for two callers.
  - The five-field `--state` row is read in three places. Left: it is the existing tab protocol, one field added.
  - Divergent Change (four fixes in one commit). Left: one ticket; the CHANGELOG lists them separately.
  - The `dialog_screen` change is outside the ticket; kept, named in the PR (it removed an intermittent failure of a new test under load).

## Spec

- Items 1 to 4 red before: the non-numeric `--wait-idle` and `--wait-idle --force` tests were already green; they are regression pins. Said in the PR.
- Nothing ran `--state` on a transcript on disk. Added `test_state_reads_the_turn_over_field_from_the_transcript_on_disk`.
- Not asked for, now named in the PR: the leftover-work message reworded ("will be stopped"); the retry-interval floor changed existing tests (0.1 to 1, one busy row fewer); `stamp-self` reads the fleet once per invocation; a boss that has not registered is no longer self-stamped.
- Item 5, "without saying so": the restart says it before typing and lists each job, but does not pause. Decision kept: the worker's report means its handoff is on disk, SKILL.md tells the boss not to restart a worker whose job must outlive it. Said in the PR.
- Items 1, 2, 3, 6 traced correct by the agent.
