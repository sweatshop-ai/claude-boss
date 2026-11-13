#!/usr/bin/env python3
"""The shell-token half of boss-run's hard rule `PR merge outside boss_merge` (ticket 53).

boss-run's raw-text patterns see the characters the boss typed. The shell runs what is left
after it removes quotes, joins `g"h"`, expands `$(...)` and so on, so `"gh" pr merge 5` ran the
forbidden merge past a pattern that looked for `gh pr merge`. This module reads the command the
way the shell does, and refuses a merge it can see and a command it cannot see through.

    echo 'gh pr "merge" 5' | python3 merge_shape.py     # prints "name<TAB>detail", exit 1
    scan(cmd) -> None | (name, detail)

Exit 0: nothing found. Exit 1: a finding, printed as `name<TAB>detail`. Any other exit (a crash, a
signal, no python3) is not an answer, and boss-run takes that as a refusal too.

What it covers: POSIX/bash word syntax (quotes, backslash, `$'..'`, the substitutions, `;` `&` `|`
`(` `)` newline, redirections, heredocs and here-strings, assignments, reserved words) and what runs
other commands (wrappers, `eval`, `sh -c`, `find -exec`, `xargs`). It does not read other
languages: `python3 -c`, `perl -e`, `ssh host '...'` can still spell a merge, and stay with the
reviewer and the owner's own rules.
"""
import os
import re
import sys

MERGE = "PR merge outside boss_merge"
OPAQUE = "merge rule cannot see through"

MAX_DEPTH = 8   # nested $( ), sh -c, eval; deeper is refused rather than followed

SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "fish", "csh", "tcsh"}
# Run another command given in their own arguments: the command is found among the later words.
WRAPPERS = {"env", "command", "exec", "builtin", "nohup", "nice", "time", "coproc", "timeout", "sudo", "doas",
            "stdbuf", "setsid", "ionice", "watch", "unbuffer", "chronic", "script", "flock", "su", "runuser"}
# Feed the command more arguments from stdin, which is not in the text: gh behind them is refused.
STDIN_FEEDERS = {"xargs", "parallel"}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}
SKIPPED_RESERVED = {"if", "then", "else", "elif", "while", "until", "do", "!", "{", "}"}
# Environment a command may set to change what runs or where gh looks: an unseen startup file for
# bash, another gh config, another home.
ENV_TRICKS = re.compile(r"^(BASH_ENV|ENV|GH_CONFIG_DIR|XDG_CONFIG_HOME|XDG_DATA_HOME|HOME)=")
# Text that writes gh's own config, where aliases live, or its extensions.
GH_FILES = re.compile(r"gh/(config|hosts)\.yml|gh/extensions|\.config/gh\b")
API_VALUE_LONG = {"--method", "--field", "--raw-field", "--header", "--jq", "--template", "--input",
                  "--hostname", "--cache", "--preview"}
API_VALUE_SHORT = {"-X", "-F", "-f", "-H", "-q", "-t", "-p"}
API_FIELD = {"-f", "-F", "--field", "--raw-field"}
GRAPHQL_MERGE = re.compile(r"mergePullRequest|enablePullRequestAutoMerge", re.I)
MERGE_PATH = re.compile(r"pulls/[^/]+/merge")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
BRACE = re.compile(r"\{[^{}]*(,|\.\.)[^{}]*\}")
WS = " \t\r"
OP_CHARS = ";&|()<>\n"


class Finding(Exception):
    def __init__(self, name, detail):
        super().__init__(name, detail)
        self.name, self.detail = name, detail


def opaque(detail):
    return Finding(OPAQUE, detail)


class Word:
    __slots__ = ("val", "exp", "glob", "subs", "quoted")

    def __init__(self):
        self.val, self.exp, self.glob, self.subs, self.quoted = "", False, False, [], False


class Cmd:
    def __init__(self):
        self.words, self.subs, self.bodies, self.here, self.targets = [], [], [], None, []


# ------------------------------------------------------------------ lexer ----
def _skip_single(src, i):
    j = src.find("'", i)
    if j < 0:
        raise opaque("an unclosed single quote")
    return j


def _dq(src, i, closing):
    """Reads a double-quoted run from i. Returns (text, exp, subs, next index); `closing` False
    reads a heredoc body (to the end of src, `"` is an ordinary character)."""
    out, exp, subs = [], False, []
    n = len(src)
    while True:
        if i >= n:
            if closing:
                raise opaque("an unclosed double quote")
            return "".join(out), exp, subs, i
        c = src[i]
        if closing and c == '"':
            return "".join(out), exp, subs, i + 1
        if c == "\\" and i + 1 < n:
            nxt = src[i + 1]
            if nxt == "\n":
                i += 2
            elif nxt in '$`"\\':
                out.append(nxt); i += 2
            else:
                out.append("\\" + nxt); i += 2
        elif c == "$" and src.startswith("$(", i):
            end = _match(src, i + 2, "(", ")")
            subs.append(src[i + 2:end]); exp = True
            out.append(src[i:end + 1]); i = end + 1
        elif c == "$" and src.startswith("${", i):
            end = _match(src, i + 2, "{", "}")
            subs += _dq(src[i + 2:end], 0, False)[2]; exp = True
            out.append(src[i:end + 1]); i = end + 1
        elif c == "`":
            j = _backtick(src, i)
            subs.append(src[i + 1:j].replace("\\`", "`").replace("\\\\", "\\")); exp = True
            out.append(src[i:j + 1]); i = j + 1
        elif c == "$" and i + 1 < n and (src[i + 1].isalnum() or src[i + 1] in "_@*#?!$-"):
            exp = True
            out.append(c); i += 1
        else:
            out.append(c); i += 1


def _backtick(src, i):
    j = i + 1
    while j < len(src):
        if src[j] == "\\":
            j += 2
            continue
        if src[j] == "`":
            return j
        j += 1
    raise opaque("an unclosed backtick")


def _match(src, i, open_c, close_c):
    """Index of the bracket that closes the one opened just before i, quotes and nesting respected."""
    depth, n = 1, len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            i = _skip_single(src, i + 1) + 1
            continue
        if c == '"':
            i = _dq(src, i + 1, True)[3]
            continue
        if c == "`":
            i = _backtick(src, i) + 1
            continue
        if c == "$" and i + 1 < n and src[i + 1] == open_c:
            depth += 1; i += 2
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise opaque("an unclosed $( or ${")


_ANSI = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
         "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi_c(src, i):
    out, n = [], len(src)
    while i < n:
        c = src[i]
        if c == "'":
            return "".join(out), i + 1
        if c == "\\" and i + 1 < n:
            nxt = src[i + 1]
            m = re.match(r"x[0-9a-fA-F]{1,2}|[0-7]{1,3}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}", src[i + 1:])
            if m:
                s = m.group(0)
                code = int(s[1:], 16) if s[0] in "xuU" else int(s, 8)
                out.append(chr(code) if code else "")
                i += 1 + len(s)
            else:
                out.append(_ANSI.get(nxt, "\\" + nxt)); i += 2
        else:
            out.append(c); i += 1
    raise opaque("an unclosed $'...'")


class Lexer:
    def __init__(self, src):
        self.src, self.i = src, 0
        self.pending = []   # (delimiter, strip tabs, quoted, body list) waiting for the next newline

    def tokens(self):
        src, n = self.src, len(self.src)
        toks = []
        while self.i < n:
            c = src[self.i]
            if c in WS:
                self.i += 1
            elif c == "\\" and src.startswith("\\\n", self.i):
                self.i += 2
            elif c == "#":
                j = src.find("\n", self.i)
                self.i = n if j < 0 else j
            elif c == "\n":
                toks.append(("op", "\n")); self.i += 1
                self.read_bodies()
            elif c in ";|()" or (c == "&" and not src.startswith("&>", self.i)):
                two = src[self.i:self.i + 2]
                op = two if two in (";;", ";&", "&&", "||", "|&") else c
                toks.append(("op", op)); self.i += len(op)
            elif c in "<>" or src.startswith("&>", self.i):
                toks.append(self.redirect())
            else:
                w = self.word()
                if w.val.isdigit() and not w.quoted and self.i < n and src[self.i] in "<>":
                    continue     # a file descriptor in front of a redirection: `2>&1`
                toks.append(("word", w))
        return toks

    def read_bodies(self):
        src, n = self.src, len(self.src)
        for delim, strip, _, body in self.pending:
            lines = []
            while True:
                if self.i >= n:
                    raise opaque("a heredoc that is never closed")
                j = src.find("\n", self.i)
                line = src[self.i:n if j < 0 else j]
                self.i = n if j < 0 else j + 1
                if (line.lstrip("\t") if strip else line) == delim:
                    break
                lines.append(line)
            body.append("\n".join(lines) + ("\n" if lines else ""))
        self.pending = []

    def redirect(self):
        src = self.src
        for op in ("&>>", "<<<", "<<-", "&>", "<<", "<&", "<>", ">>", ">&", ">|", "<(", ">(", "<", ">"):
            if src.startswith(op, self.i):
                break
        if op in ("<(", ">("):
            w = Word()
            end = _match(src, self.i + 2, "(", ")")
            w.val, w.exp = src[self.i:end + 1], True
            w.subs.append(src[self.i + 2:end])
            self.i = end + 1
            return ("word", w)
        self.i += len(op)
        while self.i < len(src) and src[self.i] in WS:
            self.i += 1
        if self.i >= len(src) or src[self.i] in "\n;|&()<>":
            raise opaque("a redirection with no target")
        target = self.word()
        body = None
        if op in ("<<", "<<-"):
            body = []
            self.pending.append((target.val, op == "<<-", target.quoted, body))
        return ("redir", op, target, body)

    def word(self):
        src, n = self.src, len(self.src)
        w = Word()
        out, unq = [], []
        while self.i < n:
            c = src[self.i]
            if c in WS or c in OP_CHARS:
                if c in "<>" and src.startswith(c + "(", self.i) and not out:
                    pass
                break
            if c == "\\":
                if self.i + 1 >= n:
                    out.append("\\"); unq.append("\\"); self.i += 1
                elif src[self.i + 1] == "\n":
                    self.i += 2
                else:
                    out.append(src[self.i + 1]); unq.append("\0"); w.quoted = True; self.i += 2
            elif c == "'":
                j = _skip_single(src, self.i + 1)
                out.append(src[self.i + 1:j]); unq.append("\0"); w.quoted = True; self.i = j + 1
            elif c == '"' or src.startswith('$"', self.i):
                start = self.i + (2 if c == "$" else 1)
                text, exp, subs, self.i = _dq(src, start, True)
                out.append(text); unq.append("\0"); w.quoted = True
                w.exp |= exp; w.subs += subs
            elif src.startswith("$'", self.i):
                text, self.i = _ansi_c(src, self.i + 2)
                out.append(text); unq.append("\0"); w.quoted = True
            elif src.startswith("$(", self.i):
                end = _match(src, self.i + 2, "(", ")")
                w.subs.append(src[self.i + 2:end]); w.exp = True
                out.append(src[self.i:end + 1]); unq.append("\0"); self.i = end + 1
            elif src.startswith("${", self.i):
                end = _match(src, self.i + 2, "{", "}")
                w.subs += _dq(src[self.i + 2:end], 0, False)[2]; w.exp = True
                out.append(src[self.i:end + 1]); unq.append("\0"); self.i = end + 1
            elif c == "`":
                j = _backtick(src, self.i)
                w.subs.append(src[self.i + 1:j].replace("\\`", "`").replace("\\\\", "\\")); w.exp = True
                out.append(src[self.i:j + 1]); unq.append("\0"); self.i = j + 1
            elif c == "$" and self.i + 1 < n and (src[self.i + 1].isalnum() or src[self.i + 1] in "_@*#?!$-"):
                w.exp = True
                j = self.i + 1
                if src[j].isalnum() or src[j] == "_":
                    while j < n and (src[j].isalnum() or src[j] == "_"):
                        j += 1
                else:
                    j += 1
                out.append(src[self.i:j]); unq.append("\0"); self.i = j
            else:
                if c in "*?[":
                    w.glob = True
                out.append(c); unq.append(c); self.i += 1
        w.val = "".join(out)
        if BRACE.search("".join(unq)):
            w.glob = True
        return w


def parse(src):
    lx = Lexer(src)
    toks = lx.tokens()
    cmds, cur = [], Cmd()
    for t in toks:
        if t[0] == "word":
            cur.words.append(t[1]); cur.subs += t[1].subs
        elif t[0] == "redir":
            _, op, target, body = t
            cur.subs += target.subs
            cur.targets.append(target)
            if op == "<<<":
                cur.here = None if target.exp else target.val
            elif body is not None:
                cur.bodies.append((body, target.quoted))
        elif t[1] in ("&&", "||", ";", ";;", ";&", "&", "|", "|&", "\n", "(", ")"):
            if cur.words or cur.subs or cur.bodies:
                cmds.append(cur)
            cur = Cmd()
    if cur.words or cur.subs or cur.bodies:
        cmds.append(cur)
    return cmds


# ---------------------------------------------------------------- checks ----
def _shown(words):
    return " ".join(w.val for w in words)[:120]


def _base(w):
    return os.path.basename(w.val)


def scan_src(src, depth):
    if depth > MAX_DEPTH:
        raise opaque("commands nested more than %d deep" % MAX_DEPTH)
    for cmd in parse(src):
        for sub in cmd.subs:
            scan_src(sub, depth + 1)
        heredoc = None
        for body, quoted in cmd.bodies:
            text = body[0] if body else ""
            if not quoted:
                for sub in _dq(text, 0, False)[2]:
                    scan_src(sub, depth + 1)
            heredoc = text
        check_cmd(cmd, heredoc if heredoc is not None else cmd.here, depth)


def check_cmd(cmd, stdin, depth):
    words = list(cmd.words)
    i = 0
    while i < len(words) and (ASSIGN.match(words[i].val) or (words[i].val in SKIPPED_RESERVED and not words[i].quoted)):
        i += 1
    words = words[i:]
    for w in cmd.words + cmd.targets:
        if ENV_TRICKS.match(w.val):
            raise opaque("%s changes what runs or where gh looks: %s" % (w.val.partition("=")[0], _shown(cmd.words)))
        if GH_FILES.search(w.val):
            raise opaque("a command that touches gh's own config or extensions: %s" % _shown(cmd.words))
    # A word of several tokens may be a command line handed to a program that runs it (`env -S '...'`,
    # `flock -c '...'`, `script -c '...'`, `ssh host '...'`): read it as one, and keep only a merge.
    for w in cmd.words:
        text = w.val.partition("=")[2] if w.val.startswith("-") else w.val     # `--split-string='...'`
        if re.search(r"\s", text) and not w.exp:
            try:
                scan_src(text, depth + 1)
            except Finding as f:
                if f.name == MERGE:
                    raise
    if not words:
        return
    head = words[0]
    if head.exp or head.glob:
        raise opaque("the command name is built at run time: %s" % _shown(words))
    dispatch(words, stdin, depth)
    # `echo gh pr merge`, `git ... -- gh pr merge`: a literal gh in any later word is read as a command
    # (only a merge it finds counts: `command -v gh codex` is a lookup, not a gh call)
    for j in range(1, len(words)):
        if not words[j].exp and _base(words[j]) == "gh":
            try:
                check_gh(words[j + 1:], words[j].val)
            except Finding as f:
                if f.name == MERGE:
                    raise


def dispatch(words, stdin, depth):
    """words[0] is a command position. True when it was a wrapper's target and has been handled."""
    base = _base(words[0])
    if base == "gh":
        check_gh(words[1:], words[0].val)
    elif base in SHELLS:
        check_shell(words, stdin, depth)
    elif base == "eval":
        check_eval(words[1:], depth)
    elif base in ("source", "."):
        raise opaque("sourcing a file the rule cannot read: %s" % _shown(words))
    elif base in WRAPPERS or base in STDIN_FEEDERS or base == "find":
        check_wrapper(words, stdin, depth)


def check_eval(args, depth):
    for w in args:
        if w.exp or w.glob:
            raise opaque("eval of text built at run time: %s" % _shown(args))
    scan_src(" ".join(w.val for w in args), depth + 1)


def check_shell(words, stdin, depth):
    i, n, c_seen = 1, len(words), False
    while i < n:
        s = words[i].val
        if s == "--":
            i += 1
            break
        if s in ("--rcfile", "--init-file") or s.startswith(("--rcfile=", "--init-file=")):
            raise opaque("a shell started with a startup file the rule cannot read: %s" % _shown(words))
        if s in ("-o", "+o", "-O", "+O"):
            i += 2
            continue
        if s.startswith("-") and len(s) > 1:
            if not s.startswith("--") and "c" in s[1:]:
                c_seen = True
            i += 1
            continue
        break
    if c_seen:
        if i >= n:
            raise opaque("a shell -c with no script")
        script = words[i]
        if script.exp or script.glob:
            raise opaque("shell -c of text built at run time: %s" % _shown(words))
        scan_src(script.val, depth + 1)
        return
    if i >= n and stdin is not None:
        scan_src(stdin, depth + 1)
        return
    raise opaque("a shell that reads a script from a file or from stdin: %s" % _shown(words))


def check_wrapper(words, stdin, depth):
    wrapper = _base(words[0])
    if wrapper in ("command", "builtin") and len(words) > 1 and words[1].val in ("-v", "-V"):
        return      # a lookup, nothing runs
    armed = wrapper != "find"
    for j in range(1, len(words)):
        w = words[j]
        if wrapper == "find":
            if w.val in (";", "+") and armed:
                armed = False
            if w.val in FIND_EXEC:
                armed = True
                continue
        if not armed:
            continue
        if w.exp or w.glob:
            if w.val.startswith("-") or ASSIGN.match(w.val):
                continue
            raise opaque("%s runs a command built at run time: %s" % (wrapper, _shown(words)))
        base = _base(w)
        if base == "gh" or base in SHELLS or base == "eval" or base in ("source", "."):
            if wrapper in STDIN_FEEDERS:
                raise opaque("%s feeds arguments from stdin to %s: %s" % (wrapper, base, _shown(words)))
            dispatch(words[j:], stdin, depth)
            return


def _gh_positionals(args, want):
    """The first `want` words of gh's command line that are not options, with the index after them.
    -R/--repo take the next word whatever it is."""
    pos, i = [], 0
    while i < len(args) and len(pos) < want:
        w = args[i]
        s = w.val
        if s in ("-R", "--repo"):
            i += 2
        elif s.startswith("-") and not w.glob:
            i += 1
        elif w.exp or w.glob:
            raise opaque("a gh subcommand built at run time: %s" % s)
        else:
            pos.append(s); i += 1
    return pos, i


def _gh_dirs():
    home = os.path.expanduser("~")
    conf = os.environ.get("GH_CONFIG_DIR") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "gh")
    data = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "gh", "extensions")
    return conf, data


def _gh_alias(name):
    """The expansion of gh alias `name` in the installed gh's config, or None. Anything the small
    reader cannot be sure of is a Finding."""
    conf, _ = _gh_dirs()
    path = os.path.join(conf, "config.yml")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return None
    except OSError:
        raise opaque("gh's config cannot be read, so an alias for %s cannot be ruled out" % name)
    in_aliases = False
    for line in lines:
        if re.match(r"^aliases:\s*$", line):
            in_aliases = True
            continue
        if in_aliases and line and not line[0].isspace():
            break
        m = in_aliases and re.match(r"^\s+(\S+?):\s*(.*)$", line)
        if m and m.group(1).strip("'\"") == name:
            val = m.group(2).strip()
            if not val or val[0] in "|>&*[{":
                raise opaque("gh alias %s is written in a form the rule cannot read" % name)
            if val[0] in "'\"" and val[-1] == val[0] and len(val) > 1:
                val = val[1:-1].replace("''", "'") if val[0] == "'" else val[1:-1]
            return val
    return None


def check_gh(args, gh):
    pos, i = _gh_positionals(args, 1)
    if not pos:
        return
    p0 = pos[0]
    if p0 in ("pr", "alias", "extension"):
        pos, _ = _gh_positionals(args, 2)
        p1 = pos[1] if len(pos) > 1 else None
        if p0 == "pr" and p1 == "merge":
            raise Finding(MERGE, "gh pr merge, as the shell reads it: %s %s" % (gh, _shown(args)))
        if p0 == "alias" and p1 in ("set", "import"):
            raise opaque("gh alias %s defines a command the rule cannot read: %s" % (p1, _shown(args)))
        if p0 == "extension" and p1 not in ("list", "ls", "search", "browse", None):
            raise opaque("gh extension %s installs or runs code the rule cannot read: %s" % (p1, _shown(args)))
    elif p0 == "api":
        _, k = _gh_positionals(args, 1)
        check_api(args[k:], gh, args)
    else:
        # not one of the commands above: a user's alias or an extension may be a merge, and gh
        # keeps both where this can look (an alias in its config, an extension as a directory)
        expansion = _gh_alias(p0)
        if expansion is not None:
            if expansion.startswith("!"):
                scan_src(expansion[1:], MAX_DEPTH - 1)
            else:
                words = [t[1] for t in Lexer(expansion).tokens() if t[0] == "word"]
                check_gh(words + args[i:], gh)
        _, data = _gh_dirs()
        if os.path.isdir(os.path.join(data, "gh-" + p0)):
            raise opaque("gh %s is an extension, whose code the rule cannot read" % p0)


def check_api(rest, gh, args):
    method = endpoint = None
    method_word = None
    fields = False
    queries = []
    i, n = 0, len(rest)
    while i < n:
        w = rest[i]
        s = w.val
        name, val_word, val = None, None, None
        if s.startswith("--") and len(s) > 2:
            nm, eq, v = s.partition("=")
            if nm in API_VALUE_LONG:
                name = nm
                if eq:
                    val_word, val = w, v
                else:
                    val_word = rest[i + 1] if i + 1 < n else None
                    val = val_word.val if val_word else ""
                    i += 1
        elif s.startswith("-") and len(s) > 1 and s[:2] in API_VALUE_SHORT:
            name = s[:2]
            if len(s) > 2:
                val_word, val = w, s[2:].lstrip("=")
            else:
                val_word = rest[i + 1] if i + 1 < n else None
                val = val_word.val if val_word else ""
                i += 1
        elif not s.startswith("-") and endpoint is None:
            endpoint = w
        i += 1
        if name in ("-X", "--method"):
            method, method_word = val.upper(), val_word
        elif name in API_FIELD:
            fields = True
            key, _, fval = val.partition("=")
            if key == "query":
                queries.append((val_word, fval))
        elif name == "--input":
            fields = True
            queries.append((None, None))
    ep = endpoint.val if endpoint else ""
    if method_word is not None and (method_word.exp or method_word.glob):
        raise opaque("gh api with a method built at run time: %s" % _shown(args))
    writes = (method is not None and method != "GET") or (method is None and fields)
    if endpoint is not None and ep.strip("/") == "graphql":
        for vw, fval in queries:
            if vw is None or vw.exp or vw.glob or fval.startswith("@"):
                raise opaque("gh api graphql with a query read from a file or built at run time: %s" % _shown(args))
        if any(GRAPHQL_MERGE.search(w.val) for w in rest):
            raise Finding(MERGE, "a GraphQL merge mutation, as the shell reads it: %s %s" % (gh, _shown(args)))
        return
    if writes and MERGE_PATH.search(ep):
        raise Finding(MERGE, "gh api write to a pull request's merge endpoint: %s %s" % (gh, _shown(args)))
    if endpoint is not None and (endpoint.exp or endpoint.glob) and method == "PUT":
        raise opaque("gh api -X PUT to an endpoint built at run time: %s" % _shown(args))
    if endpoint is not None and (endpoint.exp or endpoint.glob) and any(GRAPHQL_MERGE.search(w.val) for w in rest):
        raise Finding(MERGE, "a GraphQL merge mutation, as the shell reads it: %s %s" % (gh, _shown(args)))


def scan(cmd):
    """None when nothing was found, else (name, detail)."""
    try:
        scan_src(cmd, 0)
    except Finding as f:
        return f.name, f.detail
    except RecursionError:
        return OPAQUE, "the command is nested too deep to read"
    return None


def main():
    cmd = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
    found = scan(cmd)
    if found is None:
        return 0
    sys.stdout.write("%s\t%s\n" % (found[0], found[1].replace("\n", " ").replace("\t", " ")))
    return 1


if __name__ == "__main__":
    sys.exit(main())
