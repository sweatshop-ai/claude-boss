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
    with_body(text, body)       `body` under the heading and the status line,
                                the sheaf comments it drops kept at the end
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


COMMENT_OPEN_RE = re.compile(r"<!--\s*(?:sheaf|rd)-comment\b")
# What sheaf glues to the end of a heading line: whole comments, on that one line.
HEAD_TAIL = r"(?:<!--\s*(?:sheaf|rd)-comment\b[^\n]*?-->)*"


def comment_blocks(text: str) -> list:
    """Every sheaf comment in `text`, byte for byte: from `<!-- sheaf-comment` (or
    the older `rd-comment`) to the first `-->`. sheaf writes a `--` inside a
    comment as `-&#45;`, so that is its end. The contents are not read. A block
    that never closes is a ValueError: where it ends is a guess."""
    out, at = [], 0
    while True:
        m = COMMENT_OPEN_RE.search(text, at)
        if not m:
            return out
        end = text.find("-->", m.end())
        if end < 0:
            raise ValueError("a sheaf comment opens and never closes (`<!-- sheaf-comment` "
                             "without `-->`); close it by hand before rewriting this goal")
        out.append(text[m.start():end + 3])
        at = end + 3


def lost_comments(dropped: str, kept: str) -> list:
    """The comment blocks of `dropped` that `kept` does not already hold, as many
    times over as they stand in `dropped`. A body from `boss-goal show` holds its
    blocks, so they are not carried twice."""
    have = comment_blocks(kept)
    lost = []
    for b in comment_blocks(dropped):
        if b in have:
            have.remove(b)
        else:
            lost.append(b)
    return lost


HEADING_LINE_RE = re.compile(r"^#{2,6}\s")


def _reglue(old_lines, body: str) -> str:
    """`body` with the comments glued to a heading of `old_lines` glued to the
    same heading of `body`, byte for byte. A comment on a heading line that
    `body` does not have again, or has with another comment already glued to it,
    cannot stay where it was and is not moved elsewhere: a ValueError."""
    new = body.split("\n")
    for ln in old_lines:
        if not HEADING_LINE_RE.match(ln) or not COMMENT_OPEN_RE.search(ln):
            continue
        try:
            blocks = comment_blocks(ln)
        except ValueError:
            raise ValueError("a sheaf comment glued to the heading %r runs over more than one "
                             "line (sheaf writes it on one); put it on one line by hand before "
                             "rewriting this goal" % ln.split("<!--", 1)[0].strip()) from None
        if not lost_comments(ln, body):
            continue
        text = ln.split("<!--", 1)[0].rstrip()
        tail = ln[len(text):]
        rest = tail
        for b in blocks:
            rest = rest.replace(b, "", 1)
        at = [i for i, b in enumerate(new) if b.rstrip() == text]
        if rest.strip() or len(at) != 1:
            raise ValueError("a sheaf comment is glued to the heading %r, which the new body "
                             "does not have exactly once; keep that heading line (as `boss-goal "
                             "show` prints it) or move the comment by hand" % text)
        new[at[0]] = text + tail
    return "\n".join(new)


def with_body(text: str, body: str) -> str:
    """`body` under the header of `text`: its `# ` heading and its status line,
    in the order they stand. The status stays as it was; only `set_status`
    changes it. The sheaf comments of the lines it drops go at the end."""
    lines = text.splitlines()
    keep = {_heading_at(lines)}
    keep.add(next((i for i, ln in enumerate(lines) if ln.startswith("_Status:")), -1))
    head = [lines[i] for i in sorted(keep) if i >= 0]
    rest = [ln for i, ln in enumerate(lines) if i not in keep]
    body = _reglue(rest, body)
    dropped = "\n".join(rest)
    lost = lost_comments(dropped, "\n".join(head + [body]))
    return "\n".join(head + [body.rstrip("\n")] + ([""] + lost if lost else [])) + "\n"


# --------------------------------------------------------------- sections

def section(text: str, title: str) -> str:
    """The body of `## <title>`, up to the next `## `, stripped."""
    m = re.search(r"^##\s+%s\s*%s\s*$(.*?)(?=^##\s|\Z)" % (re.escape(title), HEAD_TAIL),
                  text, re.M | re.S)
    return m.group(1).strip() if m else ""


def _section_span(lines, title):
    """(first, end) line indices of `## <title>`'s body, or None."""
    head = re.compile(r"^##\s+%s\s*%s\s*$" % (re.escape(title), HEAD_TAIL))
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
    it stay. A file without the section gets it at the end. The sheaf comments of
    the lines it replaces stay at the end of the section."""
    lines = text.split("\n")
    span = _section_span(lines, NEXT)
    new = body.rstrip("\n").split("\n")
    if span is None:
        return text.rstrip("\n") + "\n\n## %s\n%s\n" % (NEXT, "\n".join(new))
    first, end = span
    tail = lines[end:]
    lost = lost_comments("\n".join(lines[first:end]), body)
    return "\n".join(lines[:first] + new + ([""] + lost if lost else [])
                     + ([""] + tail if tail else [""]))


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
        try:
            new = with_body(text, body) if cmd == "set-body" else set_next(text, body)
        except ValueError as e:
            print("objective: %s: %s" % (path, e), file=sys.stderr)
            return 1
    try:
        _write(path, new)
    except OSError as e:
        print("objective: cannot write %s: %s" % (path, e.strerror), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
