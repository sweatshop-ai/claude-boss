#!/usr/bin/env python3
"""The reviewer chain: Codex first, an optional fallback model next, else nobody.

One place decides which reviewer answers, so `boss-run`, `boss-goal review` and
`boss-goal premortem` cannot drift apart. Standard library only.

    run_chain(prompt, words=..., fallback=OPUS) -> Result
    run_chain(prompt, lines=Shape("RISK", min=8), fallback=FABLE) -> Result
    claude_argv(fallback, prompt) -> argv        the fallback's `claude` call, built in this one place
    fallback_flags(fallback) -> flags            the command-line flags that rebuild a Fallback

What makes an answer usable is one of two rules: a `VERDICT:` line in `words`, or
`lines.min` lines under `lines.label`. The fallbacks a caller names by preset
(`PRESETS`: opus, fable) are the only place the model ids are written.

`Result.reviewer` is "codex", the fallback's name, or "none". Every attempt is
kept on `Result.attempts` with a reason from a closed set:

    answered   a usable VERDICT line (or enough labelled lines) was in the answer
    absent     the reviewer is not on PATH, or only on entries a checkout could supply
    timeout    it ran past its timeout and gave no usable verdict
    error      it exited non-zero (or could not be started) and gave none
    noverdict  it exited 0 and its answer has no usable VERDICT line
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


class Words(tuple):
    """A verdict vocabulary: the words, and the rule that matches them.

    "prefix": the word must follow `VERDICT:` and may run on (APPROVED is APPROVE),
    as boss-run has always matched. "token": the word must be a whole token, longest
    word first (NO-GO is never GO, GOOD is no verdict). Left unsaid, the rule is
    "prefix" for APPROVE/REJECT, wherever those two words are named (a plain tuple
    of them, `--words APPROVE,REJECT`), and "token" for any other vocabulary.
    """
    match: str

    def __new__(cls, words, match=None):
        if match not in (None, "prefix", "token"):
            raise ValueError("match must be 'prefix' or 'token', not %r" % (match,))
        self = super().__new__(cls, (w.upper() for w in words))
        self.match = match or _default_rule(self)
        return self


def _default_rule(words) -> str:
    return "prefix" if {w.upper() for w in words} == {"APPROVE", "REJECT"} else "token"


APPROVE_REJECT = Words(("APPROVE", "REJECT"), match="prefix")
GO_NOGO = Words(("GO", "NO-GO"), match="token")


CODEX_FAILURES = frozenset(("absent", "timeout", "error", "noverdict"))
DEFAULT_TIMEOUT = 120   # seconds, per reviewer
RESERVED_NAMES = frozenset(("codex", "none"))   # a Result already says these; a fallback cannot be one


@dataclass(frozen=True)
class Fallback:
    name: str
    model: str
    timeout: int | None = None     # None: twice the Codex timeout, as every caller gave it
    allowed_tools: tuple[str, ...] | None = None
    when: tuple[str, ...] = ("absent", "timeout", "error", "noverdict")
    extra_args: tuple[str, ...] = ()     # more `claude` flags, put ahead of `-p` (see claude_argv)
    env_unset: tuple[str, ...] = ()      # environment variables the `claude` child does not inherit

    def __post_init__(self):
        if not self.name.strip() or self.name.strip().lower() in RESERVED_NAMES:
            raise ValueError("a fallback cannot be named %r: Result.reviewer already uses %s"
                             % (self.name, " and ".join(sorted(RESERVED_NAMES))))
        if self.allowed_tools is not None and not self.allowed_tools:
            raise ValueError("allowed_tools=() would read as no restriction; use None for that")
        if not isinstance(self.extra_args, tuple) or not all(isinstance(a, str) for a in self.extra_args):
            raise ValueError("extra_args must be a tuple of strings: %r" % (self.extra_args,))
        if (not isinstance(self.env_unset, tuple) or not all(isinstance(n, str) and n and n == n.strip()
                                                             and "=" not in n and "," not in n for n in self.env_unset)):
            raise ValueError("env_unset must be a tuple of variable names, without = , or surrounding space: %r"
                             % (self.env_unset,))
        if "PATH" in self.env_unset:
            raise ValueError("env_unset cannot name PATH: claude_launch gives the child its own filtered PATH, "
                             "so the entry would be silently ignored")
        if "--" in self.extra_args:
            raise ValueError("extra_args cannot hold a bare --: it would end option parsing before -p")
        unknown = set(self.when) - CODEX_FAILURES
        if unknown:
            raise ValueError("when names reasons Codex cannot fail with: %s" % sorted(unknown))


OPUS = Fallback("opus", "claude-opus-5-5")
FABLE = Fallback("fable", "claude-fable-5-1")
# The fallbacks a caller names by preset (`--fallback opus`), so the model ids live only here.
PRESETS = {fb.name: fb for fb in (OPUS, FABLE)}


@dataclass(frozen=True)
class Verdict:
    word: str
    reason: str


@dataclass(frozen=True)
class Shape:
    """The other acceptance rule: a usable answer is `min` or more lines that start
    with `label:` (`RISK:` for a premortem). The parsed value keeps what follows the
    label on each such line, at most `max` of them."""
    label: str
    min: int = 1
    max: int | None = None

    def __post_init__(self):
        if not self.label.strip() or ":" in self.label:
            raise ValueError("a line label is one word without a colon, not %r" % (self.label,))
        if self.min < 1 or (self.max is not None and self.max < self.min):
            raise ValueError("min must be at least 1 and max at least min: %r" % (self,))


@dataclass(frozen=True)
class Lines:
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Attempt:
    reviewer: str
    reason: str
    output: str
    exit_code: int | None
    stderr_tail: str
    model: str | None


@dataclass(frozen=True)
class Result:
    reviewer: str
    output: str
    parsed: Verdict | Lines | None     # what the acceptance rule took from the answer
    attempts: tuple[Attempt, ...]


# What `[[:space:]]` matched in the old script's grep and sed under a UTF-8 locale, inside one
# line (lines split on \n only). It is not Python's `\s`: no no-break spaces, U+0085 or U+001C-1F.
_SPACE_CLASS = r"[\t\x0b\x0c\r \u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000]"
_SPACE = _SPACE_CLASS + "*"
_is_space = re.compile(_SPACE_CLASS).match

NO_REASON = "(no reason given)"
_REASON = re.compile(_SPACE + "REASON:" + _SPACE + "(.*)", re.IGNORECASE)


def _reason(lines: list[str]) -> str:
    for line in lines:
        m = _REASON.match(line)
        if m:
            return m.group(1) or NO_REASON
    return NO_REASON


def _check_words(words: tuple[str, ...]) -> None:
    """Refuse a vocabulary that would match any `VERDICT:` line (no words, or a blank one).

    "Blank" is Python's `strip()`, wider than the `_SPACE_CLASS` that matching uses: a word made
    only of no-break or control spaces is a caller's mistake, and refusing it is the safe side.
    """
    if not words or any(not w.strip() for w in words):
        raise ValueError("words must be a non-empty list of non-blank verdict words: %r" % (tuple(words),))


def _verdict_line(words: tuple[str, ...]):
    """A matcher for `VERDICT: <word>` at the start of a line: line -> the word, or None.

    Words are tried longest first. Under the token rule the word must end at a
    boundary: a letter or digit (Unicode too), a hyphen or any other dash or connector
    punctuation, a combining mark, or an invisible character (control or format:
    zero-width joiner, soft hyphen) continues a token, so GO-AHEAD is not GO, NO-GOING is
    not NO-GO, GO\u00e9 is not GO and GO + U+0301 is not GO. Whitespace and other
    punctuation end it.
    """
    alternatives = "|".join(re.escape(w.upper()) for w in sorted(words, key=len, reverse=True))
    rule = words.match if isinstance(words, Words) else _default_rule(words)
    token = rule != "prefix"
    pattern = re.compile(r"%sVERDICT:%s(%s)%s" % (_SPACE, _SPACE, alternatives, r"(?![\w-])" if token else ""),
                         re.IGNORECASE)

    def match(line: str) -> str | None:
        m = pattern.match(line)
        if m is None:
            return None
        after = line[m.end(1):m.end(1) + 1]
        kind = unicodedata.category(after) if after else ""
        if token and (kind in ("Pd", "Pc") or (kind[:1] in ("M", "C") and not _is_space(after))):
            return None
        return m.group(1).upper()
    return match


def _parse(output: str, words: tuple[str, ...], strict: bool = False) -> Verdict | None:
    """The first usable VERDICT line, or None. Under `strict`, two usable lines that
    disagree are no verdict at all."""
    match = _verdict_line(words)
    lines = output.split("\n")          # as grep splits: on \n only
    found = []
    for line in lines:
        word = match(line)
        if word:
            found.append(word)
            if not strict:
                break
    if not found or len(set(found)) > 1:
        return None
    return Verdict(found[0], _reason(lines))


def _parse_lines(output: str, shape: Shape) -> Lines | None:
    """The lines under `shape.label`, or None when there are fewer than `shape.min`."""
    pattern = re.compile(_SPACE + re.escape(shape.label) + ":" + _SPACE + "(.*)", re.IGNORECASE)
    found = [m.group(1).rstrip() for m in map(pattern.match, output.split("\n")) if m]
    if len(found) < shape.min:
        return None
    return Lines(tuple(found[:shape.max]))


def _acceptance(words: tuple[str, ...] | None, lines: Shape | None, strict: bool):
    """One rule for "is this answer usable": `words` (a VERDICT: line) or `lines` (a Shape).
    Returns text -> Verdict | Lines | None."""
    if (words is None) == (lines is None):
        raise ValueError("give exactly one of words (a verdict vocabulary) and lines (a Shape)")
    if words is not None:
        _check_words(words)
        return lambda text: _parse(text, words, strict)
    return lambda text: _parse_lines(text, lines)


TERM_GRACE = 2   # seconds between SIGTERM and SIGKILL when a reviewer is stopped
STDERR_TAIL = 2048


def _stop(proc: subprocess.Popen) -> None:
    """Stop a reviewer and everything it started: TERM its process group, then KILL it.

    The reviewer leads a group of its own (start_new_session), so a hung `codex`
    and the helpers it spawned go together and nothing is left running.
    """
    for sig, wait in ((signal.SIGTERM, TERM_GRACE), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            pass
    proc.wait()


class _Run(NamedTuple):
    code: int | None     # None after a timeout, and when the reviewer could not be started
    out: bytes           # as written: a NUL may sit inside a multi-byte character, so decoding waits
    err: str
    timed_out: bool


class _Turn(NamedTuple):
    attempt: Attempt
    answer: Verdict | Lines | None


def _snapshot(f, tail: int | None = None) -> bytes:
    """What a reviewer had written to a temporary file when it exited: all of it, or only its
    last `tail` bytes. Never more: a descendant may still be writing, and a read to end of file
    would then have no end."""
    f.seek(0, os.SEEK_END)
    size = f.tell()
    start = 0 if tail is None else max(0, size - tail)
    f.seek(start)
    return f.read(size - start)


def _read(f, tail: int | None = None) -> str:
    return _snapshot(f, tail).decode("utf-8", "replace")


def _run(argv: list[str], timeout: int, keep_stdout: bool = True, cwd: str | None = None,
         env: dict[str, str] | None = None) -> _Run:
    """Run one reviewer with a closed stdin.

    Its output goes to anonymous temporary files, not pipes, so the wait is on the
    reviewer alone: a descendant that left the process group and kept the output
    open can neither stall the chain nor turn an exit into a timeout. Output is
    read even after a timeout, because a reviewer may have answered before it hung.
    Stdout goes to /dev/null when it is not an answer channel (`keep_stdout` false).
    When the reviewer could not be started, `err` says why.
    """
    with tempfile.TemporaryFile() as err, \
            (tempfile.TemporaryFile() if keep_stdout else open(os.devnull, "wb")) as out:
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=True, cwd=cwd, env=env)
        except OSError as exc:
            return _Run(None, b"", str(exc), False)
        code: int | None = None
        timed_out = False
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop(proc)
            timed_out = True
        except BaseException:
            _stop(proc)
            raise
        return _Run(code, _snapshot(out) if keep_stdout else b"", _read(err, tail=4 * STDERR_TAIL), timed_out)


def _turn(reviewer, model, raw: bytes, run: _Run, parse) -> _Turn:
    """Decide the reason: a usable verdict beats everything, then timeout, error, noverdict."""
    # bash's $(...) dropped NUL bytes, and grep decoded what was left: RE\0JECT was REJECT, and a NUL
    # inside the bytes of one character gave that character back. So the NULs go before the decode.
    # The attempt keeps the output as the reviewer wrote it.
    output = raw.decode("utf-8", "replace")
    answer = parse(raw.replace(b"\0", b"").decode("utf-8", "replace"))
    if answer:
        reason = "answered"
    elif run.timed_out:
        reason = "timeout"
    elif run.code != 0:
        reason = "error"
    else:
        reason = "noverdict"
    return _Turn(Attempt(reviewer, reason, output, run.code, run.err[-STDERR_TAIL:], model), answer)


def _codex(prompt, effort, timeout, parse, cwd) -> _Turn:
    if shutil.which("codex") is None:
        return _Turn(Attempt("codex", "absent", "", None, "", None), None)
    fd, last = tempfile.mkstemp(prefix="reviewer-chain-")
    try:
        os.close(fd)
        run = _run(["codex", "exec", "-s", "read-only", "--skip-git-repo-check",
                    *(["-C", cwd] if cwd else []),
                    "-c", 'model_reasoning_effort="%s"' % effort, "-o", last, prompt], timeout,
                   keep_stdout=False)
        try:
            with open(last, "rb") as f:
                raw = _snapshot(f)
        except OSError:            # the answer file was removed: no answer, as `cat 2>/dev/null` saw it
            raw = b""
        return _turn("codex", None, raw, run, parse)
    finally:
        Path(last).unlink(missing_ok=True)


def claude_argv(fb: Fallback, prompt: str) -> list[str]:
    """The `claude` call for a fallback: the one place its argv is built, so that whatever checks
    the call (boss_review.py --check-fallback) runs the argv a review runs.

    `--allowedTools`, `--tools` and `--mcp-config` take a variable number of values, so everything
    but the model and the prompt goes ahead of `-p`, which ends them: after one of them, the prompt
    would be read as one more tool name.
    """
    tools = ["--allowedTools", ",".join(fb.allowed_tools)] if fb.allowed_tools else []
    return ["claude", *tools, *fb.extra_args, "-p", "--model", fb.model, prompt]


def child_env(fb: Fallback) -> dict[str, str] | None:
    """The environment of the fallback's `claude`: ours without `fb.env_unset` (None: inherit as is).
    `claude` loads plugins, and so their hooks, that the environment names even where it ignores the
    settings files; the review and --check-fallback both start it with this (see `claude_launch`)."""
    return {k: v for k, v in os.environ.items() if k not in fb.env_unset} if fb.env_unset else None


def _within(base: str):
    """A test for "is this realpath `base` or below it". The prefix is `base` with one trailing
    separator, so a base of `/` (whose `base + os.sep` is `//`) keeps out everything."""
    prefix = base if base.endswith(os.sep) else base + os.sep
    return lambda path: path == base or path.startswith(prefix)


def _is_preset(fb: Fallback) -> bool:
    """True for the OPUS/FABLE presets, however a caller sets `allowed_tools`, `timeout` or `when` on them.

    A preset is its name and model with no confinement of its own (`extra_args`, `env_unset`): `--fallback opus
    --fallback-tools Read,Grep,Glob` (boss-goal) is still the preset. The PR gate's `fallback_spec` carries the
    same name and model but confines the child with both, so it is custom and keeps the filtered PATH. Full
    equality with a PRESETS value would call the boss-goal spec custom (ticket 45)."""
    base = PRESETS.get(fb.name)
    return (base is not None and fb.model == base.model
            and fb.extra_args == base.extra_args and fb.env_unset == base.env_unset)


def claude_launch(fb: Fallback, prompt: str, cwd: str | None = None) -> tuple[list[str], dict] | None:
    """The argv and environment to start the fallback's `claude` with, or None when it is not there.

    For every spec, the confined one and the OPUS/FABLE presets alike, `claude` is looked up on a PATH
    without the entries a PR checkout could supply (empty or relative ones, and any inside `cwd`, or
    the current directory when `cwd` is None and the spec is the confined one; a preset with no `cwd`
    loses only its empty and relative entries), refused when the `claude` found is a link into that
    directory, and started by its absolute path: a bare name is resolved after the process has changed into the
    checkout, where `PATH=.:...` or a checkout-local `.venv/bin` would run the PR's own `claude`
    before any confinement flag is read. The first `claude` on the filtered PATH is the only candidate:
    when it is refused (a link into that directory), the result is None, "absent", and no later PATH
    entry is tried. With no `cwd` and a current directory that no longer exists, the confined spec is
    None too: there is no base to keep out. The environment is the spec's (`child_env`), or ours as it
    is for a spec that unsets nothing. The confined spec's child gets the filtered PATH. A preset's child
    gets ours minus its empty and relative entries (in the child they would mean the checkout, not the
    caller's directory) and keeps the absolute ones under the checkout, so an MCP server or hook found
    through an activated `.venv/bin` still starts: only the lookup of `claude` is filtered."""
    argv = claude_argv(fb, prompt)
    env = child_env(fb)
    # With no cwd there is no checkout to keep out. The confined spec still excludes the current
    # directory (ticket 14); a preset only loses its empty and relative entries, because the caller's
    # directory may be an ancestor of a per-user install (`$HOME` holding ~/.local/bin/claude).
    try:
        base = os.path.realpath(cwd or os.getcwd()) if cwd or env is not None else None
    except OSError:         # getcwd failed: a deleted current directory, or a PermissionError from it (no cwd), or a
                            # relative `cwd` resolved against a deleted process cwd. Nothing to keep out, nothing safe to start: fail closed
        return None
    inside = _within(base) if base else (lambda path: False)
    preset = _is_preset(fb)     # not "unsets nothing": a custom spec is confined by its own flags, so it gets the filtered PATH
    if env is None:
        env = dict(os.environ)
    keep, child_keep = [], []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        child_keep.append(entry)
        if inside(os.path.realpath(entry)):
            continue
        keep.append(entry)
    # Only the lookup of `claude` is filtered for a preset: the MCP servers and hooks it loads keep the
    # owner's absolute entries, an activated checkout `.venv/bin` among them (ticket 21). The confined
    # spec gets the filtered PATH, since nothing the checkout supplies may run in it.
    env["PATH"] = os.pathsep.join(child_keep if preset else keep)
    lookup = os.pathsep.join(keep)
    exe = shutil.which("claude", path=lookup)
    if exe is None:
        return None
    real_exe = os.path.realpath(exe)    # a symlink in a safe directory may lead into the checkout
    if inside(real_exe):
        return None
    argv[0] = exe
    return argv, env


def _claude(prompt, fb: Fallback, timeout, parse, cwd) -> _Turn:
    launch = claude_launch(fb, prompt, cwd)
    if launch is None:
        return _Turn(Attempt(fb.name, "absent", "", None, "", fb.model), None)
    run = _run(launch[0], timeout, cwd=cwd, env=launch[1])
    return _turn(fb.name, fb.model, run.out, run, parse)


def run_chain(prompt: str, *, words: tuple[str, ...] | None = None, lines: Shape | None = None,
              effort: str = "medium", codex_timeout: int = DEFAULT_TIMEOUT,
              fallback: Fallback | None = None, strict: bool = False,
              cwd: str | None = None, skip_codex: bool = False) -> Result:
    """Ask Codex, then the fallback if one is given and Codex's reason is in its `when`. With `skip_codex` (which
    needs a fallback) Codex is not started and the fallback alone is asked: one attempt, for a caller that chose
    not to spend Codex on this review (review by risk, ticket 52).

    A usable answer is a VERDICT: line in `words`, or `lines.min` lines under `lines.label`;
    give one of the two. The first attempt with a usable answer answers; if none has one,
    the reviewer is "none". With `cwd`, both reviewers run in that directory and may read
    it. A fallback without a timeout of its own gets twice `codex_timeout`.
    """
    parse = _acceptance(words, lines, strict)
    if cwd is not None and not os.path.isdir(cwd):
        raise ValueError("cwd is not a directory: %s" % cwd)
    if skip_codex and fallback is None:
        raise ValueError("skip_codex needs a fallback: nothing would be asked")
    timeout = None if fallback is None else 2 * codex_timeout if fallback.timeout is None else fallback.timeout
    if skip_codex:
        tried = [_claude(prompt, fallback, timeout, parse, cwd)]
    else:
        tried = [_codex(prompt, effort, codex_timeout, parse, cwd)]
        if fallback is not None and tried[0].attempt.reason in fallback.when:
            tried.append(_claude(prompt, fallback, timeout, parse, cwd))
    attempts = tuple(turn.attempt for turn in tried)
    for turn in tried:
        if turn.answer:
            return Result(turn.attempt.reviewer, turn.attempt.output, turn.answer, attempts)
    return Result("none", "", None, attempts)


def _csv(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _json_strings(text: str) -> tuple[str, ...]:
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):        # nested past the parser's depth: not a list of strings either
        value = None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise argparse.ArgumentTypeError("must be a JSON list of strings, e.g. '[\"--tools\", \"Read\"]': %r"
                                         % text[:80])
    return tuple(value)


def fallback_flags(fb: Fallback) -> list[str]:
    """`fb` as the command-line flags that rebuild it, for a caller that starts this command as a
    child process and so cannot hand it a `Fallback`. Every field is carried, so that none (the
    confinement in `extra_args`, above all) is dropped on the way; what the flags cannot carry
    exactly is refused, never changed."""
    flags = ["--fallback-name", fb.name, "--fallback-model", fb.model,
             "--fallback-when", ",".join(fb.when)]
    if fb.timeout is not None:
        flags += ["--fallback-timeout", str(fb.timeout)]
    if fb.allowed_tools:
        tools = ",".join(fb.allowed_tools)
        if _csv(tools) != tuple(fb.allowed_tools):
            raise ValueError("--fallback-tools is one comma list and cannot carry %r" % (fb.allowed_tools,))
        flags += ["--fallback-tools", tools]
    if fb.extra_args:
        flags += ["--fallback-extra-args", json.dumps(list(fb.extra_args))]
    if fb.env_unset:
        flags += ["--fallback-env-unset", ",".join(fb.env_unset)]
    return flags


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="reviewer_chain.py",
        description="Ask Codex, then an optional fallback model, for a VERDICT. Writes one JSON "
                    "object (the Result) to stdout. Exit 0: a reviewer answered. 1: none did. 2: usage.")
    ap.add_argument("--prompt-file", required=True, help="the prompt, passed to the reviewers as is")
    ap.add_argument("--words", type=_csv, help="verdict words, e.g. APPROVE,REJECT")
    ap.add_argument("--match", choices=("prefix", "token"),
                    help="prefix: APPROVED is APPROVE (boss-run). token: whole words. "
                         "Default: prefix for APPROVE,REJECT, token for any other words")
    ap.add_argument("--lines", metavar="LABEL",
                    help="instead of --words: a usable answer is --min-lines lines starting `LABEL:`")
    ap.add_argument("--min-lines", type=int, metavar="N", help="with --lines; default 1")
    ap.add_argument("--max-lines", type=int, metavar="N", help="with --lines: keep at most N lines")
    ap.add_argument("--effort", default="medium", help="Codex model_reasoning_effort")
    ap.add_argument("--cwd", metavar="DIR", help="run both reviewers in DIR (Codex -C), so they may read it")
    ap.add_argument("--codex-timeout", type=int, default=DEFAULT_TIMEOUT, metavar="SECONDS")
    ap.add_argument("--fallback", choices=sorted(PRESETS), metavar="PRESET",
                    help="a named fallback (%s); its name and model come from this module"
                         % ", ".join(sorted(PRESETS)))
    ap.add_argument("--fallback-name", help="what the result calls the fallback, e.g. opus")
    ap.add_argument("--fallback-model", help="exact model id for `claude --model`")
    ap.add_argument("--fallback-timeout", type=int, metavar="SECONDS",
                    help="default: twice --codex-timeout")
    ap.add_argument("--fallback-tools", type=_csv, help="comma list for `claude --allowedTools`")
    ap.add_argument("--fallback-when", type=_csv, metavar="REASONS",
                    help="Codex reasons that let the fallback run (default: all four)")
    ap.add_argument("--fallback-extra-args", type=_json_strings, metavar="JSON",
                    help="more `claude` flags, as one JSON list of strings, put ahead of -p")
    ap.add_argument("--fallback-env-unset", type=_csv, metavar="NAMES",
                    help="comma list of environment variables the `claude` call does not inherit")
    ap.add_argument("--no-fallback", action="store_true", help="Codex only (also the default)")
    ap.add_argument("--skip-codex", action="store_true",
                    help="do not ask Codex: ask the fallback alone (needs a fallback; one attempt)")
    ap.add_argument("--strict", action="store_true",
                    help="two usable VERDICT lines that disagree are no verdict")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    options = {"--fallback-name": args.fallback_name, "--fallback-model": args.fallback_model,
               "--fallback-timeout": args.fallback_timeout, "--fallback-tools": args.fallback_tools,
               "--fallback-when": args.fallback_when, "--fallback-extra-args": args.fallback_extra_args,
               "--fallback-env-unset": args.fallback_env_unset}
    given = [flag for flag, value in options.items() if value is not None]
    if args.no_fallback and (given or args.fallback):
        ap.error("--no-fallback conflicts with %s" % ", ".join(given or ["--fallback"]))
    if args.skip_codex and (args.no_fallback or not (args.fallback or args.fallback_name)):
        ap.error("--skip-codex needs a fallback (--fallback or --fallback-name with --fallback-model)")
    if args.fallback and (args.fallback_name or args.fallback_model):
        ap.error("--fallback %s already names the fallback and its model" % args.fallback)
    if given and not args.fallback and not (args.fallback_name and args.fallback_model):
        ap.error("%s need --fallback or both --fallback-name and --fallback-model" % ", ".join(given))
    if (args.words is None) == (args.lines is None):
        ap.error("give --words or --lines, not both and not neither")
    if args.lines is None and (args.min_lines is not None or args.max_lines is not None):
        ap.error("--min-lines and --max-lines go with --lines")
    if args.words is None and args.match is not None:
        ap.error("--match goes with --words")
    try:
        words = lines = None
        if args.words is not None:
            words = Words(args.words, match=args.match)
            _check_words(words)
        else:
            lines = Shape(args.lines, 1 if args.min_lines is None else args.min_lines, args.max_lines)
        fallback = None
        if args.fallback or args.fallback_name:
            preset = PRESETS.get(args.fallback)
            extra = {} if args.fallback_when is None else {"when": args.fallback_when}
            if args.fallback_extra_args is not None:
                extra["extra_args"] = args.fallback_extra_args
            if args.fallback_env_unset is not None:
                extra["env_unset"] = args.fallback_env_unset
            fallback = Fallback(preset.name if preset else args.fallback_name,
                                preset.model if preset else args.fallback_model,
                                args.fallback_timeout, args.fallback_tools, **extra)
        # surrogateescape, so that bytes that are not UTF-8 come back out of argv as the same bytes:
        # the reviewer must be shown the command that will run, not a lossy copy of it.
        prompt = os.fsdecode(Path(args.prompt_file).read_bytes())
        if args.cwd is not None and not os.path.isdir(args.cwd):
            raise ValueError("--cwd is not a directory: %s" % args.cwd)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    result = run_chain(prompt, words=words, lines=lines, effort=args.effort,
                       codex_timeout=args.codex_timeout, fallback=fallback, strict=args.strict,
                       cwd=args.cwd, skip_codex=args.skip_codex)
    print(json.dumps(dataclasses.asdict(result)))
    return 0 if result.reviewer != "none" else 1


if __name__ == "__main__":
    sys.exit(main())
