#!/usr/bin/env python3
"""The objective of a track, pm/<track>.goal.md: its one reader and writer.

    # Objective — <track>
    _Status: OPEN_            or `PAUSED — <why> (since …)`, `MET <date> — <proof>`
    ## Outcome … ## Done when … ## Tickets … ## Next, in priority order …

The status is the first `_Status:` line, wherever it sits; reading and writing
agree on that one line. On 2026-10-02 six of nineteen objectives had their
header twice, and three of them said MET or PAUSED on line 2 and OPEN on
line 4: the pulse took the first, `boss-goal list` took line 2, and the writer
overwrote line 2 whatever it held. The criteria are the boxes under
`## Done when`, for the pulse, `check` and `verify` alike.

Who uses it:

  boss-pulse.py        status, the sections it injects, the ticket source
  boss_ladder_core.py  is_open
  bin/boss-goal        through the command line below (bash)

    status(text)                the status as written, "" when unreadable
    is_open(text)
    set_status(text, value)     the first status line rewritten, or one inserted
    strip_header(body)          (body without a leading header, whether it had one)
    with_body(text, body)       `body` under the heading and the status line
    section(text, title)        the body of `## <title>`
    tickets_source(text)        the first line under `## Tickets`
    next_items(text)            the lines of `## Next, in priority order`
    next_count(text)            how many items those lines hold
    set_next(text, body)        that section replaced, the ones after it kept
    criteria(text)              (ticked, text) for each box under `## Done when`
    unmet(text)                 the unticked ones
    tick(text, criteria)        (text with those boxes ticked, how many)

Command line, for bash (exit 1 when the file cannot be read or written, 2 on a
bad call):

    objective.py status|tickets|next-count|criteria FILE   print
    objective.py set-status FILE VALUE                     rewrite the status line
    objective.py set-body|set-next FILE < body             replace that part
    objective.py tick FILE < criteria                      tick them, print how many
"""
import os
import re
import sys
from pathlib import Path

STATUS_RE = re.compile(r"^_Status:\s*(.+?)_\s*$")
HEADING = "# Objective — "
NEXT = "Next, in priority order"


def status(text: str) -> str:
    """The first `_Status:` line's value. A first status line that does not
    read is "", which is not open: a stale copy further down never stands in."""
    line = next((ln for ln in text.splitlines() if ln.startswith("_Status:")), "")
    m = STATUS_RE.match(line)
    return m.group(1).strip() if m else ""


def is_open(text: str) -> bool:
    return status(text).upper().startswith("OPEN")


def _heading_at(lines) -> int:
    """The index of the `# ` heading above the first `## `, or -1."""
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            break
        if ln.startswith("# "):
            return i
    return -1


def set_status(text: str, value: str) -> str:
    """`text` with its first `_Status:` line saying `value`. With none, the line
    goes under the `# ` heading, or first when there is no heading either."""
    if "\n" in value or "\r" in value:
        raise ValueError("a status is one line")
    lines = text.split("\n")
    new = "_Status: %s_" % value
    at = next((i for i, ln in enumerate(lines) if ln.startswith("_Status:")), None)
    if at is not None:
        lines[at] = new
    else:
        lines.insert(_heading_at(lines) + 1, new)
    return "\n".join(lines)


def strip_header(body: str):
    """(`body` without the header `boss-goal show` prints, whether it had one).

    Only that header: blank lines, `# Objective — <track>`, then a `_Status:`
    line. A body that keeps it gets a second status line nothing rewrites; a
    body heading like `# Objectives` stays."""
    lines = body.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    start = i
    if i < len(lines) and lines[i].startswith(HEADING):
        i += 1
    if i < len(lines) and lines[i].startswith("_Status:"):
        i += 1
    if i == start:
        return body, False
    return "\n".join(lines[i:]), True


def with_body(text: str, body: str) -> str:
    """`body` under the header of `text`: its `# ` heading and its status line,
    in the order they stand. The status stays as it was; only `set_status`
    changes it."""
    lines = text.splitlines()
    keep = {_heading_at(lines)}
    keep.add(next((i for i, ln in enumerate(lines) if ln.startswith("_Status:")), -1))
    head = [lines[i] for i in sorted(keep) if i >= 0]
    return "\n".join(head + [body.rstrip("\n")]) + "\n"


# --------------------------------------------------------------- sections

def section(text: str, title: str) -> str:
    """The body of `## <title>`, up to the next `## `, stripped."""
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(title), text, re.M | re.S)
    return m.group(1).strip() if m else ""


def _section_span(lines, title):
    """(first, end) line indices of `## <title>`'s body, or None."""
    head = re.compile(r"^##\s+%s\s*$" % re.escape(title))
    at = next((i for i, ln in enumerate(lines) if head.match(ln)), None)
    if at is None:
        return None
    end = next((i for i in range(at + 1, len(lines)) if re.match(r"^##\s", lines[i])), len(lines))
    return at + 1, end


def tickets_source(text: str) -> str:
    """The first line under `## Tickets`: a folder of ticket files or `gh:…`, or ""."""
    for line in section(text, "Tickets").splitlines():
        line = line.strip().strip("`").strip()
        if line:
            return line
    return ""


def next_items(text: str) -> list:
    """Every non-blank line of `## Next, in priority order`, indent kept: what the
    pulse hands an idle worker when there is no ticket graph."""
    lines = text.splitlines()
    span = _section_span(lines, NEXT)
    return [ln for ln in lines[slice(*span)] if ln.strip()] if span else []


ITEM_RE = re.compile(r"^(\d+[.)]|[-*+])\s")


def next_count(text: str) -> int:
    """How many items `## Next` queues: lines that start a list item at the margin.
    A wrapped or nested line belongs to the item above it."""
    return sum(1 for ln in next_items(text) if ITEM_RE.match(ln))


def set_next(text: str, body: str) -> str:
    """`text` with `## Next, in priority order` holding `body`; the sections after
    it stay. A file without the section gets it at the end."""
    lines = text.split("\n")
    span = _section_span(lines, NEXT)
    new = body.rstrip("\n").split("\n")
    if span is None:
        return text.rstrip("\n") + "\n\n## %s\n%s\n" % (NEXT, "\n".join(new))
    first, end = span
    tail = lines[end:]
    return "\n".join(lines[:first] + new + ([""] + tail if tail else [""]))


BOX_RE = re.compile(r"^- \[([ x])\] (.*)$")


def criteria(text: str) -> list:
    """(ticked, text) for each `- [ ]` / `- [x]` line under `## Done when`."""
    lines = text.splitlines()
    span = _section_span(lines, "Done when")
    return [(m.group(1) == "x", m.group(2))
            for m in map(BOX_RE.match, lines[slice(*span)] if span else []) if m]


def unmet(text: str) -> list:
    """The unticked criteria, without the box."""
    return [c for done, c in criteria(text) if not done]


def tick(text: str, done) -> tuple:
    """(`text` with the criteria in `done` ticked, how many). A literal match on
    the whole criterion, inside `## Done when` only."""
    lines = text.split("\n")
    span = _section_span(lines, "Done when")
    n = 0
    for c in done:
        for i in range(*span) if span else ():
            if lines[i] == "- [ ] " + c:
                lines[i] = "- [x] " + c
                n += 1
                break
    return "\n".join(lines), n


# ----------------------------------------------------------- command line

USAGE = ("usage: objective.py {status|tickets|next-count|criteria|set-body|set-next|tick} FILE"
         " | set-status FILE VALUE")


def _write(path: Path, text: str) -> None:
    """Through a temp file beside the target, with its mode; a symlink stays one."""
    path = path.resolve()
    tmp = path.with_name(".%s.tmp%d" % (path.name, os.getpid()))
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def main(argv) -> int:
    reads = {"status": status, "tickets": tickets_source, "next-count": next_count,
             "criteria": lambda t: "\n".join("- [%s] %s" % ("x" if d else " ", c)
                                             for d, c in criteria(t))}
    stdin_cmds = ("set-body", "set-next", "tick")
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if not ((cmd in reads or cmd in stdin_cmds) and len(args) == 1
            or cmd == "set-status" and len(args) == 2 and not set(args[1]) & {"\n", "\r"}):
        print(USAGE, file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print("objective: cannot read %s: %s" % (path, e.strerror), file=sys.stderr)
        return 1
    if cmd in reads:
        out = str(reads[cmd](text))
        if out:
            print(out)
        return 0
    if cmd == "set-status":
        new = set_status(text, args[1])
    elif cmd == "tick":
        new, n = tick(text, [ln for ln in sys.stdin.read().splitlines() if ln])
        print("ticked %d" % n)
    else:
        body = sys.stdin.read()
        if cmd == "set-body":
            body, dropped = strip_header(body)
            if dropped:
                print("dropped the header from stdin; the status stays as it was "
                      "(boss-goal status to change it)", file=sys.stderr)
            if not body.strip():
                print("objective: nothing on stdin but a header", file=sys.stderr)
                return 1
        new = with_body(text, body) if cmd == "set-body" else set_next(text, body)
    try:
        _write(path, new)
    except OSError as e:
        print("objective: cannot write %s: %s" % (path, e.strerror), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
