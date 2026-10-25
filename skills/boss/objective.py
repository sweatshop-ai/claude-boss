#!/usr/bin/env python3
"""The objective of a track, pm/<track>.goal.md: its one reader and writer.

    # Objective — <track>
    _Status: OPEN_            or `PAUSED — <why> (since …)`, `MET <date> — <proof>`
    ## Outcome … ## Done when … ## Tickets … ## Next, in priority order …

The status is the first `_Status:` line, wherever it sits; reading and writing
agree on that one line. On 2026-10-02 six of nineteen objectives had their
header twice, and three of them said MET or PAUSED on line 2 and OPEN on
line 4: the pulse took the first, `boss-goal list` took line 2, and the writer
overwrote line 2 whatever it held.

Who uses it:

  boss-pulse.py        status, the sections it injects, the ticket source
  boss_ladder_core.py  is_open
  bin/boss-goal        through the command line below (bash)

    status(text)                the status as written, "" when unreadable
    is_open(text)
    set_status(text, value)     the first status line rewritten, or one inserted
    with_body(text, body)       `body` under the heading and the status line
    section(text, title)        the body of `## <title>`
    tickets_source(text)        the first line under `## Tickets`
    next_items(text)            the lines of `## Next, in priority order`
    next_count(text)            how many items those lines hold
    unmet(text)                 the `- [ ]` criteria under `## Done when`

Command line, for bash (exit 1 when the file cannot be read, 2 on a bad call):

    objective.py status|tickets|next-count FILE    print one value
    objective.py set-status FILE VALUE             rewrite the status line
    objective.py set-body FILE < body              replace all but the header
"""
import os
import re
import sys
from pathlib import Path

STATUS_RE = re.compile(r"^_Status:\s*(.+?)_\s*$")


def status(text: str) -> str:
    """The first `_Status:` line's value. A first status line that does not
    read is "", which is not open: a stale copy further down never stands in."""
    line = next((ln for ln in text.splitlines() if ln.startswith("_Status:")), "")
    m = STATUS_RE.match(line)
    return m.group(1).strip() if m else ""


def is_open(text: str) -> bool:
    return status(text).upper().startswith("OPEN")


def set_status(text: str, value: str) -> str:
    """`text` with its first `_Status:` line saying `value`. With none, the line
    goes under the `# ` heading, or first when there is no heading either."""
    lines = text.split("\n")
    new = "_Status: %s_" % value
    at = next((i for i, ln in enumerate(lines) if ln.startswith("_Status:")), None)
    if at is not None:
        lines[at] = new
    else:
        lines.insert(1 if lines and lines[0].startswith("# ") else 0, new)
    return "\n".join(lines)


def with_body(text: str, body: str) -> str:
    """`body` under the header of `text`: its `# ` heading and its status line.
    The status stays as it was; only `set_status` changes it."""
    lines = text.splitlines()
    head = [lines[0]] if lines and lines[0].startswith("# ") else []
    head += [ln for ln in lines if ln.startswith("_Status:")][:1]
    return "\n".join(head + [body.rstrip("\n")]) + "\n"


# --------------------------------------------------------------- sections

def section(text: str, title: str) -> str:
    """The body of `## <title>`, up to the next `## `, stripped."""
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(title), text, re.M | re.S)
    return m.group(1).strip() if m else ""


def tickets_source(text: str) -> str:
    """The first line under `## Tickets`: a folder of ticket files or `gh:…`, or ""."""
    for line in section(text, "Tickets").splitlines():
        line = line.strip().strip("`").strip()
        if line:
            return line
    return ""


def next_items(text: str) -> list:
    """Every non-blank line of `## Next, in priority order`: what the pulse hands
    an idle worker when there is no ticket graph."""
    return [ln for ln in section(text, "Next, in priority order").splitlines() if ln.strip()]


ITEM_RE = re.compile(r"^(\d+[.)]|[-*+])\s")


def next_count(text: str) -> int:
    """How many items `## Next` queues: lines that start a list item at the margin.
    A wrapped or nested line belongs to the item above it."""
    return sum(1 for ln in next_items(text) if ITEM_RE.match(ln))


def unmet(text: str) -> list:
    """The `- [ ]` criteria under `## Done when`, without the box."""
    return [ln[6:] for ln in section(text, "Done when").splitlines() if ln.startswith("- [ ]")]


# ----------------------------------------------------------- command line

USAGE = "usage: objective.py {status|tickets|next-count|set-body} FILE | set-status FILE VALUE"


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(".%s.tmp%d" % (path.name, os.getpid()))
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv) -> int:
    reads = {"status": status, "tickets": tickets_source,
             "next-count": next_count}
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if not ((cmd in reads or cmd == "set-body") and len(args) == 1
            or cmd == "set-status" and len(args) == 2):
        print(USAGE, file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print("objective: cannot read %s: %s" % (path, e.strerror), file=sys.stderr)
        return 1
    if cmd in reads:
        print(reads[cmd](text))
        return 0
    _write(path, set_status(text, args[1]) if cmd == "set-status" else with_body(text, sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
