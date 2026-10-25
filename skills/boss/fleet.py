#!/usr/bin/env python3
"""The fleet view: which tmux pane runs which Claude session, and who owns it.

One module answers this for boss-pulse, boss-panes and boss-lifecycle, so they
cannot disagree. Two rules live here and nowhere else:

  which session   the live session whose registry record names the pane
                  (`tmux: "<session>:@<window>.%<pane>"`, written by Claude Code)
  who owns it     the pane's `@boss_pane` stamp, set by the boss that claimed it

tmux sits behind an adapter: `Tmux` talks to the real server, `MemoryTmux`
holds panes in a list for tests.
"""
import subprocess
import time
from dataclasses import dataclass, field


@dataclass
class Pane:
    id: str
    coord: str = ""
    owner: str = ""
    command: str = ""
    path: str = ""
    mirror: str = ""


@dataclass
class Seat:
    """One pane and the session running in it, if any.

    `others` holds further live sessions that name the same pane, youngest
    last. A claude started from inside a pane (a tool call, a nested shell)
    inherits its TMUX_PANE, so its record names that pane too. The oldest is
    the pane's own session; the rest are flagged, never silently dropped.
    """
    pane: Pane
    session: dict = None
    others: list = field(default_factory=list)

    def flags(self):
        return ["shared-pane"] if self.others else []

    def explain(self):
        """Why this seat is flagged, in words a boss can act on; "" if it is not."""
        if not self.others:
            return ""
        also = "; ".join(_who(r) for r in self.others)
        return ("shared-pane: %d live sessions name pane %s. This row is %s, the oldest, "
                "which is the pane's own session. Also there: %s, started from inside it. "
                "A headless `claude -p` from a tool call leaves the keyboard to %s; an "
                "interactive claude in a nested shell takes it, and then keystrokes "
                "(retire, restart) reach the youngest. Look at the pane before sending "
                "keys; SendMessage reaches each by name."
                % (1 + len(self.others), self.pane.id, _who(self.session), also,
                   _name(self.session)))


def _opt(name):
    # `IFS=$'\t' read` in bash collapses runs of tabs, and an empty field would
    # shift every later one left, so an unset option prints "-" instead.
    return "#{?%s,#{%s},-}" % (name, name)


# The one tmux format. Field order matches Pane.
FORMAT = "\t".join(["#{pane_id}", "#{session_name}:#{window_index}.#{pane_index}",
                     _opt("@boss_pane"), "#{pane_current_command}", "#{pane_current_path}",
                     _opt("@worker_name")])

STAMP = "@boss_pane"


class TmuxUnavailable(Exception):
    """tmux did not answer: no server, a timeout, or no binary. Not an empty fleet."""


class Tmux:
    """The real tmux server."""

    def __init__(self, timeout=3):
        self.timeout = timeout

    def _run(self, args):
        try:
            r = subprocess.run(["tmux"] + args, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    def panes(self):
        raw = self._run(["list-panes", "-a", "-F", FORMAT])
        if raw is None:
            raise TmuxUnavailable("tmux list-panes failed")
        out = []
        for line in raw.splitlines():
            f = line.split("\t")
            if len(f) != 6 or not f[0].startswith("%"):
                continue
            out.append(Pane(*["" if v == "-" else v for v in f]))
        return out

    def stamp(self, pane, boss):
        """True when tmux took the stamp."""
        return self._run(["set-option", "-p", "-t", pane, STAMP, boss]) is not None


class MemoryTmux:
    def __init__(self, panes):
        self._panes = list(panes)

    def panes(self):
        return list(self._panes)

    def stamp(self, pane, boss):
        for p in self._panes:
            if p.id == pane:
                p.owner = boss
                return True
        return False


def pane_of(rec):
    """The `%N` pane id a session record names, or ""."""
    tm = (rec or {}).get("tmux") or ""
    return tm.rsplit(".", 1)[-1] if "%" in tm else ""


def _name(r):
    return r.get("name") or r.get("sessionId") or "?"


def _who(r):
    started = r.get("startedAt")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(started / 1000)) if started else "?"
    return "%s (%s, started %s)" % (_name(r), r.get("sessionId") or "-", when)


def view(tmux, sessions):
    """Every pane, with the session running in it."""
    by_pane = {}
    for r in sessions:
        p = pane_of(r)
        if p:
            by_pane.setdefault(p, []).append(r)
    seats = []
    for p in tmux.panes():
        here = sorted(by_pane.get(p.id, []), key=lambda r: r.get("startedAt") or 0)
        seats.append(Seat(p, here[0] if here else None, here[1:]))
    return seats


def owned(seats, boss_pane):
    """The seats a boss stamped, its own pane left out."""
    if not boss_pane:
        return []
    return [s for s in seats if s.pane.owner == boss_pane and s.pane.id != boss_pane]


def seat_of(seats, pane=None, sid=None):
    """The seat of a pane id or of a session id, or None."""
    for s in seats:
        if pane is not None and s.pane.id == pane:
            return s
        if sid is not None and any(r.get("sessionId") == sid for r in [s.session or {}] + s.others):
            return s
    return None
