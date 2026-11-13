# 53: `boss-run`'s merge rule reads what the shell will run, not the raw text

**What to build:** the hard rule `PR merge outside boss_merge` in `skills/boss/bin/boss-run` also matches the command after the shell has tokenised it, and refuses what it cannot see through (Codex NO-GO on PR 121, recheck round 5; class a).

**Status:** open (Codex NO-GO after 3 rounds, round 3 findings below)

## The finding, checked on origin/main (7bffd52)

`"gh" pr merge 5`, `gh pr "merge" 5` and `gh api -X "PUT" repos/o/r/pulls/5/merge` all run the forbidden operation after quote removal and matched none of the raw-text regex (tickets 41 and later only widened the regex). It held: all three went on to the reviewer.

## Decisions

- **A second check beside the regex, in `skills/boss/merge_shape.py`.** `boss-run` pipes `$CMD` (the bytes `bash -lc` will run) to it. Exit 0: clean; exit 1: `name<TAB>detail`; anything else (a crash, a signal, no python3) is no answer and refuses, so the rule cannot fail open. The raw regex stays (it also covers `curl -X PUT .../merge`, and the owner's own `boss-hard-rules.tsv` lines are raw regexes). Python, not bash, because the tokeniser is a real lexer; `boss-run` already needs python3 for the reviewer chain.
- **Not `shlex`.** `shlex` has no `$(...)`, backtick, `${...}`, `$'..'`, heredoc or operator model, and cannot say whether a word held an expansion. The module has its own small lexer for what the shell does to a word, and says "cannot see through" at anything it cannot lex (an unclosed quote or `$(`, a heredoc that never closes, nesting deeper than 8).
- **Seen through, not refused:** quotes, backslashes and `$'..'` in any token (so `"gh" pr "merge"`, `g\h`); `;` `&&` `||` `|` `&` `(` `)` newline, braces, `if/then/do`; assignments and redirections in front; `$(...)`, backticks, `${...}`, `<(...)` and heredoc bodies are scanned as commands of their own; `sh|bash|... -c 'literal'` and `eval literal` are scanned as the script they carry; `env`, `command`, `exec`, `nohup`, `nice`, `time`, `timeout`, `sudo`, `doas`, `stdbuf`, `setsid`, `ionice`, `watch`, `flock`, `script` and `find -exec` are followed to the command they run; a literal `gh` in any later word of a command is read as gh (as `echo gh pr merge` always was refused). Why: each of these keeps the command's text intact once quotes are gone, so refusing them would only cost legitimate commands.
- **`gh` is read as gh reads it:** the first two non-option words are the subcommand (`-R`/`--repo` take the next word, whatever it is, so `gh -R merge pr view` is a view). `pr merge` is refused; `gh api` is refused for a non-GET method (or fields, which make it a POST) to `pulls/<n>/merge`, for `-X PUT` to an endpoint built at run time, and for `graphql` with a merge mutation, or with a query read from a file (`@file`, `--input`) or built at run time. Methods are read in all shapes (`-X PUT`, `-XPUT`, `--method=put`, quoted).
- **Refused because it cannot be seen through** (reason `merge rule cannot see through`, same exit 5, nothing run, the owner takes it): a command name built at run time (`$GH`, `gh${IFS}pr`, `` `echo gh` ``, a glob or brace in the name); a `gh` subcommand built at run time (`gh pr $S`, `gh pr m*`); `eval` or `sh -c` of text built at run time; a shell that reads a file or stdin (`bash x.sh`, `echo ... | sh`; a heredoc or here-string with a literal body is read); `source`/`.`; `xargs`/`parallel` feeding gh or a shell (the arguments come from stdin); a wrapper whose command is built at run time; `gh alias set|import`, and any `gh <word>` that is not one of gh's own commands (a user alias or extension may be `pr merge`; gh refuses aliases that shadow built-ins, so the built-in list is the whole safe set). Each is a trust-boundary question the text cannot answer; a boss that needs one asks the owner.
- **Cost accepted:** `gh pr view $N` (variable in an argument) and `echo $(date)` still pass to the reviewer; `$GH pr view`, `gh pr $S` and `timeout $T gh ...` are refused. A boss that hand-types literal numbers loses nothing.
- **Out of scope, said plainly:** other languages (`python3 -c`, `perl -e`, `ssh host '...'`) can still spell a merge; they stay with the reviewer and the owner's own rules. Shell functions and aliases defined earlier in the same command are not tracked (`bash -lc` has no aliases).

## Round 1 (Codex NO-GO on 4c516e9, four class a findings) and what changed

- **A command line handed to a program that runs it** (`env -S '"gh" pr merge 5'`, `flock -c`, `script -c`, `watch`, `su -c`, `ssh host '...'`): any word of several tokens (also the part after `=` of an option) is now read as shell text, and a merge found in it refuses. Other findings in it are ignored, so a `git commit -m 'a b c'` still passes. This replaces listing each program's string option: the list is unbounded, the shape is not.
- **`time -p` and `coproc JOB`** are wrappers, not skipped reserved words: the command is looked for behind their options and name.
- **Startup files and other config**: `BASH_ENV=`, `ENV=`, `GH_CONFIG_DIR=`, `XDG_CONFIG_HOME=`, `XDG_DATA_HOME=` and `HOME=` set anywhere (a prefix, `export`, `env`, a redirection target), `--rcfile`/`--init-file`, and any text naming gh's own config or extension files are refused: each changes what runs or where gh looks, from a place the text does not show.
- **No list of gh's built-in commands.** A list is right for one gh version only. For a first word that is not `pr`, `api`, `alias` or `extension`, the scanner now looks where gh keeps what could be a merge: an alias in gh's `config.yml` (`GH_CONFIG_DIR`, else `XDG_CONFIG_HOME/gh`, else `~/.config/gh`) is expanded and scanned (a `!` alias as shell); an extension directory `gh-<name>` under `XDG_DATA_HOME/gh/extensions` is refused by name; a config that cannot be read, or an alias in a form the small reader is not sure of (block scalar, anchor, loop), is refused. A word that is neither (`gh copilot`, a typo) is gh's own to answer. `gh extension` other than `list`, `search` and `browse` is refused (it installs or runs code the text does not show), so an alias or extension cannot appear inside the same command that creates it.

## Round 2 (Codex NO-GO on fc03162, four findings) and what changed

- **A merge by another program.** The token rule only knew `gh`. `check_put_merge` now reads every command: a merge mutation name in any word, or a PUT marker (`PUT`, `-X PUT`, `-XPUT`, `--request=put`, `--method PUT`) together with a `pulls/<n>/merge` word, is the merge API whoever sends it (`"curl" -X "PUT" ...`); a PUT to an address built at run time (`curl -X PUT "$URL"`) cannot be seen through.
- **`env --split-string="$X"`.** An option that runs a command line (`-S`, `--split-string`, `-c`, `--command`, glued or not) with a value built at run time is refused, not skipped as an option.
- **YAML in gh's config.** The small alias reader now refuses what it cannot decode: a backslash in a name or value (YAML escapes), an alias that continues on the next, deeper line (a plain scalar folds to one line).
- **`[` is a glob only when it forms a bracket expression** (`g[h]`). `[ -f file ]` and `[[ 1 == 1 ]]` are commands again and reach the reviewer.

## Done when

- [x] Tests first: `test_merge_shape.py` (54 hidden merges, 51 opaque forms, 54 clean commands, the CLI contract, nesting limit); `test_boss_run.py` HardRules: the hidden merges refused with `seen:` in the message, the log and the exit, the same as an argument list, the opaque ones named, harmless look-alikes still reach the reviewer, a shape check that does not answer refuses
- [x] The existing 59 `test_boss_run.py` tests stay green
- [x] CHANGELOG (Unreleased)

## Round 3 (Codex NO-GO on d3d7f57, the last round review-by-risk allows) — not fixed

- `${x@P}` (prompt expansion) executes command substitutions in the value of `x`, built piecemeal; a `${...}` is treated as safe outside command position.
- `check_wrapper` returns after the first `find -exec`; a later `-exec "$GH" pr m'er'ge 5 \;` is not read.
- The alias reader accepts only a bare `aliases:` line: `aliases: # comment` and flow mappings read as "no aliases".
- Alias resolution reads gh's config before the command runs; a command can build the config path, write a merge alias and call it in the same approved command.

Pattern across 3 rounds: 12 findings, each a new way for text to hide a command. Each fix added a refusal class, and the next round found the next. The design question for the owner (in the handoff): keep growing the scanner, or refuse by default (an allowlist of simple commands that need no reading), or make the boss not hand-type merges at all.
