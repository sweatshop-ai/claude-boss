#!/usr/bin/env python3
"""The reviewer chain: Codex first, an optional fallback model next, else nobody.

One place decides which reviewer answers, so `boss-run` and every other caller
cannot drift apart. Standard library only.

    run_chain(prompt, words=..., fallback=HAIKU) -> Result

`Result.reviewer` is "codex", the fallback's name, or "none". Every attempt is
kept on `Result.attempts` with a reason from a closed set:

    answered   a usable VERDICT line was in the reviewer's answer
    absent     the reviewer is not on PATH
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
    timeout: int = DEFAULT_TIMEOUT
    allowed_tools: tuple[str, ...] | None = None
    when: tuple[str, ...] = ("absent", "timeout", "error", "noverdict")

    def __post_init__(self):
        if not self.name.strip() or self.name.strip().lower() in RESERVED_NAMES:
            raise ValueError("a fallback cannot be named %r: Result.reviewer already uses %s"
                             % (self.name, " and ".join(sorted(RESERVED_NAMES))))
        if self.allowed_tools is not None and not self.allowed_tools:
            raise ValueError("allowed_tools=() would read as no restriction; use None for that")
        unknown = set(self.when) - CODEX_FAILURES
        if unknown:
            raise ValueError("when names reasons Codex cannot fail with: %s" % sorted(unknown))


HAIKU = Fallback("haiku", "claude-haiku-4-5-20251001")


@dataclass(frozen=True)
class Verdict:
    word: str
    reason: str


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
    parsed: Verdict | None
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
    verdict: Verdict | None


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


def _run(argv: list[str], timeout: int, keep_stdout: bool = True) -> _Run:
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
                                    start_new_session=True)
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


def _turn(reviewer, model, raw: bytes, run: _Run, words, strict) -> _Turn:
    """Decide the reason: a usable verdict beats everything, then timeout, error, noverdict."""
    # bash's $(...) dropped NUL bytes, and grep decoded what was left: RE\0JECT was REJECT, and a NUL
    # inside the bytes of one character gave that character back. So the NULs go before the decode.
    # The attempt keeps the output as the reviewer wrote it.
    output = raw.decode("utf-8", "replace")
    verdict = _parse(raw.replace(b"\0", b"").decode("utf-8", "replace"), words, strict)
    if verdict:
        reason = "answered"
    elif run.timed_out:
        reason = "timeout"
    elif run.code != 0:
        reason = "error"
    else:
        reason = "noverdict"
    return _Turn(Attempt(reviewer, reason, output, run.code, run.err[-STDERR_TAIL:], model), verdict)


def _codex(prompt, effort, timeout, words, strict) -> _Turn:
    if shutil.which("codex") is None:
        return _Turn(Attempt("codex", "absent", "", None, "", None), None)
    fd, last = tempfile.mkstemp(prefix="reviewer-chain-")
    try:
        os.close(fd)
        run = _run(["codex", "exec", "-s", "read-only", "--skip-git-repo-check",
                    "-c", 'model_reasoning_effort="%s"' % effort, "-o", last, prompt], timeout,
                   keep_stdout=False)
        try:
            with open(last, "rb") as f:
                raw = _snapshot(f)
        except OSError:            # the answer file was removed: no answer, as `cat 2>/dev/null` saw it
            raw = b""
        return _turn("codex", None, raw, run, words, strict)
    finally:
        Path(last).unlink(missing_ok=True)


def _claude(prompt, fb: Fallback, words, strict) -> _Turn:
    if shutil.which("claude") is None:
        return _Turn(Attempt(fb.name, "absent", "", None, "", fb.model), None)
    # --allowedTools takes a variable number of values, so it goes ahead of -p:
    # after it, the prompt would be read as one more tool name.
    tools = ["--allowedTools", ",".join(fb.allowed_tools)] if fb.allowed_tools else []
    run = _run(["claude", *tools, "-p", "--model", fb.model, prompt], fb.timeout)
    return _turn(fb.name, fb.model, run.out, run, words, strict)


def run_chain(prompt: str, *, words: tuple[str, ...], effort: str = "medium",
              codex_timeout: int = DEFAULT_TIMEOUT, fallback: Fallback | None = None,
              strict: bool = False) -> Result:
    """Ask Codex, then the fallback if one is given and Codex's reason is in its `when`.

    The first attempt with a usable verdict answers; if none has one, the reviewer is "none".
    """
    _check_words(words)
    tried = [_codex(prompt, effort, codex_timeout, words, strict)]
    if fallback is not None and tried[0].attempt.reason in fallback.when:
        tried.append(_claude(prompt, fallback, words, strict))
    attempts = tuple(turn.attempt for turn in tried)
    for turn in tried:
        if turn.verdict:
            return Result(turn.attempt.reviewer, turn.attempt.output, turn.verdict, attempts)
    return Result("none", "", None, attempts)


def _csv(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="reviewer_chain.py",
        description="Ask Codex, then an optional fallback model, for a VERDICT. Writes one JSON "
                    "object (the Result) to stdout. Exit 0: a reviewer answered. 1: none did. 2: usage.")
    ap.add_argument("--prompt-file", required=True, help="the prompt, passed to the reviewers as is")
    ap.add_argument("--words", required=True, type=_csv, help="verdict words, e.g. APPROVE,REJECT")
    ap.add_argument("--match", choices=("prefix", "token"),
                    help="prefix: APPROVED is APPROVE (boss-run). token: whole words. "
                         "Default: prefix for APPROVE,REJECT, token for any other words")
    ap.add_argument("--effort", default="medium", help="Codex model_reasoning_effort")
    ap.add_argument("--codex-timeout", type=int, default=DEFAULT_TIMEOUT, metavar="SECONDS")
    ap.add_argument("--fallback-name", help="what the result calls the fallback, e.g. haiku")
    ap.add_argument("--fallback-model", help="exact model id for `claude --model`")
    ap.add_argument("--fallback-timeout", type=int, metavar="SECONDS",
                    help="default %d" % DEFAULT_TIMEOUT)
    ap.add_argument("--fallback-tools", type=_csv, help="comma list for `claude --allowedTools`")
    ap.add_argument("--fallback-when", type=_csv, metavar="REASONS",
                    help="Codex reasons that let the fallback run (default: all four)")
    ap.add_argument("--no-fallback", action="store_true", help="Codex only (also the default)")
    ap.add_argument("--strict", action="store_true",
                    help="two usable VERDICT lines that disagree are no verdict")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    options = {"--fallback-name": args.fallback_name, "--fallback-model": args.fallback_model,
               "--fallback-timeout": args.fallback_timeout, "--fallback-tools": args.fallback_tools,
               "--fallback-when": args.fallback_when}
    given = [flag for flag, value in options.items() if value is not None]
    if args.no_fallback and given:
        ap.error("--no-fallback conflicts with %s" % ", ".join(given))
    if given and not (args.fallback_name and args.fallback_model):
        ap.error("%s need both --fallback-name and --fallback-model" % ", ".join(given))
    try:
        words = Words(args.words, match=args.match)
        _check_words(words)
        fallback = None
        if args.fallback_name:
            extra = {} if args.fallback_when is None else {"when": args.fallback_when}
            fallback = Fallback(args.fallback_name, args.fallback_model,
                                DEFAULT_TIMEOUT if args.fallback_timeout is None else args.fallback_timeout,
                                args.fallback_tools, **extra)
        # surrogateescape, so that bytes that are not UTF-8 come back out of argv as the same bytes:
        # the reviewer must be shown the command that will run, not a lossy copy of it.
        prompt = os.fsdecode(Path(args.prompt_file).read_bytes())
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    result = run_chain(prompt, words=words, effort=args.effort, codex_timeout=args.codex_timeout,
                       fallback=fallback, strict=args.strict)
    print(json.dumps(dataclasses.asdict(result)))
    return 0 if result.reviewer != "none" else 1


if __name__ == "__main__":
    sys.exit(main())
