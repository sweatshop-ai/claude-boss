# The track store: one module owns pm/

Plan settled with the owner on 2026-10-26/27 (architecture review, then a grilling
in two rounds, Q1–Q13, every recommendation accepted). The tickets in `issues/`
cut it into six slices. Domain terms are in `CONTEXT.md` (**Track store**,
**Boss file**, **Tracker**, **Objective status**).

## Why

The `pm/` layout (the config directory, the boss files, `.pulse/` state,
`<track>.md`, `<track>.goal.md`) is worked out in nine places, and they already
disagree. With `CLAUDE_CONFIG_DIR` set to an empty string, `boss_store` and
`registry` resolve to `~/.claude`, while `boss-guard`, `boss-reap`,
`boss-compact` and the ladder core resolve to `.` (run and observed 2026-10-26
at 9d7ab1c). The guard then looks for boss files under `./pm` and never fires.

## Decisions

1. **What the store owns (Q1).** Paths, plus reading and writing the raw files:
   objective text, tracker text, per-session state JSON with safe writes. Not the
   formats: `objective.py` and `tracker.py` keep what the text means.
2. **Where (Q2).** `skills/boss/boss_store.py` grows into the track store and
   keeps its name. CONTEXT.md carries the term.
3. **The config-dir rule (Q3).** An empty `CLAUDE_CONFIG_DIR` is unset and means
   `~/.claude`. `registry.config_dir` calls the store.
4. **Bash (Q4).** `boss-goal` and `boss-tracker` keep their bash path code. A
   test keeps their track regex, paths and frontier cache key equal to the
   store's, on the pattern of `test_policy.py`.
5. **The ladder's overrides (Q5).** `BOSS_LADDER_PM` and `BOSS_LADDER_STATE`
   stay; only the default comes from the store. The ladder's own state stays in
   `routines/state/boss-ladder.json`.
6. **When paths resolve (Q6).** At call time, with an optional `cfg=` for tests.
   Hooks drop their `CFG`, `PM`, `MARKERS`, `STATE` constants.
7. **Naming (Q7).** The file under `pm/.boss-sessions/<sid>` is the **boss
   file**; "marker" stays the ladder's token. The `boss-marker` command keeps its
   name.
8. **Interface (Q8, amended by Q13).** Plain functions with `cfg=None`, no
   object. Existing: `config_dir`, `is_boss`, `track_of`, `register`,
   `valid_track`. New: `objective_path`, `tracker_path`, `read_objective`,
   `read_tracker` (text or `None`), `open_tracks()` yielding
   `(track, tracker_path, objective_text_or_None, reason)` with only "no goal
   file" and "goal unreadable" (the ladder keeps `is_open()` and "goal not OPEN",
   so the store never imports `objective.py`), `state_path(sid, kind)`,
   `update_state(sid, kind, fn)` under `flock`.
9. **Reap (Q9).** The store yields `(path, sid)` candidates from the boss-file
   directory and `.pulse/`; a name without a UUID is never a candidate. Reap
   keeps the live set, the 30-minute grace and dry run.
10. **Frontier cache (Q10).** `frontier_cache(track, source)` moves into the
    store, key included. The bash `sha1sum` copy is held by the test in 4 until a
    later change (architecture candidate 2) removes it.
11. **Tests (Q11).** First a failing test that runs guard, pulse, compact and
    reap with `CLAUDE_CONFIG_DIR=""` and `HOME=<tmp>`. Store tests against a tmp
    `cfg`. Existing hook tests stay. Locally only the touched test files; CI on
    t-compute runs the suite.
12. **Delivery (Q12).** Branch `feat/track-store`, release 0.17.0 with a
    CHANGELOG entry, code review and `/codex-review`, a PR to `main` that the
    owner merges.

## Out of scope

The other three candidates of the review (the ticket graph owning its GitHub
cache, the retire protocol behind the fleet's tmux seam, one answer to which
rung is due) are separate work. Don't start them here.
