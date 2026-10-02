#!/usr/bin/env python3
"""The formats of a track's two files, in one place.

  pm/<track>.md        the tracker. Its `## Open blockers` section holds one
                       line per thing blocked on the owner; a line the ladder
                       escalates carries a marker.
  pm/<track>.goal.md   the objective. Line 2 is `_Status: OPEN_`, `PAUSED — …`
                       or `MET … — …`, written by bin/boss-goal.

Who reads and writes them:

  boss-jev.py          writes the marker line under the lock, reads it back
  boss-pulse.py        reads the objective's status and the Open blockers
  boss_ladder_core.py  reads both, rewrites last= and next= under the lock
  bin/boss-tracker     writes the section template (bash), appends under the lock
  bin/boss-goal        writes the status line (bash)

The bash tools keep their own templates; test_tracker.py runs them and reads
what they wrote with this module, so the two cannot drift apart unnoticed.

Marker:

    [ladder id=a1b2c3d4 t0=2026-09-18T10:53+02:00 last=0
     next=2026-09-18T10:58+02:00 pane=20:0.2 ask="put the u2 file on lab-0"]

The fields are documented in routines/boss_ladder_core.py, which acts on them.
"""
import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- the lock

# Agreed with Berit 2026-09-18: boss-jev, the ladder and boss-tracker append
# all take fcntl.flock on this sibling, because the first two write by temp
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
    start = _token_at(line)
    if start < 0:
        return None
    i, fields = start + len(TOKEN), {}
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
    return line[start:i], fields


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


def insert_in_section(body: str, title: str, line: str) -> str:
    """`line` at the end of section `title`, before its trailing blank lines.
    A missing section is created at the end of the file."""
    lines = body.split("\n")
    head = next((i for i, ln in enumerate(lines)
                 if re.match(r"^##\s+%s\b" % re.escape(title), ln)), None)
    if head is None:
        return body.rstrip("\n") + "\n\n## %s\n%s\n" % (title, line)
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    at = end
    while at > head + 1 and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, line)
    return "\n".join(lines)


# ---------------------------------------------------------- the objective

STATUS_RE = re.compile(r"^_Status:\s*(.+?)_\s*$", re.M)


def goal_status(text: str) -> str:
    """The objective's status, upper-cased: `OPEN`, `PAUSED — …`, `MET …`.

    The first `_Status:` line is the one bin/boss-goal writes (line 2) and
    rewrites on `status`. A later one is a stale copy: on 2026-10-02 six of
    nineteen objectives had their header twice, and three of them said MET or
    PAUSED on line 2 and OPEN on line 4.
    """
    m = STATUS_RE.search(text)
    return m.group(1).strip().upper() if m else ""


def goal_open(text: str) -> bool:
    return goal_status(text).startswith("OPEN")
