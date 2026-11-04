# PR 52, round 1: Opus fallback (fresh agent), head d771a25. Codex follow-up owed (back at 23:38)

Verdict: GO. No blockers. The agent ran only `bash -n`, awk probes and read-only scans of the 60 newest transcripts.

VERIFIED (read or run):
- boss-lifecycle.sh:340-343 `still_busy`: busy and waiting always busy; `shell` busy unless the fifth field is exactly `1`; a missing, `-` or empty field refuses.
- :385 gate `idle||shell && ! still_busy || die` correct under `set -e`.
- :362-368 wait loop: a failed read ends the loop and dies "not idle", nothing typed; `10#` fixes 08/09.
- :78-84 floor: the regex refuses `1e3`, `.5`, `1.`; `007` passes; `0` and `0.01` become 1.
- :395 `| grep -q` replaced by a here-string.
- transcript.py:110-133 `turn_over` against real records: after a `turn_duration` the next user/assistant record was always `user` (639 of 639), 488 preceded by `enqueue`; records seen idle (away_summary, compact_boundary, dequeue, ai-title, ...) are skipped; a truncated tail fails safe.
- boss-panes.py:180-190 `stamp-self`: no session or a worker is not stamped.

Minor, not blocking:
1. Two sessions in one pane: fleet keeps the oldest, so `stamp-self` judges that one (older worker plus newer boss leaves the boss unstamped; fails safe; `--state` already worked so). VERIFIED.
2. `stamp-self` never removes a stamp; worker panes stamped by the old script keep it until the pane is reused. VERIFIED.
3. Gap race: a shell that finishes between the status read and `/exit` can exit a session whose woken turn has no tool call yet; only the reaction to the shell's end is lost. Existing race, likelier here. VERIFIED.
4. 32 of 60 recent transcripts end on `end_turn` with no `turn_duration`; such a worker in `shell` is refused, not typed at. NOT FOUND: whether this happens to live workers.
