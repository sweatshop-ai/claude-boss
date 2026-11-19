# 01: The pulse records why it stays silent

**What to build:** on every Stop of a boss session the pulse writes one line to a per-session
log beside its pulse state: the time, the track, which gate held it back (not a boss, no goal,
objective closed, background tasks, rate gate, open question, nothing to say) or what it decided,
with the number of idle workers and of unassigned items when known. The log rotates at 1 MB.
`boss-pulse why <track>` summarises the last day per gate, so a silence like action-list
(285 Stops, zero pulses, 2026-10-28) can be explained afterwards. No gate changes behaviour in
this ticket. Update the pulse section of the boss SKILL.md.

**Blocked by:** None (can start immediately)

**Claimed by:** Nilufar 2026-11-19 17:46

**Status:** done

- [x] Each early return in the Stop hook writes exactly one log line naming its gate (evidence: test_silence_log.py::Lines (objective-closed, no-goal, open-question, background-tasks, rate-gate, nothing-to-say lines) 105 passed; PR 161 pytest success)
- [x] A pulse that fires writes its decision (actions, idle count) to the same log (evidence: Lines::test_a_pulse_that_fires_writes_its_decision (actions=ask, idle=0))
- [x] The log rotates at 1 MB; a write failure never fails the hook (evidence: Rotation::test_the_log_rotates_at_one_megabyte, Lines::test_an_unwritable_log_never_fails_the_hook)
- [x] `boss-pulse why <track>` prints counts per gate and the last firing time (evidence: Why::test_why_counts_per_gate_and_names_the_last_firing runs `boss-pulse.py why demo`)
- [x] Tests cover one gate, a firing pulse and rotation (evidence: test_silence_log.py: gate, firing pulse, rotation, why, reap)
