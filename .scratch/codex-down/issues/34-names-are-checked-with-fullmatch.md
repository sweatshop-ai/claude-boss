# 34: Track and session names are checked with fullmatch, not `$`

**Blocked by:** none

**Status:** done (Amelie built it, PR 119)

Found by the Codex re-review of PR 96 (class b, real on main). `boss_store.valid_track` used
`TRACK_RE.match` with a pattern ending in `$`, and `$` matches before a final newline, so `prod\n` passed and
reached `--track` (`boss_review.py`), a pm file name and alert text. Reaching a file needs a `pm/<track>\n.md`
to exist, so impact today is low. `SID_RE` (session ids, which become file names under `pm/.pulse`,
`pm/consent` and the markers directory) had the same shape.

## What to build

`TRACK_RE` and `SID_RE` end in `\Z` instead of `$` and every caller uses `fullmatch`.

Every other regex validator in `skills/boss`, checked:

- `unask.KIND_RE`: already `fullmatch`. Fine.
- `tracker.ID_RE`, `tracker.KEY_RE`, `codex_blocker.ID_RE`, `codex_blocker.CHOICE_RE`: applied to a value
  taken out of one line of a tracker file (split on `\n`), so no newline can be in it. Not a trust boundary;
  left.
- `objective.STATUS_RE`, `BOX_RE`, `ITEM_RE`, `frontier.py` `FIELD`, `TICKET_FILE`, `ID`, `GH_SOURCE`: per-line
  parsers of files, or `GH_SOURCE` on a `gh:` source in a ticket file read line by line. Left.
- `boss_review.NAME`: already `fullmatch`, with a comment saying why.

- [x] Tests that fail on main: `valid_track` refuses `prod\n`, `\n`, `pro\nd`; `SID_RE`, `_marker`,
  `consent.token_path` and `state_path` refuse a session id with a trailing newline.
- [x] CHANGELOG.md.
