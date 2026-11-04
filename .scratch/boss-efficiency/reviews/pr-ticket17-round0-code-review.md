# Ticket 17: round 0, mattpocock-skills:code-review (Otilia)

Diff `origin/main...HEAD` at e90ae83 and 47adda2, code and synthetic fixtures only. No repo coding standard is documented; the smell baseline was applied as judgement calls. Two fresh sub-agents.

## Standards: no hard violation
- Duplicated `min(end, index.cut.get(track, end))` in `measure_track` and `coverage`. **Fixed**: `Index.clip_end`.
- Vacuous test assertions (`assertGreaterEqual(..., 0)`, `- 0`, `delta=130`). **Fixed**.
- Parallel tuple lists in the scan result, long `Index.__init__`, one-letter names, test helper with many parameters, `**kw` passthrough. **Left**: matches the existing `xmsgs` style; judgement calls.

## Spec
- A track with a done commit but never marked met gets no cut. **Kept on purpose**: without the mark the track is not known to be finished, and cutting an open track at its last done ticket would drop live work. Stated in `routines/boss-efficiency.md`.
- "Done" commit is any `git commit` command containing the word done, read from the transcript. **Known limit**, stated in the doc.
- A worker is counted from the start of the boss's window, not from the message. **Intended**: "count its records in the track's window".
- A session with no recorded name is skipped. **Intended**; the rerun reports how many sessions have a name.
- `days` stays the window's. **Commented in the code.**
