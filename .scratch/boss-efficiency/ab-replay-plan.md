# Ticket 08: plan for the A/B replay of `overview-build`, boss against one long session

Prepared by Kaveh on 2026-11-05. Nothing has been run and nothing created on GitHub. The facts below were read from `/home/tiroir/Projects/agentview` (read-only: `git log`, `git show`, `git grep`, `gh api` reads) and from this repo.

**Two findings change the ticket as the owner described it.** Both are in section 2: agentview has **no CI at all and no `main`**, and the original run made **no pull requests**. "Stop at merged PRs with CI green" needs a setup that does not exist yet.

## 1. Starting commit, and the 22 tickets

- **Starting commit: `a5674b414afb3e5284d30a6a1588aff967b20aa9`** (2026-10-18 23:52 CEST, "Overview build: 13 tickets from the build spec; routines leave the page"). Its parent is `1e36e8fc9bd02c8fb98d62966dec674c8ace66c2`. How I know: it is the commit that adds the 13 ticket files and the build spec's last line, and the boss brief (`.scratch/overview-build/boss-brief.md`, written 23:58) lists exactly tickets 01–13 as the frontier. Ticket 01 was claimed at 2026-10-19 00:03.
- **Where the tickets are.** At `a5674b4`: tickets 01–13 in `.scratch/overview-build/issues/`. Tickets 14–22 did not exist yet; they were written during the run (each first appears in a later commit, e.g. 14 in `8dc4e58`, 20–22 around 2026-10-21). Their final text is at `origin/dev` (22 files; 19 is `needs-triage`, 22 is "done, one box open").
- **Do the tickets leak the original run? Yes, all of them.** Every final ticket file carries a `Claimed by:` line, `Status: done`, ticked boxes, and an `Evidence` or `Gate` section with worker names, commit hashes, hunt verdicts, review counts, test counts and "merged to origin/dev as …". Tickets 14–22 are also *consequences* of the original run (bugs and gaps it found), so even their "What to build" text carries knowledge the replay would not have at the start.
- **What a clean replay needs** (a script, not judgement; I would write it when asked):
  - Tickets 01–13: take the files from `a5674b4` as they are. They are clean.
  - Tickets 14–22: keep the title, `What to build`, `Blocked by` and the unticked acceptance boxes only. Drop `Claimed by`, `Evidence`, `Gate`, `Hunt`, `Merged to`, "What ticket N learned". Set `Status: ready-for-agent`.
  - Ticket 19 (`needs-triage`) and 22 (one box open) were not finished in the original run; say in the brief that they are in scope as written and count them as such in both arms.
  - The `.scratch/overview/` map and `docs/specs/2026-10-18-*.md` exist at `a5674b4` and are the intended inputs.
- **Residual contamination I cannot remove:** the 9 late tickets still encode what the original run learned. The ticket already says neither replay compares directly with the 142M; the same limit applies to the comparison of the two replays: it is fair between them (same inputs), not to the original.
- **What the original run had that the replay arms need decided:** the original used an owner "3-hunt gate" and external reviewers (Mistral, Opus hunts, Codex when up) per ticket. If the replays do not specify the same gate, the numbers measure a different process. The brief for both arms must name one gate and the same review count, or say none.

## 2. The separate copy: code, PRs, CI, and why it cannot go live

**What I checked, against the message that started this task:**

- `~/.claude/routines/branch_deploys.py /home/tiroir/Projects/agentview dev` exits **1** (nothing fires). With `main` it exits 1 too, because **agentview has no `main` branch**: the remote is `https://github.com/thinkingtoo/agentview.git`, default branch `dev`, public. `git ls-tree origin/dev .github` returns nothing; `gh api repos/thinkingtoo/agentview/actions/workflows` lists no workflow. Ticket 02's evidence says the same (the repo has no `.github`, a push starts no check, `total_count` 0).
- So **no workflow deploys from agentview**. What is "live" is the systemd user units in the repo root: `agentview.service` runs `python3 %h/Projects/agentview/server.py` with that directory as `WorkingDirectory`, and the timers (`push`, `archive`, `snapshot`, `retention`, `summaries`) run scripts at `%h/Projects/agentview/…`. Live = the checkout at `/home/tiroir/Projects/agentview`, whatever is in it. The two hooks in `~/.claude/settings.json` (`turn_line.py`, `stop_line.py`) also point at that path.
- The original run merged straight to `origin/dev` (the Evidence lines say "merged to origin/dev as …"). The repo has one merged PR in its history (#1, unrelated). **There were no PRs in the original run.**

**So the copy is:**

- **Code:** a fresh clone with its own `.git`, at a path no unit and no settings entry names, for example `/home/tiroir/Projects/ab-replay/agentview-A` and `…/agentview-B`, one per arm, each checked out at `a5674b4` on a branch `replay-A` / `replay-B`. Not a worktree of the live checkout: worktrees share `.git`, and a push from one could reach the live remote. Not under `/home/tiroir/Projects/agentview-wt/`, which the original run used.
- **Where PRs merge:** a new repo (see the owner list) that is **not** `thinkingtoo/agentview`: `origin` of each copy points there and the `thinkingtoo` remote is removed before the run (`git remote -v` shows one URL). I recommend a **private** repo in the `sweatshop-ai` org, one repo with branches `replay-A` and `replay-B` as the two bases, PRs from feature branches into their own base, so the arms cannot see each other's PRs by accident of ordering. A public repo would also expose the self-hosted runner to fork PRs.
- **CI the copy needs.** The suite is `python3 -m unittest discover -s tests` (1,700–2,100 tests at various points in the original run; too heavy for the laptop by the standing rule). The org runners are `t-compute-1..3` (`runs-on: [self-hosted, linux, t-compute]`); `ubuntu-latest` fails in 1 s. So the replay repo needs one workflow file, `.github/workflows/test.yml`, `on: pull_request` to the two base branches, running the unittest suite on `[self-hosted, linux, t-compute]` with a throwaway `XDG_STATE_HOME`. `tests/ui_smoke.py` is run by hand by design (needs a browser and a throwaway server; it crashed or flaked on this laptop in the original run): **leave it out of CI and of "green"**, and say so in the brief. The workflow is added to the base commit of both arms, the same file, before either arm starts, so it is not part of what either arm builds.
- **Cannot trigger a deploy:** the copy has no workflow that deploys (neither does the original); the only workflow is the test one, and it runs in the new repo, not in `thinkingtoo/agentview`.
- **Cannot touch a live FleetView:** the copy's `server.py` is never started by a unit (units name the live path). If a worker starts a test server it must bind port 0 and use its own `config.json`; 8765 is refused by `ui_smoke.py` already. The brief repeats it.
- **Cannot write to `~/.claude`, the live hooks or the real dashboard — what is true and what is not:**
  - The code of the copy never writes there: its state files go to `$XDG_STATE_HOME` (`log.py`, `marks.py`, `tickets.py`, `lines.py`), which the brief points at a throwaway directory. Tests use fake providers.
  - **It is not airtight:** the live hooks in `~/.claude/settings.json` fire on *every* Claude session on this machine, including the workers of both arms (`turn_line.py`, `stop_line.py`, the team-line card). The arms' sessions will appear in the live FleetView and can ring its chime. Only a separate `CLAUDE_CONFIG_DIR` for the runs (own settings, own `projects/`, plugin installed there, login copied) would stop that. That is a bigger setup, and it also changes where transcripts land (which the measures use). I recommend accepting the dashboard noise and naming the arms' sessions with an `ab-` prefix, unless the owner prefers the separate config dir.
  - The copy's `agentview.service` etc. are inert files in the clone; the brief forbids `systemctl` and `install` on them.

## 3. Client data

Greps by client directory names under `~/Projects/thinkingtoo/clients`, the brain's `Clients/` folder and the project list (names not written here):

- Tracked files at `origin/dev`: **one hit**, `tests/test_snapshot.py` (a single line). Everything else: no hit, including all 22 ticket files, the specs and the map.
- Full history (`git log -p --all`): 6 matching lines, 0 matching commit messages.
- The ticket text mentions "a client project's card" without naming it.
- **Checked at the starting commit:** `a5674b4` has **no hit** in `tests/` (grep for the client directory names), so the `test_snapshot.py` line was added later and the copy, built from `a5674b4`, does not contain it. The history hits are all after `a5674b4`. `config.json` (real project names) is **not tracked**; the copy has only `config.example.json`. So the copy is free of client data by construction, provided it is built from `a5674b4` and not from `origin/dev`. Tickets 14–22 come from the stripped final text: grep them once more after stripping (the final files at `origin/dev` have no hit).
- The brief must tell workers not to read `~/.claude/projects` transcripts of other sessions for fixtures; the original run did (ticket 18's corpus). Replaying ticket 18 as written would again read real transcripts. **Decision needed: ticket 18 runs on invented fixtures only, or is excluded from both arms.**

## 4. The two runs, concretely

**Same for both:** starting commit and base from section 2, the same 22 stripped tickets, the same `test.yml`, the same Definition of done (merged PR into the arm's base, `test.yml` green on that PR's head, no unticked box), the same review gate (to be named by the owner), at most 3 concurrent workers or subagents, worker model Sonnet, worker effort medium, no Codex dependence (fall back to an Opus agent as the standing rule says, in both arms), and the same wall-clock allowance. Start: the same minute, from the same prompt skeleton, differing only in the one paragraph that says how to staff.

| | Arm A: boss | Arm B: one session with subagents |
|---|---|---|
| Main session | `boss-start overview-build-A` | `claude --model fable --effort high --autocompact 450k --fallback-model opus` in a tmux window, working directory `agentview-B` |
| Model and effort of the main session | Fable 5.1, high (boss-start defaults) | the same, set explicitly |
| Workers | `boss-lifecycle.sh spawn <dir> --model sonnet`, one worktree each under `…/ab-replay/wt-A/`, own branches | `Agent` calls with `model: sonnet`, `isolation: worktree` under `…/ab-replay/wt-B/` |
| Start prompt | `/boss`, then the brief | the brief as the first prompt; no `/boss` |
| Questions to the owner | through the boss's concierge as in a normal boss run | `AskUserQuestion` from the one session |

- **`boss-start` is the owner's command.** What he types, in a tmux pane: `boss-start overview-build-A`, then `/boss` in the pane that opens, then pastes the brief path. Nothing less is possible for the boss arm: the guard, the marker and `--autocompact 450k` come from `boss-start`; a bare `claude` + `/boss` gives a boss on the wrong settings and a different arm. The B arm starts with one command the owner types too (or I can print it for a Paste), but it is not a boss, so I could start it from a worker session with `tmux` if he allows it; I recommend he types both, so he sees that both started.
- **Keeping the arms from seeing each other:** separate clones, separate repo bases, separate tmux sessions, separate track names and brief files; `ab-A-` / `ab-B-` name prefixes; the brief for each says not to read, list or message the other arm's paths and sessions, and the briefs live outside both clones. The shared things I cannot separate: the laptop's `~/.claude/projects`, the live dashboard, and the weekly cap. A boss also lists other workers with `boss-lifecycle.sh list` (plain `list` shows all): the A boss will see B's session on that list unless it filters with `--mine`; the brief says so.
- **Can both run at once?** On this laptop: 16 cores, load ~3.5 right now. Each arm allows 3 concurrent workers. The standing rule is: no full suite locally, only touched files. With `test.yml` on t-compute the suite is never local, so both can run at once without breaking the rule; without that CI, no. The original run's own notes record `ui_smoke.py` flaking under load on this machine, which is a reason to keep it out. **Recommendation: run both at once only after `test.yml` exists and has gone green once on the base commit; otherwise one after the other, A first or B first by a coin flip the owner makes.** Running at once also puts the same load and the same hours of the day on both, which is the fairer duration comparison; running in sequence makes the cap check between them possible (section 6). On t-compute: three runners, each CI run holds one runner for the test run; 2 arms × up to 3 open PRs can queue; a queue in one arm costs that arm wall time, which is part of the measure.

## 5. The measures, the same way for both

Everything comes from files, with one tool, by arithmetic; no judgement in the table.

| Measure | Source | Tool and how |
|---|---|---|
| Tokens | transcripts under `~/.claude/projects/` for every session of the arm: main session, workers, and the subagent files under each session's `subagents/` directory | `routines/boss_efficiency_core.py` sums the `usage` fields (input, cache creation, cache read, output) per track; for arm B it needs the same attribution by working directory instead of by boss socket. **I did not find how the 142M of the original was counted** (not in the ticket or the audit notes); the table gives the four columns separately and a total, and the owner may want the original recomputed with the same tool. |
| Merged PRs | `gh api repos/<replay-repo>/pulls?state=all&base=replay-A` (and B) | count merged; list PRs closed unmerged separately |
| CI green | check-runs of each merged PR's head commit | `.total_count` first: zero means nothing ran |
| Reverts | `git log --grep='^Revert'` and PRs that undo an earlier PR, on each base | count |
| Serious post-merge defects | a fixed second pass: after both arms stop, one fresh Opus agent per arm with the same prompt reads the arm's final tree against the 22 tickets' boxes and runs its tests; plus the owner's own findings. Defined in advance as: a ticket box that is ticked and does not hold, or a regression in a test that passed on the base. | count and list; "serious" is the owner's call per item, listed with the evidence |
| Duration | first dispatch timestamp to the last merge, and separately the machine time (sum of intervals where any session of the arm has a call in flight) | from transcript timestamps, as the original's "37 h, 13 machine" were measured |
| The owner's minutes | **convention proposed:** every message the owner types into an arm's session starts an interval that ends at the arm's next assistant message, or 2 minutes, whichever is first; every `AskUserQuestion`/concierge question counts from the time it is shown to the time it is answered, capped at 5 minutes. Number of questions is reported beside it. Minutes the owner spends in the other arm count for the other arm. | from the transcripts and the fleet's ask records; I did not verify that the ask-shown timestamp is stored in a place I can read |

**Private table:** `/home/tiroir/Documents/brain/01-projects/boss-efficiency/ab-replay-table.md` (outside the public repo; the numbers have no client names, but the transcripts they come from do). The repo gets only ticket 08's final status line and the owner's decision, no transcript text.

## 6. Cost, time, and a stop in the middle

- **Tokens:** about 284M for two replays, an estimate from 2 × 142M, not measured. The original 142M belonged to a graph that started at 13 tickets; both replays know 22 at the start, so they may differ in either direction. By model: the main session is Fable, the rest Sonnet; cache reads dominate the count in both arms (the 2026-08-30 audit found 97–99% for a boss), so the token total is a poor proxy for the cap; the table must also give output tokens and cache writes.
- **Against the weekly cap:** I do not know. Nothing on this machine states what is left of the current week: `~/.claude/stats-cache.json`, `policy-limits.json`, the settings and agentview's `pace.json` (that one is per-track progress) contain no cap figure, and I did not find a usage file elsewhere. The owner sees it in the Claude Code usage screen.
- **A stop midway that leaves usable numbers: yes, if the stop is at a ticket boundary.** Each merged PR is a counted unit; the table is built per merged PR (tokens spent up to that merge, minutes, time), so a stop after N merges gives a complete table for N tickets in both arms, as long as both are stopped at the same ticket count or the same cumulative token figure. Two rules to set in advance: (1) the stop is "when either arm reaches X tokens", then the other arm is stopped at its next merge; (2) a partial result is reported as "N of 22", never extrapolated. A stop in the middle of a ticket leaves that ticket's tokens uncounted as merged work; they are reported as spent without a merge.

## 7. What the owner must decide or do before it starts

1. **Create the replay repo** and give the runners access: a private repo in the `sweatshop-ai` org (name his choice), with the t-compute runners allowed on it. Only his hand (GitHub). Without it there are no PRs and no CI green.
2. **Accept or change the stop condition.** The ticket says "merged PRs with CI green"; the original merged directly with local tests, and agentview has no CI. Add `test.yml` as described, **or** redefine done as "merged to the arm's base branch with the suite green on t-compute over ssh" (the rule for repos with no t-compute CI).
3. **Name the review gate** both arms use (the original had a 3-hunt gate with outside reviewers) or say none.
4. **Ticket 18:** invented fixtures only, or leave it out of both arms.
5. **Both at once, or one after the other**, and if one after the other, which first.
6. **The live dashboard noise:** accept it with an `ab-` prefix on the sessions, or set up a separate config dir for the runs (more setup, different transcript paths).
7. **Type the two start commands** (`boss-start overview-build-A` then `/boss`; the B command) when ready, after checking his weekly usage screen: the plan cannot see what is left.

## What would make the replay impossible as described

Nothing is impossible, but two things are not as described: **no CI and no PR flow exist** (items 1–2), and **"something deploys from agentview main" is not what I found**: there is no `main` and no workflow; the live thing is the systemd units pointing into the live checkout path, which the copy avoids by living elsewhere with its own `.git`.

## Boss's call on section 7 (Anton, 2026-11-05)

Decided by the boss; the owner can still overrule. The owner still decides when it starts and creates the repo.

- **Review gate:** both arms use the current rule from ticket 02.
- **Ticket 18:** out of both arms. Real transcripts must not be used, and a fixture version is a different ticket.
- **Dashboard noise:** accepted, `ab-` prefix, no separate config dir.
- **Done:** merged PRs with CI green, as the owner said: the private repo and `test.yml`.
- **Order:** one after the other, not at once. The Codex limit ran out twice the night before under less load, and two arms sharing it and this laptop would skew each other.
- **Correction:** the plan's note on `branch_deploys.py` stands as measured (exit 1 on agentview); the exit 0 in the original message was read from a pipe.
- **Not built yet:** the clean-replay script and the repo, until the owner decides.
