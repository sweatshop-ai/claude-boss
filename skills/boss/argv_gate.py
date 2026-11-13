#!/usr/bin/env python3
"""argv_gate: boss-run runs only what it can see completely (codex-down ticket 53b).

boss-run used to hand the boss's text to `bash -lc` and try to prove the text harmless; a
reviewer, hard rules and a lexer (PR 148) all read the text and Codex found twelve ways for
shell syntax to hide a merge. Then a denylist of program names (PR 150, rounds 1 and 2) grew by
one finding set per round. This module is the allowlist. The command is an argument list,
executed directly, and the reviewer is shown exactly that list:

  1. A single-argument command is split into a list only when it is fully literal: plain words
     and quotes. Anything a shell would expand, join or redirect is refused.
  2. argv[0] must be a bare name on PROGRAMS, the programs boss-run is for (sized from the 714
     approved commands in the log of 2026-11-13). Everything else is refused: a shell, an
     interpreter, `env`, `find`, `sed`, `curl`, `tar`, `ssh`, any program not named. A boss that
     needs a script dispatches it to a worker.
  3. `gh` and `git` take only the subcommands listed here and only options that cannot run a
     program; `systemctl` only `status` and `show`.
  4. After the reviewer's APPROVE the program is resolved from a fixed set of directories, never
     from PATH, and that absolute path is what runs.

Usage (as boss-run calls it): argv_gate.py [--single|--resolve] [--config-dir DIR] [--cwd DIR] -- ARG...
Prints one JSON object. Exit 0: {ok:true, argv, flat, display[, exec]}. Exit 1: {ok:false, rule,
detail}. Any other exit status or no JSON is no answer, and boss-run refuses.
"""
import json
import os
import re
import shlex
import subprocess
import sys

REFUSED = 5


class Refused(Exception):
    """A rule that stops the command. `name` is the rule, `detail` what matched."""
    exit = REFUSED

    def __init__(self, name, detail):
        super().__init__("%s: %s" % (name, detail))
        self.name, self.detail = name, detail


class Plan:
    """What boss-run will run: `argv` as typed; `flat` for the hard rules; `display` for the reviewer."""

    def __init__(self, argv, flat):
        self.argv, self.flat, self.display = argv, flat, shlex.join(argv)


# ---------------------------------------------------------------- literal text ----
LITERAL = "command not fully literal"


def _refuse_literal(what):
    raise Refused(LITERAL, what)


def split_literal(cmd):
    """The words of `cmd` when it is plain words and quotes, else Refused.

    Single quotes keep everything. Double quotes keep everything but `$`, the backtick and the
    backslash, which a shell would act on. A newline is a word's own byte inside quotes (it is
    shown to the reviewer as it is) and a command separator outside, which is refused. Outside
    quotes a word may not hold any character a shell treats as syntax.
    """
    if "\x00" in cmd:
        _refuse_literal("a NUL byte")
    words, cur, started, i, n = [], [], False, 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in "'\"":
            end = cmd.find(c, i + 1)
            if end < 0:
                _refuse_literal("an unclosed quote")
            body = cmd[i + 1:end]
            if c == '"':
                for bad, name in (("$", "$ inside double quotes"), ("`", "a backtick inside double quotes"),
                                  ("\\", "a backslash inside double quotes")):
                    if bad in body:
                        _refuse_literal(name)
            cur.append(body)
            started = True
            i = end + 1
            continue
        if c in " \t":
            if started:
                words.append("".join(cur))
                cur, started = [], False
            i += 1
            continue
        if c == "\n":
            _refuse_literal("a newline (a second command)")
        if ord(c) < 32 or c == "\x7f":
            _refuse_literal("a control character")
        if c in "$`\\;&|<>(){}*?[!~":
            _refuse_literal("%r outside quotes" % c)
        if c == "#" and not started:
            _refuse_literal("a comment")
        cur.append(c)
        started = True
        i += 1
    if started:
        words.append("".join(cur))
    return words


# ------------------------------------------------------------ the allowlist ----
NOT_ON_LIST = "program not on boss-run's list"
BARE_NAME = re.compile(r"[a-z][a-z0-9-]*")

FILE_PROGRAMS = {"cp", "mv", "mkdir", "touch", "rm"}
READ_PROGRAMS = {"ls", "cat", "head", "tail", "jq", "grep", "date"}
PROGRAMS = {"gh", "git", "systemctl", "rg"} | FILE_PROGRAMS | READ_PROGRAMS

# The directories a program may resolve to. PATH is not consulted: a `gh` earlier on PATH, a
# relative PATH entry or a link made in /tmp is not on this list. A real file's own directory
# must be here too, so a link in a trusted directory cannot lead out of it. The coreutils
# directory is where multi-call builds keep their binaries. The owner may name more in
# <config dir>/boss-run-trusted-path (one directory per line); that file adds trust, so the
# file programs refuse to touch it.
FIXED_DIRS = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/lib/cargo/bin/coreutils")
TRUSTED_FILE = "boss-run-trusted-path"


def trusted_dirs(config_dir):
    extra = []
    if config_dir:
        try:
            with open(os.path.join(config_dir, TRUSTED_FILE), encoding="utf-8") as f:
                extra = [line.strip() for line in f if line.strip().startswith("/")]
        except OSError:
            pass
    return [*extra, *FIXED_DIRS]


def resolve(name, config_dir):
    """The absolute path `name` runs as: the first executable of that name in a trusted
    directory, whose real location is in a trusted directory too. Raises Refused."""
    dirs = trusted_dirs(config_dir)
    real_dirs = {os.path.realpath(d) for d in dirs}
    for d in dirs:
        path = os.path.join(d, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            real = os.path.realpath(path)
            if os.path.dirname(real) not in real_dirs:
                raise Refused("program resolves outside the trusted directories", "%s -> %s" % (path, real))
            return path
    raise Refused("program not found in the trusted directories", "%s (looked in %s)" % (name, ":".join(dirs)))


# --------------------------------------------------------------------- gh ----
# Built from the commands in the log (pr 322, api 103, issue 26, run 19, workflow 3, label 1, repo 1).
# `merge` is not in it: boss_merge.py is the one way to merge.
GH_SUBS = {
    "pr": {"view", "list", "create", "comment", "checks", "diff", "close", "reopen", "edit", "ready",
           "review", "status", "checkout"},
    "issue": {"view", "list", "create", "comment", "close", "reopen", "edit", "status"},
    "run": {"view", "list", "watch", "rerun", "cancel"},
    "workflow": {"run", "view", "list"},
    "label": {"list", "create", "edit"},
    "repo": {"view", "list"},
    "api": None,
}
_PULLS_MERGE = re.compile(r"pulls[^ ]*merge", re.I)
_BRANCH_MERGE = re.compile(r"repos/[^ ]*/merges", re.I)
_MUTATION = re.compile(r"mergePullRequest|enablePullRequestAutoMerge", re.I)
_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")
_DATA_FROM_FILE = re.compile(r"(^@|=@)")


def _gh_nested(rest):
    """The word after `gh <sub>`: the first that is not an option or the value of -R/--repo."""
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("-R", "--repo"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def _check_gh(argv):
    if len(argv) < 2:
        raise Refused("gh without a subcommand", "nothing to check")
    sub = argv[1]
    if sub == "--version":
        return
    if sub not in GH_SUBS:
        raise Refused("gh subcommand not on boss-run's list", "%s (allowed: %s)" % (sub, " ".join(sorted(GH_SUBS))))
    if sub == "api":
        flat = " ".join(argv)
        for rx, what in ((_PULLS_MERGE, "a pull request merge endpoint"), (_BRANCH_MERGE, "the branch merge endpoint"),
                         (_MUTATION, "a merge mutation")):
            if rx.search(flat):
                raise Refused("PR merge outside boss_merge", "%s in the arguments: %s" % (what, flat))
        if any(_PERCENT.search(a) for a in argv[2:]):
            raise Refused("merge rule cannot see through", "a percent-encoded path or query in an API call")
        if "graphql" in flat:
            for a in argv[2:]:
                if a == "--input" or _DATA_FROM_FILE.search(a):
                    raise Refused("merge rule cannot see through", "a GraphQL body read from a file (%s)" % a)
        return
    nested = _gh_nested(argv[2:])
    if nested == "merge":
        raise Refused("PR merge outside boss_merge", "gh %s merge" % sub)
    if nested not in GH_SUBS[sub]:
        raise Refused("gh subcommand not on boss-run's list", "gh %s %s (allowed: %s)"
                      % (sub, nested, " ".join(sorted(GH_SUBS[sub]))))


# -------------------------------------------------------------------- git ----
GIT_SUBS = {"worktree", "push", "merge", "commit", "branch", "pull", "add", "restore", "fetch", "status",
            "log", "diff", "show", "rev-parse"}
# Long options that make git run a program or write where it is told. Git accepts any unambiguous
# prefix of a long option, so a word of three characters or more that is a prefix of one of these
# is refused too (`--exe`, `--upload-pa=`).
_GIT_PROGRAM_OPTIONS = ("--upload-pack", "--receive-pack", "--exec", "--exec-path", "--ext-cmd", "--strategy",
                        "--open-files-in-pager", "--output")


def _check_git(argv):
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] == "-C" and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            i += 2
        elif argv[i] == "--no-pager":
            i += 1
        else:
            raise Refused("git option before the subcommand not on boss-run's list",
                          "%s (only -C <dir> and --no-pager; -c and --config-env run programs)" % argv[i])
    if i >= len(argv):
        raise Refused("git without a subcommand", "nothing to check")
    sub, rest = argv[i], argv[i + 1:]
    if sub not in GIT_SUBS:
        raise Refused("git subcommand not on boss-run's list", "%s (allowed: %s)" % (sub, " ".join(sorted(GIT_SUBS))))
    for a in rest:
        if a == "--":
            break
        if "ext::" in a:
            raise Refused("git transport that runs a program", a)
        if a == "-c" or a.startswith("-c") and "=" in a or a == "--config" or a.startswith("--config="):
            raise Refused("git option that sets config", "%s (a config key can run a program)" % a)
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if len(name) >= 3 and any(p.startswith(name) for p in _GIT_PROGRAM_OPTIONS):
                raise Refused("git option that can run a program", a)
        elif sub == "merge" and re.match(r"^-[A-Za-z]*s", a):
            raise Refused("git option that can run a program", "%s (a merge strategy runs a git-merge-<name> helper)" % a)


# ------------------------------------------------------------------- others ----
_SYSTEMCTL_FLAGS = {"--user", "--system", "--no-pager", "--no-legend", "-l", "--full", "--no-ask-password"}
_PROTECTED_PATH = re.compile(
    r"(^|/)(\.git|\.ssh|\.gnupg|\.bashrc|\.bash_profile|\.bash_login|\.profile|\.zshrc|\.zprofile|\.zshenv|\.gitconfig|"
    r"authorized_keys|boss-run-trusted-path|boss-hard-rules\.tsv|\.githooks|hooks)(/|$)"
    r"|(^|/)\.config/(git|gh|systemd)(/|$)|(^|/)\.local/share/gh(/|$)", re.I)


def _check_systemctl(argv):
    i = 1
    while i < len(argv) and argv[i] in _SYSTEMCTL_FLAGS:
        i += 1
    if i >= len(argv) or argv[i] not in ("status", "show"):
        raise Refused("systemctl subcommand not on boss-run's list",
                      "only status and show; a restart goes to the owner (a restart changes a service, "
                      "and none of the 714 logged commands used systemctl)")
    for a in argv[i + 1:]:
        if a in ("-H", "--host", "-M", "--machine") or a.startswith(("--host=", "--machine=", "-H", "-M")):
            raise Refused("systemctl option that reaches another machine", a)


def _check_file_program(argv):
    for a in argv[1:]:
        if not a.startswith("-") and _PROTECTED_PATH.search(a):
            raise Refused("write to a place that runs code or holds trust",
                          "%s (.git, hooks, shell startup files, ssh keys, gh/git/systemd config, boss-run's own rule files)" % a)


def _check_rg(argv):
    for a in argv[1:]:
        if re.match(r"^--(pre|hostname-bin)", a):
            raise Refused("rg option that runs a program", a)


# ---------------------------------------------------------------------- plan ----
def check_argv(argv):
    """Raises Refused unless the argument list is one boss-run may show a reviewer. Runs nothing."""
    if not argv or argv[0] == "":
        raise Refused("no command", "the argument list is empty")
    name = argv[0]
    if not BARE_NAME.fullmatch(name):
        raise Refused("program given by path or by an odd name",
                      "%s: give the program's bare name; boss-run resolves it from its trusted directories" % name)
    if name not in PROGRAMS:
        raise Refused(NOT_ON_LIST, "%s (on the list: %s). A script or an interpreter goes to a worker."
                      % (name, " ".join(sorted(PROGRAMS))))
    if name == "gh":
        _check_gh(argv)
    elif name == "git":
        _check_git(argv)
    elif name == "systemctl":
        _check_systemctl(argv)
    elif name == "rg":
        _check_rg(argv)
    elif name in FILE_PROGRAMS:
        _check_file_program(argv)


def _git_flat(argv):
    """The joined text the hard rules read: git without -C <dir>, so `git -C x push origin main`
    is `git push origin main`."""
    i = 1
    while i < len(argv) and argv[i] in ("-C", "--no-pager"):
        i += 2 if argv[i] == "-C" else 1
    return " ".join(["git", *argv[i:]])


def plan(args, *, single):
    """`args` is what follows `--`. One argument with `single` is a shell-looking string, and is
    taken only when literal; otherwise the arguments are the argument list as they are."""
    argv = split_literal(args[0]) if single and len(args) == 1 else list(args)
    for a in argv:
        try:
            a.encode("utf-8")
        except UnicodeEncodeError:
            raise Refused("argument that is not text",
                          "bytes that are not valid UTF-8 cannot be shown to a reviewer as they run")
    check_argv(argv)
    return Plan(argv, _git_flat(argv) if argv[0] == "git" else " ".join(argv))


def prepare(argv, config_dir, cwd, env=None):
    """After the APPROVE: the list that runs, argv[0] resolved to an absolute path in a trusted
    directory. For gh, `gh alias list` (on the binary that will run) must not name the subcommand."""
    exe = resolve(argv[0], config_dir)
    if argv[0] == "gh" and len(argv) > 1 and argv[1] != "--version":
        try:
            r = subprocess.run([exe, "alias", "list"], capture_output=True, text=True, timeout=20,
                               env=dict(os.environ if env is None else env), cwd=cwd, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise Refused("gh alias cannot be read", "`gh alias list` did not answer: %s" % e)
        if r.returncode != 0:
            raise Refused("gh alias cannot be read", "`gh alias list` exited %d: %s" % (r.returncode, r.stderr.strip()[:120]))
        if argv[1] in {m.group(1) for m in re.finditer(r"^([^\s:]+):", r.stdout, re.M)}:
            raise Refused("gh alias", "%s is an alias in gh's config" % argv[1])
    return [exe, *argv[1:]]


def main(argv):
    mode = "plan"
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    cwd, i = os.getcwd(), 0
    while i < len(argv) and argv[i] != "--":
        if argv[i] in ("--single", "--resolve"):
            mode = argv[i][2:]
        elif argv[i] == "--cwd" and i + 1 < len(argv):
            cwd = argv[i + 1]
            i += 1
        elif argv[i] == "--config-dir" and i + 1 < len(argv):
            config_dir = argv[i + 1]
            i += 1
        else:
            print("argv_gate: unknown argument %s" % argv[i], file=sys.stderr)
            return 2
        i += 1
    args = argv[i + 1:]
    try:
        if mode == "resolve":
            run = prepare(args, config_dir, cwd)
            print(json.dumps({"ok": True, "argv": args, "flat": " ".join(args), "display": shlex.join(args), "exec": run}))
            return 0
        p = plan(args, single=(mode == "single"))
    except Refused as e:
        print(json.dumps({"ok": False, "rule": e.name, "detail": e.detail}))
        return 1
    print(json.dumps({"ok": True, "argv": p.argv, "flat": p.flat, "display": p.display}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
