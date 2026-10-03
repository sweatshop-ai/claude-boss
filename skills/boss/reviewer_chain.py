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


@dataclass(frozen=True)
class Fallback:
    name: str
    model: str
    timeout: int = 120
    allowed_tools: tuple[str, ...] | None = None
    when: tuple[str, ...] = ("absent", "timeout", "error", "noverdict")

    def __post_init__(self):
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


NO_REASON = "(no reason given)"
_REASON = re.compile(r"[ \t\r\f\v]*REASON:[ \t\r\f\v]*(.*)", re.IGNORECASE)


def _reason(lines: list[str]) -> str:
    for line in lines:
        m = _REASON.match(line)
        if m:
            return m.group(1) or NO_REASON
    return NO_REASON


def _check_words(words: tuple[str, ...]) -> None:
    """Refuse a vocabulary that would match any `VERDICT:` line (no words, or a blank one)."""
    if not words or any(not w.strip() for w in words):
        raise ValueError("words must be a non-empty list of non-blank verdict words: %r" % (tuple(words),))


_SPACE = r"[ \t\r\f\v]*"   # what grep's [[:space:]]* matches within one line


def _verdict_line(words: tuple[str, ...]) -> re.Pattern:
    """`VERDICT: <word>` at the start of a line, longest word first.

    Under the token rule the word must end at a boundary, and a hyphen continues
    a token, so GO-AHEAD is not GO and NO-GOING is not NO-GO.
    """
    alternatives = "|".join(re.escape(w.upper()) for w in sorted(words, key=len, reverse=True))
    rule = words.match if isinstance(words, Words) else _default_rule(words)
    end = "" if rule == "prefix" else r"(?![A-Za-z0-9_-])"
    return re.compile(r"%sVERDICT:%s(%s)%s" % (_SPACE, _SPACE, alternatives, end), re.IGNORECASE)


def _parse(output: str, words: tuple[str, ...], strict: bool = False) -> Verdict | None:
    """The first usable VERDICT line, or None. Under `strict`, two usable lines that
    disagree are no verdict at all."""
    line_re = _verdict_line(words)
    lines = output.split("\n")          # as grep splits: on \n only
    found = []
    for line in lines:
        m = line_re.match(line)
        if m:
            found.append(m.group(1).upper())
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
    out: str
    err: str
    timed_out: bool


class _Turn(NamedTuple):
    attempt: Attempt
    verdict: Verdict | None


def _run(argv: list[str], timeout: int) -> _Run:
    """Run one reviewer with a closed stdin.

    When the reviewer could not be started, `err` says why. Output is read even after a timeout, because
    a reviewer may have answered before it hung. The drain after the kill is
    bounded too: a descendant that left the group and still holds the pipe must
    not hold the chain with it.
    """
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        return _Run(None, "", str(exc), False)
    code: int | None
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        _stop(proc)
        try:
            out, err = proc.communicate(timeout=TERM_GRACE)
        except subprocess.TimeoutExpired as late:
            out, err = late.stdout or b"", late.stderr or b""
            proc.stdout.close()
            proc.stderr.close()
        code, timed_out = None, True
    except BaseException:
        _stop(proc)
        raise
    return _Run(code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), timed_out)


def _turn(reviewer, model, output, run: _Run, words, strict) -> _Turn:
    """Decide the reason: a usable verdict beats everything, then timeout, error, noverdict."""
    verdict = _parse(output, words, strict)
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
                    "-c", 'model_reasoning_effort="%s"' % effort, "-o", last, prompt], timeout)
        output = Path(last).read_bytes().decode("utf-8", "replace")
        return _turn("codex", None, output, run, words, strict)
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
              codex_timeout: int = 120, fallback: Fallback | None = None,
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
    ap.add_argument("--codex-timeout", type=int, default=120, metavar="SECONDS")
    ap.add_argument("--fallback-name", help="what the result calls the fallback, e.g. haiku")
    ap.add_argument("--fallback-model", help="exact model id for `claude --model`")
    ap.add_argument("--fallback-timeout", type=int, default=120, metavar="SECONDS")
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
    given = [args.fallback_name, args.fallback_model]
    if args.no_fallback and any(given) or bool(args.fallback_name) != bool(args.fallback_model):
        ap.error("--fallback-name and --fallback-model go together, and not with --no-fallback")
    try:
        words = Words(args.words, match=args.match)
        _check_words(words)
        fallback = None
        if args.fallback_name:
            extra = {} if args.fallback_when is None else {"when": args.fallback_when}
            fallback = Fallback(args.fallback_name, args.fallback_model, args.fallback_timeout,
                                args.fallback_tools, **extra)
        prompt = Path(args.prompt_file).read_bytes().decode("utf-8", "replace")
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    result = run_chain(prompt, words=words, effort=args.effort, codex_timeout=args.codex_timeout,
                       fallback=fallback, strict=args.strict)
    print(json.dumps(dataclasses.asdict(result)))
    return 0 if result.reviewer != "none" else 1


if __name__ == "__main__":
    sys.exit(main())
