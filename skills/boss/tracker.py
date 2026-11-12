#!/usr/bin/env python3
"""The format of a track's tracker, pm/<track>.md, in one place.

  pm/<track>.md        the tracker. Its `## Open blockers` section holds one
                       line per thing blocked on the owner; a line the ladder
                       escalates carries a marker.

The objective, pm/<track>.goal.md, has its own module: objective.py.

Who reads and writes them:

  boss-pulse.py        reads the Open blockers
  boss_ladder_core.py  reads them, rewrites last= and next= under the lock
  bin/boss-tracker     writes the section template (bash), appends under the lock

The bash tools keep their own templates; test_tracker.py runs them and reads
what they wrote with this module, so the two cannot drift apart unnoticed.

    lock_path(tracker)          the sibling every writer flocks
    scan_marker(line)           (raw, fields) for the first marker, None, or MarkerError
    validate(fields)            typed fields, or MarkerError
    has_marker(line)            a marker token, readable or not
    render_marker(id, t0, nxt)  the token scan_marker reads back
    marker_tag(id)              the text that finds one marker by id
    rewrite(raw, last, nxt)     last= and next= updated, the rest byte for byte
    blockers_range(lines)       the Open blockers body, as line indices
    blocker_lines(text)         the same, as lines
    open_blockers(text)         its bulleted entries
    insert_in_section(body, title, line)
    mark_cleared(raw, when)     the line with cleared= before ask=
    update(path, fn, deadline)  the one locked, stat-checked, renamed write
    add_line(path, title, line, tag, deadline)   one line under a section, once

Marker, appended to a `## Open blockers` line:

    [ladder id=a1b2c3d4 t0=2026-09-18T10:53+02:00 last=0
     next=2026-09-18T10:58+02:00 pane=20:0.2 ask="put the u2 file on lab-0"]

  id       required, [a-z0-9]{4,16}, stable forever. The key. Survives any
           rewording of the line, and keys the state journal.
  t0       required, ISO 8601 WITH offset. When the blocker was raised. Never
           rewritten.
  last     required, the rung already posted. Born 0: the hook posts rung 0.
  next     required, ISO 8601 with offset. Authoritative gate — nothing posts
           before now >= next. Pushing it forward by hand defers a rung without
           losing t0, which is how "rungs held while the owner is at the keyboard"
           works.
  ask      required, double-quoted, no '"' inside. The one action. Slack text.
  pane     optional, sess:win.pane.
  cost     optional, quoted. What is idle behind it.
  cleared  optional, ISO 8601. Present -> the line is skipped forever. This
           never posts `boss-alert clear` itself; whoever sets cleared= posts it,
           because only they know it actually cleared.

A line with no marker is ignored. A malformed marker is reported by the ladder
and skipped, never guessed at.
"""
from __future__ import annotations

import errno
import fcntl
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------- the lock

# Agreed with Berit 2026-09-18: the ladder and boss-tracker append
# both take fcntl.flock on this sibling, because the ladder writes by temp
# file + rename and a lock on the tracker's own inode does not survive the
# replace. bin/boss-tracker spells the same path in bash.
def lock_path(path: Path) -> Path:
    return path.parent / f".{path.name}.lock"


# ---------------------------------------------------------------- the marker

TOKEN = "[ladder"
ID_RE = re.compile(r"^[a-z0-9]{4,16}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REQUIRED = ("id", "t0", "last", "next", "ask")
KNOWN = set(REQUIRED) | {"pane", "cost", "cleared"}

# What the hook writes into ask= until the boss names the action.
PLACEHOLDER = "(boss names it)"


class MarkerError(Exception):
    """A token that starts with [ladder but does not parse. Never guessed at."""


class _FromFn(Exception):
    """An exception raised by update's `fn`, carried past the writer's own I/O handler."""


def _token_at(line: str) -> int:
    """Index of the first `[ladder` token, or -1. `[ladderish` is not one."""
    start = line.find(TOKEN)
    if start < 0:
        return -1
    after = start + len(TOKEN)
    if after < len(line) and line[after] not in " \t]":
        return -1
    return start


def has_marker(line: str) -> bool:
    """Does the line carry a marker token, readable or not?

    The ladder owns such a line, broken or whole: a broken one is reported by
    the ladder, never escalated by anyone else.
    """
    return _token_at(line) >= 0


def scan_marker(line: str):
    """Return (raw_token, fields) for the first [ladder ...] token, or None."""
    found = _scan(line)
    return None if found is None else (line[found[0]:found[1]], found[2])


def _scan(line: str):
    """(start, end, fields, keys) for the first token, or None; keys maps a field
    name to the index in `line` where that key begins."""
    start = _token_at(line)
    if start < 0:
        return None
    i, fields, keys = start + len(TOKEN), {}, {}
    while True:
        while i < len(line) and line[i] in " \t":
            i += 1
        if i >= len(line):
            raise MarkerError("marker is not closed with ']'")
        if line[i] == "]":
            i += 1
            break
        eq = line.find("=", i)
        if eq < 0:
            raise MarkerError(f"no '=' after {line[i:i + 20]!r}")
        key = line[i:eq]
        if not KEY_RE.match(key):
            raise MarkerError(f"bad field name {key!r}")
        if key in fields:
            raise MarkerError(f"duplicate field {key!r}")
        keys[key] = i
        j = eq + 1
        if j < len(line) and line[j] == '"':
            end = line.find('"', j + 1)
            if end < 0:
                raise MarkerError(f"{key}= has no closing quote")
            fields[key], i = line[j + 1:end], end + 1
        else:
            end = j
            while end < len(line) and line[end] not in " \t]":
                end += 1
            fields[key], i = line[j:end], end
    return start, i, fields, keys


def parse_ts(value: str, field: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise MarkerError(f"{field}={value!r} is not ISO 8601")
    if dt.tzinfo is None:
        # A naive timestamp is ambiguous across a DST change, and the ladder
        # is nothing but time arithmetic.
        raise MarkerError(f"{field}={value!r} has no UTC offset")
    return dt


def validate(fields: dict) -> dict:
    missing = [k for k in REQUIRED if k not in fields]
    if missing:
        raise MarkerError(f"missing field(s): {', '.join(missing)}")
    unknown = sorted(set(fields) - KNOWN)
    if unknown:
        raise MarkerError(f"unknown field(s): {', '.join(unknown)}")
    if not ID_RE.match(fields["id"]):
        raise MarkerError(f"id={fields['id']!r} is not [a-z0-9]{{4,16}}")
    if not fields["ask"].strip():
        raise MarkerError("ask= is empty")
    try:
        last = int(fields["last"])
    except ValueError:
        raise MarkerError(f"last={fields['last']!r} is not a number")
    if last < 0:
        raise MarkerError(f"last={last} is negative")
    out = {
        "id": fields["id"], "last": last,
        "t0": parse_ts(fields["t0"], "t0"),
        "next": parse_ts(fields["next"], "next"),
        "ask": fields["ask"],
        "pane": fields.get("pane", ""), "cost": fields.get("cost", ""),
        "cleared": fields.get("cleared", ""),
    }
    if out["cleared"]:
        parse_ts(out["cleared"], "cleared")
    return out


def render_marker(id_: str, t0: datetime, nxt: datetime, ask: str = PLACEHOLDER,
                  pane: str = "", last: int = 0) -> str:
    """The token scan_marker reads back. ask may not hold a '"'."""
    if '"' in ask:
        raise MarkerError('ask= may not contain \'"\'')
    pane_f = f" pane={pane}" if pane else ""
    return (f"[ladder id={id_} t0={t0.isoformat(timespec='minutes')} last={last} "
            f"next={nxt.isoformat(timespec='minutes')}{pane_f} ask=\"{ask}\"]")


def marker_tag(id_: str) -> str:
    """The prefix that finds one marker by id in a tracker's text."""
    return f"{TOKEN} id={id_} "


def rewrite(raw: str, last: int, nxt: datetime) -> str:
    """Update last= and next= inside the token, byte for byte elsewhere."""
    out = re.sub(r"(?<=\blast=)[^\s\]]*", str(last), raw, count=1)
    return re.sub(r"(?<=\bnext=)[^\s\]]*", nxt.isoformat(), out, count=1)


def mark_cleared(raw: str, when: datetime) -> str:
    """`raw` with ` cleared=<when, ISO to the minute>` put before ask=, byte for byte elsewhere.

    A line with no readable marker, no ask= or a cleared= with a value is returned as it came;
    an empty `cleared=` is not cleared (validate says so), so it is filled in.
    `when` must carry a UTC offset: parse_ts refuses a naive one, and the ladder
    would report the marker malformed.
    """
    if when.tzinfo is None:
        raise ValueError("when has no UTC offset")
    try:
        found = _scan(raw)
    except MarkerError:
        return raw
    if found is None or found[2].get("cleared") or "ask" not in found[3]:
        return raw
    stamp = f"cleared={when.isoformat(timespec='minutes')}"
    if "cleared" in found[2]:
        lo = found[3]["cleared"]
        hi = lo + len("cleared=")
        if raw[hi:hi + 1] == '"':
            hi = raw.find('"', hi + 1) + 1
        else:
            while hi < len(raw) and raw[hi] not in " \t]":
                hi += 1
        return f"{raw[:lo]}{stamp}{raw[hi:]}"
    at = found[3]["ask"]
    return f"{raw[:at]}{stamp} {raw[at:]}"


def set_ask(raw: str, ask: str) -> str:
    """`raw` with the marker's ask= value replaced, byte for byte elsewhere.

    A line with no readable marker or no quoted ask= is returned as it came; `ask` may not hold a '"'.
    """
    if '"' in ask:
        raise MarkerError('ask= may not contain \'"\'')
    try:
        found = _scan(raw)
    except MarkerError:
        return raw
    if found is None or "ask" not in found[3]:
        return raw
    at = found[3]["ask"] + len("ask=")
    if raw[at:at + 1] != '"':
        return raw
    end = raw.find('"', at + 1)
    return f'{raw[:at]}"{ask}"{raw[end + 1:]}'


# ---------------------------------------------------------- Open blockers

BLOCKERS = "Open blockers"
BLOCKERS_RE = re.compile(r"^##\s+Open blockers.*?$", re.M)
NEXT_H2_RE = re.compile(r"^##\s", re.M)


def blockers_range(lines: list[str]) -> tuple[int, int]:
    """Line indices of the first `## Open blockers` body, or (0, 0) if none.

    A marker only means anything on a blocker line. Reading the whole file makes
    prose that documents the marker format — in a roster row, in a state note —
    parse as a malformed marker, which is exactly what happened at 14:59 on
    2026-09-18.
    """
    start = None
    for i, line in enumerate(lines):
        if start is None:
            if BLOCKERS_RE.match(line):
                start = i + 1
        elif NEXT_H2_RE.match(line):
            return start, i
    return (start, len(lines)) if start is not None else (0, 0)


def blocker_lines(text: str) -> list[str]:
    """The raw lines of the Open blockers body, without their line ends."""
    lines = text.splitlines()
    lo, hi = blockers_range(lines)
    return lines[lo:hi]


def open_blockers(text: str) -> list[str]:
    """Every bulleted entry under Open blockers, bullet stripped, newest last."""
    out = []
    for line in blocker_lines(text):
        line = line.strip()
        if line.startswith(("-", "*")) and len(line) > 2:
            out.append(line.lstrip("-* ").strip())
    return out


def _section(lines: list[str], title: str):
    """(head, end): the heading's line index and the index where its section ends, or None."""
    head = next((i for i, ln in enumerate(lines)
                 if re.match(r"^##\s+%s\b" % re.escape(title), ln)), None)
    if head is None:
        return None
    end = next((i for i in range(head + 1, len(lines)) if NEXT_H2_RE.match(lines[i])), len(lines))
    return head, end


def insert_in_section(body: str, title: str, line: str) -> str:
    """`line` at the end of section `title`, before its trailing blank lines.
    A missing section is created at the end of the file. The line goes in with the
    file's own line ending (CRLF if its first line ends so)."""
    first = body.find("\n")
    eol = "\r\n" if first > 0 and body[first - 1] == "\r" else "\n"
    lines = body.split("\n")
    found = _section(lines, title)
    if found is None:
        return body.rstrip("\r\n") + eol + eol + "## %s%s%s%s" % (title, eol, line, eol)
    head, end = found
    at = end
    while at > head + 1 and not lines[at - 1].strip():
        at -= 1
    cr = "\r" if eol == "\r\n" else ""
    if cr and at == len(lines) and not lines[-1].endswith("\r"):
        # The file has no final newline: the last line takes the break and the new one stays bare,
        # so the file still ends as it did and no ending is mixed.
        lines[-1] += cr
        cr = ""
    lines.insert(at, line + cr)
    return "\n".join(lines)


# ---------------------------------------------------------------- the writer

def update(path: Path, fn: Callable[[str], Optional[str]], deadline: float) -> str:
    """The one write to a tracker: lock, read, `fn(text)`, temp file, rename.

    Takes the sibling lock until `deadline` (a time.monotonic() value), polling
    with LOCK_NB so a held lock is a return value and not a hang. `fn` gets the
    text and returns the new text, or None for no change. The boss's Edit tool
    takes no lock, so the file's (st_ino, st_mtime_ns, st_size) is checked between the
    read and the rename, and the pass is redone on the new text, 3 tries in all
    (the ladder's process_tracker makes the same check with the same limit).

    A symlink in place of the tracker is never followed: the file is opened once with O_NOFOLLOW and read,
    and its identity checked, through that descriptor, so a link swapped in after a caller's lstat is
    "failed: the tracker is a symbolic link", and the target is left as it was (the old code never wrote
    through a link; it read the target and turned the link into a regular file). A symlink put there between the
    read and the rename shows as a changed inode, and the pass is redone.

    Returns "done", "done (no change)" or "failed: <reason>" and never raises
    for those; an exception from `fn` is not swallowed (the lock is let go, the
    file is as it was).
    """
    path = Path(path)
    failure = None
    try:
        with open(lock_path(path), "a") as lf:
            while True:
                try:
                    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        return "failed: lock held past the deadline"
                    time.sleep(0.01)
            for _ in range(3):
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                except OSError as err:
                    if err.errno == errno.ELOOP:
                        return "failed: the tracker is a symbolic link"
                    raise
                with os.fdopen(fd, newline="", encoding="utf-8") as fh:
                    before = os.fstat(fh.fileno())
                    text = fh.read()
                try:
                    new = fn(text)
                except (OSError, UnicodeDecodeError) as err:
                    raise _FromFn(err) from None
                if new is None:
                    return "done (no change)"
                fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".boss-tracker-")
                try:
                    with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
                        fh.write(new)
                    os.chmod(tmp, before.st_mode & 0o7777)
                    now = os.lstat(path)
                    if ((now.st_ino, now.st_mtime_ns, now.st_size)
                            != (before.st_ino, before.st_mtime_ns, before.st_size)):
                        continue
                    os.replace(tmp, path)
                    return "done"
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            return "failed: file changed on all 3 tries"
    except _FromFn as raised:
        failure = raised.args[0]
    except (OSError, UnicodeDecodeError) as err:
        return f"failed: {type(err).__name__}"
    # Raised outside the handler, so fn's exception keeps its own __cause__ and __context__.
    raise failure


def add_line(path: Path, title: str, line: str, tag: str, deadline: float) -> str:
    """`line` at the end of section `title` unless `tag` is already there.

    "There" is a line of that section that holds `tag` as a whole token (not inside a
    longer id, so `id=ab12cd34` is not found in `id=ab12cd345`) and carries no
    `cleared=` value, so a cleared blocker does not hide a new one with the same id.
    Other sections do not count. The tag is the caller's: a bare tag is found in any line of the section,
    prose included (`id=ab12cd34` is found in "- resolved id=ab12cd34, see PR 90"), and a line whose marker
    is malformed and holds the tag counts as there, so a hand-damaged marker never gets a second line beside
    it. A caller that means "the marker with this id" passes `marker_tag(id)`, which holds the token and
    is not found in prose.

    One locked step, so eight callers with one tag leave one line. Returns
    "done", "done (already there)" or "failed: ...". An empty `tag` is a ValueError:
    it would match every file.
    """
    if not tag:
        raise ValueError("tag is empty")
    # A tag that starts or ends in an ASCII letter or digit may not sit inside a longer word. The test and
    # the boundary class are the same class, so a non-ASCII edge gets no boundary.
    word = "[A-Za-z0-9]"
    whole = re.compile("%s%s%s" % ("(?<!%s)" % word if re.fullmatch(word, tag[0]) else "", re.escape(tag),
                                   "(?!%s)" % word if re.fullmatch(word, tag[-1]) else ""))

    def there(text: str) -> bool:
        lines = text.split("\n")
        found = _section(lines, title)
        if found is None:
            return False
        for ln in lines[found[0] + 1:found[1]]:
            if not whole.search(ln):
                continue
            try:
                scanned = scan_marker(ln)
            except MarkerError:
                return True
            if scanned is None or not scanned[1].get("cleared"):
                return True
        return False

    def fn(text: str) -> Optional[str]:
        return None if there(text) else insert_in_section(text, title, line)

    got = update(path, fn, deadline)
    return "done (already there)" if got == "done (no change)" else got
