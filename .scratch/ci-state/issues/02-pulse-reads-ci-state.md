# 02: The boss pulse tells a worker waiting on CI from an idle one

**What to build:** `boss-pulse.py` counts a worker as idle when its session is idle, even
when its PR's CI run is queued or running; it may then ask the boss to give that worker
another ticket while its own PR is still in flight. For each idle worker, read its repo
and branch (its cwd: `git -C <cwd> rev-parse --abbrev-ref HEAD` and the origin remote) and
call `ci_state(repo, branch)`. A `queued` or `in_progress` worker is listed as
"WAITING ON CI: <name> (<branch>, queued 14 min, ETA ~56 min)". Whether it still gets a new
ticket is a choice for the grilling: it is free to work, but its PR may come back red.

`ci_state` never blocks, so the pulse's 5 s holds; the git reads are local.

**The session's cwd is not always the worktree** (Tarek, 2026-10-21): workers started in
a folder that holds worktrees (`~/Projects/render-doc-wt`) carry no branch in their
transcripts. The boss knows each worker's worktree from its dispatch, but today writes
it only into the tracker's hand-written Roster table (`| Name | Pane | Project | Branch |`),
whose cells vary by boss and are no contract. Write it where a program can read it: one
file per worker, `pm/.workers/<session-id>.json` = `{worktree, repo, branch, track}`,
written at dispatch and updated on `move`. agentview would read the same file, so the
render-doc workers get their CI wait on the page too.

Found by Codex review 2 of PR 21 as missing from ticket 01; split out on purpose.

**Blocked by:**
- 01: ci_state(repo, branch)

**Status:** needs-grilling

- [ ] Grilling settled whether a worker waiting on CI gets a new ticket
- [ ] `pm/.workers/<session-id>.json` written at dispatch, read by the pulse; format told to Tarek
- [ ] A pulse test with a stand-in roster and a cached ci_state: the worker is named as
      waiting on CI with its ETA
