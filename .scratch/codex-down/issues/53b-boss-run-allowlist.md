# 53b: `boss-run` runs only what it can see completely

**What to build:** `boss-run` stops handing the boss's text to `bash -lc`. The command is an argument list, executed directly, and the reviewer is shown exactly that list. A single-argument command is accepted only when it is plain words and quotes; a program that runs another command is refused by name; `gh` and `git` are refused when they name their own aliases or extensions. The merge rule then reads the literal list and needs no cleverness. Replaces PR 148 (ticket 53), which tried to prove a shell string harmless.

**Status:** open (PR 150, wrap-up 2026-11-13: allowlist built and pushed, head e1dc685, CI green; real Codex round not run)

## Why not 53

PR 148 added a bash lexer (`merge_shape.py`) in front of the reviewer. Codex answered NO-GO on three rounds with 12 class a findings, each a new way to hide a merge: `env -S`, `flock -c`, `time -p`, `coproc`, `BASH_ENV`, a runtime-built `env --split-string`, `curl -X PUT .../merge`, `${x@P}`, a second `find -exec`, YAML forms in gh's config, an alias written and used in one command. Parsing shell to prove it harmless does not converge. The owner's decision (2026-11-13) is the inverse: refuse by default, and run only what can be read completely. PR 148 is closed; its lexer is not carried over (an allowlist needs no lexer for the shell, only a lexer for "plain words and quotes", which is 40 lines).

## Decisions

- **No shell.** `( cd "$CWD" && exec -- "${EXEC[@]}" )`. No `bash -lc`, so no expansion, glob, pipe, redirection or `&&` happens after the reviewer has read the command. `exec --`, and an argv[0] that must be a bare lowercase name, so a leading `-` cannot be read as an option of `exec` (Opus round 2, finding 1). Cost: the login profile no longer sets PATH for the command.
- **`argv_gate.py` is the gate, in Python.** boss-run calls it with the arguments; it answers one JSON object (exit 0 `{ok, argv, flat, display}`, exit 1 `{ok:false, rule, detail}`), and boss-run refuses on anything else (crash, signal, no python3, malformed JSON), as the reviewer path already does.
- **Single argument: fully literal or refused.** Plain words and quotes. Single quotes keep everything; double quotes keep everything except `$`, backtick and backslash. Outside quotes `$ ` \ ; & | < > ( ) { } * ? [ ! ~` are refused, `#` at a word's start, any control character, and a newline. A newline inside quotes is allowed: it is a byte of the word, shown to the reviewer as it is, and a multi-line `--body` is ordinary boss usage (the spec said "no newline"; outside quotes it is refused, inside it is data). Quote concatenation (`g'h'`) is allowed: it yields the word `gh`, which is what the hard rules read. Several arguments are taken as they are. Arguments that are not UTF-8 are refused, so what the reviewer reads is byte for byte what runs.
- **Positive allowlist for argv[0] (owner's decision, 2026-11-13, replacing the denylist of PR 150 rounds 1 and 2).** Sized from the 714 approved commands in `~/.claude/pm/boss-run.log` (gh 475, git 141, bash 57, python3 25, sh 8, docker 3, rm 2, sed/mv/cp 1 each): `gh git cp mv mkdir touch rm ls cat head tail jq grep rg date systemctl`. Everything else is refused with the rule `program not on boss-run's list`: shells, interpreters, `env`, `find`, `sed`, `awk`, `curl`, `wget`, `tar`, `ssh`, `docker`, `sleep`, `echo`, editors, `claude`, `codex`. **`bash`, `sh` and `python3` are refused on purpose**: a boss that needs a script dispatches it to a worker (Cardinal Rule); SKILL.md says so. `rg` is on the list for the boss's reading; `rg --pre*` and `--hostname-bin*` are refused. `rg`, `jq`, `grep` are not in the log; they are the read tools the owner listed.
- **The name is bare and lowercase** (`[a-z][a-z0-9-]*`). A path (`/usr/bin/gh`, `./x`), a name with `=`, a leading `-`, `GH`, `git-push`, `hub` are refused: this closes "gh under another name", the `git-core` helper names and the hardlink/symlink launderers by construction (Opus round 2, findings 1, 4, 5, 7).
- **Resolved from fixed directories, not PATH, after the APPROVE.** `/usr/local/bin /usr/bin /bin /usr/lib/cargo/bin/coreutils` (the multi-call coreutils of this machine live in the last), plus any directories the owner lists in `<config dir>/boss-run-trusted-path`. The first executable of that name wins; its real location must be in a trusted directory too, so a link that leads out is refused (`cp /bin/bash /tmp/x` cannot be run: `x` is not a name on the list, and a copy of `gh` in `/tmp` is not in a trusted directory). The absolute path found is what `exec` runs. This ends the two-directory PATH of Opus round 2, finding 8. The owner's file adds trust, so `cp mv mkdir touch rm` refuse it by name (see below). It lives under `CLAUDE_CONFIG_DIR`, which the boss's own environment can name; so can the log directory and `boss-hard-rules.tsv`, which were already there. Said plainly: this guards against a mistaken or sloppy boss, not one that rewrites the environment of its own call.
- **`gh`: a subcommand list built from the log.** `pr` (view list create comment checks diff close reopen edit ready review status checkout), `issue` (view list create comment close reopen edit status), `run` (view list watch rerun cancel), `workflow` (run view list), `label` (list create edit), `repo` (view list), `api`, `--version`. `pr merge` is refused under the rule `PR merge outside boss_merge` (`boss_merge.py` is the one way). The nested word is the first that is not an option or the value of `-R`/`--repo`. An option before the subcommand is refused. After the APPROVE, `gh alias list` on the resolved binary must not name the subcommand, and must answer (else refused). gh does not let an alias shadow its own commands, so the check cannot fire on a real gh; it costs one call and the owner asked for it. `gh api`: refused for a `pulls…merge` path in any spelling and any method, `repos/…/merges`, the two merge mutations, percent-encoded arguments, and a GraphQL body read from a file (`@file`, `--input`).
- **`git`: a subcommand list.** worktree push merge commit branch pull add restore fetch status log diff show rev-parse. Before the subcommand only `-C <dir>` and `--no-pager`; `-c` and `--config-env` and everything else refused. After it, refused: a `-c`/`--config` anywhere, `ext::`, and the options that run a program or write where told, **by any unambiguous prefix** of the long option (`--exe`, `--upload-pa=`, `--receive-p=`, `--strat=`, `--out=`, three characters or more), and `-s` clusters for `merge` (a merge strategy runs a `git-merge-<name>` helper). No alias probe for git: the allowed subcommands are built-ins, which git does not let an alias shadow. `git -C d push origin main` is read by the hard rules as `git push origin main`.
- **`systemctl`: `status` and `show` only.** `--user --system --no-pager --no-legend -l --full` may precede; `-H`/`--host`/`-M`/`--machine` are refused (they reach another machine). **`--user restart` is not allowed**, decided: none of the 714 logged commands used `systemctl`, a restart changes a service (the hard rule already refuses `restart|stop` as a pattern), and the owner's list names only status and show. A dev restart goes to the owner or a worker.
- **`cp mv mkdir touch rm` are refused on** `.git`, any `hooks` or `.githooks` directory, shell startup files, `.ssh`, `.gnupg`, `.gitconfig`, `.config/{git,gh,systemd}`, `.local/share/gh`, and boss-run's own rule files (`boss-run-trusted-path`, `boss-hard-rules.tsv`). With no `bash`, `cp` plus a program on the list is the only way left to plant something another allowed program then runs; these are the places that matters. A script the boss copies to an ordinary path cannot run: nothing on the list runs a file.
- **Hard rules read the literal list.** `"gh" pr merge 5` is the text `gh pr merge 5`; the existing rule `PR merge outside boss_merge` (ticket 41) and the owner's `boss-hard-rules.tsv` are unchanged. The git and systemctl rules (`git reset --hard`, `git clean -f`, `systemctl restart|stop`) can no longer be reached through those programs (the gate refuses first) and stay as patterns for the owner's rules and for words in arguments.
- **`gh api …/pulls/N/merge` is refused for every method, GET included** (ticket 11a pinned the GET as allowed; a method cannot be told from the arguments with certainty, and `gh pr view N --json state,mergedAt` answers the same question).
- **The gate runs in two calls.** The first (text and program name, nothing run), then the hard rules, then the reviewer, and the resolution and the `gh` alias read only after the APPROVE, right before exec: a REJECT, a refused merge or no answer leaves no call on `gh`, and nothing planted is run for a command that was not approved.
- **Left to the reviewer and the owner, said plainly.** boss-run does not read the programs it runs: `git commit` runs the repo's hooks (the owner's files), `git diff` runs a configured external diff, `jq`/`grep`/`rg` read any file. The list is complete for what the argument list says; what a trusted program does with its configuration is not.

## Findings of PR 148 (rounds 1 to 3), now refused by construction

| Finding | Refused because |
|---|---|
| `env -S '"gh" pr merge 5'`, `flock -c`, `script -c`, `watch` | `env flock script watch` are not on the list |
| `time -p sh -c …`, `coproc JOB sh -c …` | `time`, `sh`, `coproc` are not on the list |
| `BASH_ENV=… bash -c`, `bash --rcfile … -ic` | `BASH_ENV=…` is not a bare lowercase name; `bash` is not on the list |
| `gh copilot` that is an alias or an extension | `gh alias list` / `gh extension list` name it |
| `"curl" -X "PUT" …/pulls/5/merge` | `curl` is not on the list; for `gh api` a `pulls…merge` path is refused, any method |
| `env --split-string="$X"` | `$` outside literal text; `env` is not on the list |
| `m: "pr merge"` alias | the gate never reads gh's YAML: it asks `gh alias list` and refuses the name |
| `${x@P}` | `$` is not literal |
| `find … -exec "$GH" pr m'er'ge 5 \;` | `$`, `\`, `;`; `find` is not on the list |
| `aliases: # comment` / flow mapping | the gate never reads gh's YAML |
| alias written then used in one command | one command is one argument list; `;` is refused, and the alias is read at the next call |

## Done when

- [x] Tests first: `test_argv_gate.py` (every finding refused, normal boss usage accepted, every refusal class) and `test_boss_run.py` (the gate before the reviewer, no shell, the reviewer shown the list, the merge rule on the literal list)
- [x] `boss-run --selftest` updated (a literal-argument refusal case added)
- [x] SKILL.md says what can no longer be written inside `boss-run` and that pipes stay outside
- [x] CHANGELOG (Unreleased)
- [ ] Review: real Codex, at most 3 fresh rounds, a second only after a class a or b finding

## Review

| Round | Head | Reviewer | Verdict | Tokens |
|---|---|---|---|---|
| 1 | 227e794 | codex (real) | NO-GO, 6 class a | 94,168 |
| 2 | 7c5721d | codex hit its usage limit (25,026 tokens, error), then opus fallback (provisional, read-only, tokens not reported) | NO-GO, 9 findings | not a Codex round |

Round 1 fixed in 7c5721d: probe moved after the APPROVE and onto the command's own repository (`--git-dir`); `curl wget http xh tar rsync zip ...` refused by name.

Round 2 (Opus, provisional, NOT counted as the real second round) findings, unfixed:
1. `exec "${ARGV[@]}"`: an argv[0] starting with `-` makes bash `exec` read options (`-a x /bin/bash -c ...`). Fix: `exec --` and refuse argv[0] starting with `-`.
2. git options by exact spelling only: abbreviations (`--exe`, `--upload-pa=`), clustered shorts (`-mx cmd`), attached `-ush`.
3. `git grep -O<cmd>` / `--open-files-in-pager`.
4. git helper names (`git-push`, `/usr/lib/git-core/git-push`) skip the git checks and the hard-rule text (`git-push origin main`).
5. gh under another name (`ln -s gh /tmp/hub`): the flat text does not start with `gh`, so the merge regex misses `pr merge`.
6. git config keys `remote.<n>.uploadpack/receivepack/vcs`; `git clone -c key=value`.
7. Laundering: the dynamic loader (`ld-linux ... /bin/bash`), `cp /bin/bash /tmp/x` then run it; more program-runners (`ssh-agent`, `sqlite3 .shell`, `psql -c '\!'`, `nix-shell --run`, `pwsh`, `fakeroot`, `bwrap`, `xterm -e`).
8. PATH searched from boss-run's directory by the gate and again after `cd "$CWD"` by `exec`: a relative PATH entry makes them differ. Fix: exec the path the gate found.
9. Over-refusal: the pattern `ed|vi|vim...[-.0-9a-z]*` refuses `editorconfig-checker`, `virsh`.

Pattern to weigh: items 2, 4, 6, 7 are the same shape as PR 148's findings (a denylist of option spellings and program names that grows with each review). Items 1, 5, 8, 9 are plain bugs. A smaller allowlist of argv[0] (positive list: gh, git with a fixed subcommand list, cp, mkdir, touch, ls, cat, jq, grep, rg, date, head, tail, systemctl --user status ...) would close 2, 4, 6, 7 by construction; that is a decision for the owner.
