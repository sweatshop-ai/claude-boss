# 53b: `boss-run` runs only what it can see completely

**What to build:** `boss-run` stops handing the boss's text to `bash -lc`. The command is an argument list, executed directly, and the reviewer is shown exactly that list. A single-argument command is accepted only when it is plain words and quotes; a program that runs another command is refused by name; `gh` and `git` are refused when they name their own aliases or extensions. The merge rule then reads the literal list and needs no cleverness. Replaces PR 148 (ticket 53), which tried to prove a shell string harmless.

**Status:** open

## Why not 53

PR 148 added a bash lexer (`merge_shape.py`) in front of the reviewer. Codex answered NO-GO on three rounds with 12 class a findings, each a new way to hide a merge: `env -S`, `flock -c`, `time -p`, `coproc`, `BASH_ENV`, a runtime-built `env --split-string`, `curl -X PUT .../merge`, `${x@P}`, a second `find -exec`, YAML forms in gh's config, an alias written and used in one command. Parsing shell to prove it harmless does not converge. The owner's decision (2026-11-13) is the inverse: refuse by default, and run only what can be read completely. PR 148 is closed; its lexer is not carried over (an allowlist needs no lexer for the shell, only a lexer for "plain words and quotes", which is 40 lines).

## Decisions

- **No shell.** `( cd "$CWD" && exec "${ARGV[@]}" )`. No `bash -lc`, so no expansion, glob, pipe, redirection or `&&` happens after the reviewer has read the command. Cost: the login profile no longer sets PATH for the command; boss-run's own PATH is used.
- **`argv_gate.py` is the gate, in Python.** boss-run calls it with the arguments; it answers one JSON object (exit 0 `{ok, argv, flat, display}`, exit 1 `{ok:false, rule, detail}`), and boss-run refuses on anything else (crash, signal, no python3, malformed JSON), as the reviewer path already does. Python, not bash, because the checks read what `gh` and `git` report about themselves. boss-run already needs python3 for the reviewer chain.
- **Single argument: fully literal or refused.** Plain words and quotes. Single quotes keep everything; double quotes keep everything except `$`, backtick and backslash. Outside quotes `$ ` \ ; & | < > ( ) { } * ? [ ! ~` are refused, `#` at a word's start (a comment), any control character, and a newline. A newline inside quotes is allowed: it is a byte of the word, shown to the reviewer as it is, and a multi-line `--body` is ordinary boss usage (the spec said "no newline"; outside quotes it is refused, inside it is data). `!` and `~` are refused unquoted because they are history and tilde expansion in a shell and the list is shown as if no shell existed. Quote concatenation (`g'h'`) is allowed: it yields the word `gh` and the hard rules read the word, which is the point.
- **Several arguments are taken as they are.** No quoting round trip, no literal check: each is one word and is never expanded.
- **argv[0] refused by name** (reason `program that runs another command`, exit 5), by its name as written and by what it resolves to through PATH and symlinks (so `ln -s /bin/bash x; ./x` cannot launder it, and busybox applets resolve to busybox): shells, `env eval exec command builtin xargs find time nice nohup timeout sudo su doas watch script parallel setsid flock ionice taskset stdbuf chroot unshare nsenter runuser pkexec systemd-run`, `tmux screen at batch crontab`, `make cmake ninja just`, interpreters (`python* perl ruby node deno bun php lua tclsh java expect osascript`), `awk sed ed ex vi vim nano emacs less more man`, `ssh scp sftp mosh socat nc ncat telnet`, `strace gdb valgrind`, `claude codex gemini aider`, package runners (`npx npm pnpm yarn uv uvx pipx pip cargo go`) and `coproc`. Decisions asked for in the spec:
  - **`sed`, `awk`: refused outright.** `sed` has `e` and `w` in its script (`s/x/y/e` runs a command) and a safe subset cannot be told from the script text without a parser; `awk` has `system()`. The boss has `jq` and `grep`.
  - **`ssh`, `scp`, `sftp`, `mosh`: refused outright**, not only with a remote command: `-o ProxyCommand`, `LocalCommand` and `-J` run local programs, and which argument is the host depends on ssh's option table. A boss that needs a remote host asks the owner.
  - **`git`: refused with** `-c`/`--config-env`/`--exec-path`/`--paginate`, any option before the subcommand it does not know, a config key that can run a program (`alias.` `core.` `pager.` `credential.` `include.` `filter.` `diff.` `merge.` `url.` `sequence.` `gpg.` `ssh.` and others, read or write), `config -e`, `--exec`/`--upload-pack`/`--receive-pack`, `ext::`, `rebase -x/-i`, `bisect run`, `submodule foreach`, `clone -u`, and the subcommands `difftool mergetool filter-branch instaweb help send-email daemon gui gitk citool credential`; and when the subcommand is an alias in git's own config (`git -C <dir> config --get-regexp '^alias\.'`, the `-C` chain applied, case-insensitive), or the config cannot be read.
  - **`rg --pre`, `tar --to-command/--checkpoint-action/-I/--use-compress-program`, `rsync -e/--rsh`, `zip -T`, `wget -e`:** refused as options that run a program.
  - **A relative program path (`./x`, `scripts/x`) and an `=` in argv[0] are refused:** the first runs a file the reviewer cannot read from the planted directory, the second would be an environment assignment in a shell and means something else here.
- **`gh`** (reason `gh alias`, `gh extension`, `gh alias cannot be read`): the subcommand (`argv[1]`) is refused when `gh alias list` reports it as an alias, when `gh extension list` reports it as an extension, and when either call fails (an unauthenticated `gh` fails `extension list`, so every call is refused; `gh auth login` is the owner's). An option before the subcommand is refused, `gh codespace`/`cs` (ssh into a remote shell) is refused, `gh extension` is refused except `list`, `search` and `browse`. gh's own commands cannot be aliased, so no list of built-ins is kept (round 1, finding 4).
- **`gh api …/pulls/N/merge` is refused for every method, GET included** (ticket 11a pinned the GET as allowed; a method cannot be told from the arguments with certainty, and `gh pr view N --json state,mergedAt` answers the same question).
- **The gate runs in two calls.** The first (text and program name, no tool run), then the hard rules, then the `gh`/`git` probes: a merge the rules refuse leaves no call on `gh`. Arguments that are not UTF-8 are refused, so what the reviewer reads is byte for byte what runs.
- **Merge rule on the literal list, in two places.** boss-run's existing hard rule `PR merge outside boss_merge` (a regex, ticket 41) now matches the joined list, quotes gone, so `"gh" pr merge 5` is the text `gh pr merge 5`. And `argv_gate` refuses, for `curl wget http xh` and `gh api`, a `pulls…merge` path in any spelling (`pulls/5/./merge`, `pulls/5//merge`), whatever the method (`curl -T` is a PUT), `repos/…/merges` (the branch merge endpoint, a merge into main without a PR), the two merge mutations, percent-encoded arguments, `curl -K/--config`, and a GraphQL body read from a file (`@file`, `--input`, `-d @f`).
- **Hard rules see git without its leading options.** `git -C dir push origin main` is `git push origin main` to the rules, as it always should have been (it was a hole of ticket 41's regex, found while writing this).
- **Left to the reviewer and the owner, said plainly.** boss-run does not read the programs it runs: a script the boss wrote earlier, `cp x .git/hooks/pre-commit` then `git commit`, a program on PATH not named above. The reviewer reads the list; the list is complete, the program is not. The denylist is a floor, not a proof, and it grows only from incidents.

## Findings of PR 148 (rounds 1 to 3), now refused by construction

| Finding | Refused because |
|---|---|
| `env -S '"gh" pr merge 5'`, `flock -c`, `script -c`, `watch` | `env flock script watch` are on the list |
| `time -p sh -c …`, `coproc JOB sh -c …` | `time`, `sh`, `coproc` are on the list |
| `BASH_ENV=… bash -c`, `bash --rcfile … -ic` | a command starting with an assignment is refused; `bash` is on the list |
| `gh copilot` that is an alias or an extension | `gh alias list` / `gh extension list` name it |
| `"curl" -X "PUT" …/pulls/5/merge` | quotes are gone in the list; a `pulls…merge` path in `curl` is refused, any method |
| `env --split-string="$X"` | `$` outside literal text; `env` on the list |
| `m: "pr merge"` alias | the gate never reads gh's YAML: it asks `gh alias list` and refuses the name |
| `${x@P}` | `$` is not literal |
| `find … -exec "$GH" pr m'er'ge 5 \;` | `$`, `\`, `;`; `find` on the list |
| `aliases: # comment` / flow mapping | the gate never reads gh's YAML |
| alias written then used in one command | one command is one argument list; `;` is refused, and the alias is read at the next call |

## Done when

- [x] Tests first: `test_argv_gate.py` (every finding refused, normal boss usage accepted, every refusal class) and `test_boss_run.py` (the gate before the reviewer, no shell, the reviewer shown the list, the merge rule on the literal list)
- [x] `boss-run --selftest` updated (a literal-argument refusal case added)
- [x] SKILL.md says what can no longer be written inside `boss-run` and that pipes stay outside
- [x] CHANGELOG (Unreleased)
- [ ] Review: real Codex, at most 3 fresh rounds, a second only after a class a or b finding

## Review

(rounds are recorded here)
