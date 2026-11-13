#!/usr/bin/env python3
"""argv_gate: boss-run runs only what it can see completely (codex-down ticket 53b).

boss-run used to hand the boss's text to `bash -lc` and try to prove the text harmless; a
reviewer, hard rules and a lexer (PR 148) all read the text and Codex found twelve ways for
shell syntax to hide a merge. This module turns that around. The command is an argument
list, executed directly with no shell, and the reviewer is shown exactly that list:

  1. A single-argument command is split into a list only when it is fully literal: plain
     words and quotes. Anything a shell would expand, join or redirect is refused.
  2. The program in argv[0] must not be one that runs another command or a code string.
  3. `gh` and `git` are refused when argv names one of their own aliases or extensions,
     read from the tool itself, and when they are asked to run a program.
  4. The hard rules (in boss-run) then match the list joined with single spaces.

Usage (as boss-run calls it): argv_gate.py [--single] [--cwd DIR] -- ARG...
Prints one JSON object. Exit 0: {ok:true, argv, flat, display}. Exit 1: {ok:false, rule, detail}.
Any other exit status or no JSON is no answer, and boss-run refuses.
"""
import json
import os
import re
import shlex
import shutil
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
    """What boss-run will execute: `argv`; `flat` for the hard rules; `display` for the reviewer."""

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


# ----------------------------------------------------------- programs refused ----
RUNS_OTHER = "program that runs another command"
HIDDEN_REQUEST = "program whose request or command the argument list does not show"

# Exact names (lowercase) and patterns of programs whose job is to run something else, or to
# run a code string, or to open a place where one can be typed.
_NAMES = set("""
bash sh zsh dash ksh mksh ash fish csh tcsh rbash rsh busybox toybox coproc
env eval exec command builtin xargs find time nice nohup timeout sudo su doas watch script parallel
setsid flock ionice taskset stdbuf chroot unshare nsenter runuser pkexec sg newgrp chrt
systemd-run systemd-cat dbus-launch dbus-run-session xvfb-run tsocks proxychains unbuffer rlwrap entr
tmux screen at batch crontab anacron
make cmake ninja just task gmake
perl ruby node nodejs deno bun bunx php lua luajit tclsh wish expect osascript java jshell
awk gawk mawk nawk sed ed ex vi vim nvim nano emacs less more most man view pico
ssh scp sftp mosh socat nc ncat netcat telnet
strace ltrace gdb lldb valgrind perf
claude codex gemini aider
curl wget http https xh tar rsync zip unzip 7z 7za cpio ar
npx npm pnpm yarn uv uvx pipx pip pip3 cargo go bc
""".split())
_PATTERNS = (re.compile(r"python[0-9.]*"), re.compile(r"pypy[0-9.]*"), re.compile(r"perl[0-9.]*"),
             re.compile(r"ruby[0-9.]*"), re.compile(r"php[0-9.]*"), re.compile(r"lua[0-9.]*"),
             re.compile(r"(gawk|mawk|nawk|ed|vi|vim|nvim)[-.0-9a-z]*"))


def _program_names(argv0, path):
    """The names argv[0] answers to: as written and as it resolves through links and PATH."""
    found = {os.path.basename(argv0).lower()}
    resolved = argv0 if os.path.isabs(argv0) else shutil.which(argv0, path=path)
    if resolved:
        found.add(os.path.basename(os.path.realpath(resolved)).lower())
    return found


_HIDES = set("curl wget http https xh tar rsync zip unzip 7z 7za cpio ar".split())


def _runs_other(name):
    return name in _NAMES or any(p.fullmatch(name) for p in _PATTERNS)


# ------------------------------------------------------------ the merge rule ----
# A merge through the API: the endpoint, the branch merge endpoint and the two GraphQL mutations,
# whatever the method. Only `gh api` is left that can send one (curl, wget and httpie are
# refused by name); the hard rule in boss-run reads the same text.
_PULLS_MERGE = re.compile(r"pulls[^ ]*merge", re.I)
_BRANCH_MERGE = re.compile(r"repos/[^ ]*/merges", re.I)
_MUTATION = re.compile(r"mergePullRequest|enablePullRequestAutoMerge", re.I)
_PERCENT = re.compile(r"%[0-9a-fA-F]{2}")
_DATA_FROM_FILE = re.compile(r"(^@|=@)")


def _check_api(argv, names):
    if "gh" not in names or len(argv) < 2 or argv[1] != "api":
        return
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


# ------------------------------------------------------------------------ gh ----
def _tool(argv0, args, env, cwd, what):
    """Runs the tool's own report and returns its stdout. Anything but a clean answer refuses."""
    try:
        r = subprocess.run([argv0, *args], capture_output=True, text=True, timeout=20, env=env,
                           cwd=cwd, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise Refused(what[0], "%s did not answer: %s" % (what[1], e))
    if r.returncode not in what[2]:
        raise Refused(what[0], "%s exited %d: %s" % (what[1], r.returncode, r.stderr.strip()[:120]))
    return r


_GH_FORBIDDEN_SUBS = {"codespace": "runs commands on a remote machine", "cs": "runs commands on a remote machine"}


def _check_gh(argv, path, env, cwd):
    if len(argv) < 2:
        raise Refused("gh without a subcommand", "nothing to check")
    sub = argv[1]
    if sub in ("--version", "--help", "-h", "help"):
        return
    if sub.startswith("-"):
        raise Refused("gh option before the subcommand", sub)
    if sub in _GH_FORBIDDEN_SUBS:
        raise Refused("gh " + sub, _GH_FORBIDDEN_SUBS[sub])
    gh = argv[0]
    # Names gh itself reports. A user alias or an extension may be `pr merge`; gh refuses ones
    # that shadow a built-in, so a name in neither list is gh's own command.
    out = _tool(gh, ["alias", "list"], env, cwd,
                ("gh alias cannot be read", "`gh alias list`", (0,))).stdout
    aliases = {m.group(1) for m in re.finditer(r"^([^\s:]+):", out, re.M)}
    if sub in aliases:
        raise Refused("gh alias", "%s is an alias in gh's config" % sub)
    if sub in ("extension", "ext"):
        if len(argv) > 2 and argv[2] in ("list", "ls", "search", "browse"):
            return
        raise Refused("gh extension", "installs or runs code the argument list does not show")
    out = _tool(gh, ["extension", "list"], env, cwd,
                ("gh extension cannot be read", "`gh extension list`", (0,))).stdout
    exts = set()
    for line in out.splitlines():
        tokens = line.split()
        exts.update(tokens[:2])
    if sub in exts:
        raise Refused("gh extension", "%s is an installed extension" % sub)


# ----------------------------------------------------------------------- git ----
_GIT_FLAGS = {"--no-pager", "--no-replace-objects", "--literal-pathspecs", "--glob-pathspecs",
              "--noglob-pathspecs", "--icase-pathspecs", "--no-optional-locks", "--bare", "--no-advice",
              "--version", "--help", "-P", "-h", "-v"}
_GIT_VALUE_OPTIONS = {"-C", "--git-dir", "--work-tree", "--namespace"}
_GIT_SUBS = {"difftool": "runs the configured diff tool", "mergetool": "runs the configured merge tool",
             "filter-branch": "runs shell snippets", "instaweb": "starts a web server",
             "web--browse": "starts a browser", "help": "starts man or a browser",
             "send-email": "runs a mail program", "daemon": "starts a server", "gui": "starts a program",
             "gitk": "starts a program", "citool": "starts a program", "credential": "runs a helper"}
_GIT_RUNS_PROGRAM_OPTION = re.compile(r"^--(exec|upload-pack|receive-pack|ext-cmd|editor|run|pager)\b", re.I)
_GIT_CONFIG_KEYS = re.compile(r"^(alias|core|pager|credential|include|includeif|filter|diff|merge|sequence|"
                              r"gpg|sendemail|url|submodule|difftool|mergetool|http|ssh|protocol|"
                              r"safe|transfer|receive|uploadpack|uploadarchive|gc|rebase|commit|"
                              r"interactive|web|browser|man|instaweb|mailcap|fsmonitor|trace2|"
                              r"maintenance|worktree|init)\.", re.I)


def _git_globals(argv):
    """(index of the subcommand or None, the directory -C chain, refused option or None)."""
    i, dirs = 1, []
    while i < len(argv):
        a = argv[i]
        if not a.startswith("-"):
            return i, dirs
        if a in _GIT_VALUE_OPTIONS:
            if i + 1 >= len(argv):
                raise Refused("git option without a value", a)
            if a == "-C":
                dirs.append(argv[i + 1])
            i += 2
            continue
        if a in _GIT_FLAGS or re.match(r"^--(git-dir|work-tree|namespace)=", a):
            i += 1
            continue
        raise Refused("git option that can run a program", "%s before the subcommand" % a)
    return None, dirs


def _check_git(argv, env, cwd):
    sub_at, _dirs = _git_globals(argv)
    if sub_at is None:
        return
    sub, rest = argv[sub_at], argv[sub_at + 1:]
    # The probe reads the aliases of the repository the command will use: every option before the
    # subcommand (-C, --git-dir, --work-tree, --namespace) is passed on.
    r = _tool(argv[0], [*argv[1:sub_at], "config", "--get-regexp", r"^alias\."], env, cwd,
              ("git alias cannot be read", "`git config --get-regexp`", (0, 1)))
    aliases = {line.split()[0][len("alias."):].lower() for line in r.stdout.splitlines() if line.strip()}
    if sub.lower() in aliases:
        raise Refused("git alias", "%s is an alias in git's config" % sub)
    if sub in _GIT_SUBS:
        raise Refused("git " + sub, _GIT_SUBS[sub])
    for a in rest:
        if _GIT_RUNS_PROGRAM_OPTION.match(a) or "ext::" in a:
            raise Refused("git option that runs a program", a)
    if sub == "rebase" and any(a in ("-x", "-i", "--interactive") or a.startswith("-x") for a in rest):
        raise Refused("git rebase that runs a program", "-x or -i")
    if sub == "bisect" and "run" in rest:
        raise Refused("git bisect run", "runs a program")
    if sub == "submodule" and "foreach" in rest:
        raise Refused("git submodule foreach", "runs a program in every submodule")
    if sub in ("clone", "ls-remote", "fetch", "pull") and ("-u" in rest and sub == "clone"):
        raise Refused("git clone -u", "names the upload-pack program")
    if sub == "config":
        for a in rest:
            if a in ("-e", "--edit"):
                raise Refused("git config --edit", "starts an editor")
            if _GIT_CONFIG_KEYS.match(a.lower().split("=", 1)[0]):
                raise Refused("git config of a key that can run a program", a)


def _git_flat(argv):
    """The joined text the hard rules read: git without the options before the subcommand."""
    try:
        at, _ = _git_globals(argv)
    except Refused:
        return " ".join(argv)
    return " ".join(["git", *argv[at:]]) if at else " ".join(argv)


# -------------------------------------------------------------- other options ----
_OPTION_RULES = {
    "rg": (re.compile(r"^--(pre|hostname-bin)\b"), "runs a program on every file"),
}


def _check_options(argv, names):
    for name in names:
        if name in _OPTION_RULES:
            rx, why = _OPTION_RULES[name]
            for a in argv[1:]:
                if rx.match(a):
                    raise Refused(RUNS_OTHER, "%s %s (%s)" % (name, a, why))


# ---------------------------------------------------------------------- plan ----
def check_argv(argv, cwd, path=None, env=None):
    """Raises Refused unless the argument list is one boss-run may show a reviewer."""
    if not argv or argv[0] == "":
        raise Refused("no command", "the argument list is empty")
    argv0 = argv[0]
    if "=" in argv0:
        raise Refused("command begins with an assignment", argv0)
    if "/" in argv0 and not os.path.isabs(argv0):
        raise Refused("relative program path", "%s runs a file the reviewer cannot read" % argv0)
    env = dict(os.environ if env is None else env)
    path = path if path is not None else env.get("PATH", os.defpath)
    names = _program_names(argv0, path)
    for name in sorted(names):
        if name in _HIDES:
            # curl reads .curlrc, -K files and expands {a,b}; wget -i reads URLs from a file; tar
            # -I, rsync -e and zip -T run programs. Their options hide what they do, in more ways than a
            # list can close (Codex, PR 150 round 1), so boss-run does not run them.
            raise Refused(HIDDEN_REQUEST, name)
        if _runs_other(name):
            raise Refused(RUNS_OTHER, name)
    _check_api(argv, names)
    _check_options(argv, names)


def probe_tools(argv, cwd, path=None, env=None):
    """Raises Refused when `gh` or `git` names one of its own aliases or extensions, or cannot say.

    Separate from check_argv because it runs the tool (`gh alias list`), and boss-run wants the
    hard rules to refuse first: a merge refused by its rule leaves no call on gh at all."""
    env = dict(os.environ if env is None else env)
    path = path if path is not None else env.get("PATH", os.defpath)
    argv0 = argv[0]
    names = _program_names(argv0, path)
    # A program that does not exist cannot run (exec answers 127), so there is nothing to ask it.
    found = argv0 if os.path.isabs(argv0) else shutil.which(argv0, path=path)
    if found is None or not os.access(found, os.X_OK):
        return
    argv = [found, *argv[1:]]
    if "gh" in names:
        _check_gh(argv, path, env, cwd)
    if "git" in names:
        _check_git(argv, env, cwd)


def plan(args, *, single, cwd, path=None, env=None, probe=True):
    """`args` is what follows `--`. One argument with `single` is a shell-looking string, and is
    taken only when literal; otherwise the arguments are the argument list as they are."""
    argv = split_literal(args[0]) if single and len(args) == 1 else list(args)
    if not argv:
        raise Refused("no command", "nothing to run")
    check_argv(argv, cwd, path=path, env=env)
    if probe:
        probe_tools(argv, cwd, path=path, env=env)
    names = _program_names(argv[0], path if path is not None else (env or os.environ).get("PATH", os.defpath))
    flat = _git_flat(argv) if "git" in names else " ".join(argv)
    return Plan(argv, flat)


def main(argv):
    single, probe_only, no_probe, cwd, i = False, False, False, os.getcwd(), 0
    while i < len(argv) and argv[i] != "--":
        if argv[i] == "--single":
            single = True
        elif argv[i] == "--no-probe":
            no_probe = True
        elif argv[i] == "--probe-only":
            probe_only = True
        elif argv[i] == "--cwd" and i + 1 < len(argv):
            cwd = argv[i + 1]
            i += 1
        else:
            print("argv_gate: unknown argument %s" % argv[i], file=sys.stderr)
            return 2
        i += 1
    args = argv[i + 1:]
    try:
        for a in args:
            try:
                a.encode("utf-8")
            except UnicodeEncodeError:
                raise Refused("argument that is not text", "bytes that are not valid UTF-8 cannot be shown to a reviewer as they run")
        if probe_only:
            probe_tools(args, cwd)
            print(json.dumps({"ok": True, "argv": args, "flat": " ".join(args), "display": shlex.join(args)}))
            return 0
        p = plan(args, single=single, cwd=cwd, probe=not no_probe)
    except Refused as e:
        print(json.dumps({"ok": False, "rule": e.name, "detail": e.detail}))
        return 1
    print(json.dumps({"ok": True, "argv": p.argv, "flat": p.flat, "display": p.display}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
