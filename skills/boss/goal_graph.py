#!/usr/bin/env python3
"""The ticket graph at the top of a goal page, kept up to date (goal-graph ticket 01).

A goal with a `## Tickets` source gets a section `## Ticket graph` right under its
`# Objective` heading and `_Status:` line. Inside it, between two marker comments,
a mermaid flowchart drawn from `frontier.py`'s classification, by fixed rules:

  - one node per ticket, in ticket order, id `t<num>`, label `<num> · <title>` (title
    cut at 48 characters) and on a second line the state: `ready`, the worker's name
    for a claimed ticket, `waiting`, `done`
  - one edge per Blocked by within the source; an external blocker is a dashed node
    of its own, `x<n>`, with a dashed edge to the ticket
  - colours by state only, the same five classes in every goal
  - one summary line under the diagram, with the time of the read

Only this module writes between the markers; nothing outside them is touched. The
same frontier gives the same bytes, and the file is written only when the block
differs from what is there, the read time aside: an unchanged frontier never
reloads the sheaf page nor re-renders the diagram. A broken source keeps the last
diagram and puts the error on the summary line. A section moved elsewhere by hand
stays where it was put.

The write swaps the block in the text read under a lock, then checks the file still
holds that text just before the rename, and starts again once if not: the owner
edits this page in sheaf while the pulse writes it.

Who calls it:

  boss-pulse.py   update(track) on every Stop of an open track's boss (cache only)
  frontier.py     `goal_graph.py source <source>` after a claim it made
  the timer       `goal_graph.py sweep` every minute (boss-goal-graph.timer)

Command line (exit 0, also when a track cannot be read, which goes to stderr;
2 on a bad call):

    goal_graph.py track <track>     update one track, print written or unchanged
    goal_graph.py source <source>   update every open track whose tickets are <source>
    goal_graph.py sweep             update every open track
"""
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402
import objective  # noqa: E402

FRONTIER_PY = Path(__file__).resolve().parent.parent / "hand-to-boss" / "frontier.py"

HEADING = "## Ticket graph"
START = "<!-- ticket-graph:start (written by claude-boss from the Tickets source; edits here are overwritten) -->"
END = "<!-- ticket-graph:end -->"
START_RE = re.compile(r"^<!-- ticket-graph:start\b.*-->\s*$")
END_RE = re.compile(r"^<!-- ticket-graph:end\b.*-->\s*$")
SECTION_RE = re.compile(r"^##\s+Ticket graph\s*%s\s*$" % objective.HEAD_TAIL)
SUMMARY_RE = re.compile(r"^(\d+ tickets: .*?) · read \d{2}:\d{2}$|^(Ticket source unreadable) at \d{2}:\d{2}(: .*)$")

TITLE_MAX = 48
GH_STALE_S = 120        # the sweep reads a GitHub graph again when its cache is older
GH_READ_S = 30
LOCK_NAME = ".goal-graph.lock"

# Light fills with dark text: readable on sheaf's light and dark theme alike.
CLASSES = (
    ("done", "fill:#d4f0da,stroke:#2e7d32,color:#16361c"),
    ("claimed", "fill:#d6e5fa,stroke:#1f5fb4,color:#0e2a52"),
    ("ready", "fill:#fbe8c0,stroke:#b7791f,color:#46300a"),
    ("waiting", "fill:#e4e4e4,stroke:#777777,color:#2b2b2b"),
    ("external", "fill:#f9dada,stroke:#c62828,color:#560f0f,stroke-dasharray:5 3"),
)
LINKS = "stroke:#8a8a8a,stroke-width:2px"   # mermaid's own edge grey vanishes on a dark page


def _label(text):
    """Text safe inside a quoted mermaid label: no quotes, backticks or angle brackets."""
    text = re.sub(r"[\"`<>]", "", " ".join(str(text).split()))
    return text.replace("#", "＃")      # `#name;` is an entity code in a mermaid label


def _cut(text, n=TITLE_MAX):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _worker(claimed_by):
    """`Farid 2026-10-27 12:16` (a folder claim) or `Farid` (a GitHub label) -> `Farid`."""
    return (claimed_by or "").split()[0] if (claimed_by or "").split() else "claimed"


def diagram(out):
    """The mermaid block for one `frontier.py --json` output, as lines."""
    tickets = out["tickets"]
    nums = {t["num"] for t in tickets}
    lines = ["```mermaid", "flowchart TD"]
    by_class = {name: [] for name, _ in CLASSES}
    externals = {}
    for t in tickets:
        state = t["state"]
        word = _worker(t["claimed_by"]) if state == "claimed" else state
        lines.append('  t%s["%s · %s<br/>%s"]' % (t["num"], t["num"], _label(_cut(t["title"])), _label(word)))
        by_class[state if state in by_class else "waiting"].append("t" + t["num"])
        for e in t["external"]:
            externals.setdefault(e, "x%d" % (len(externals) + 1))
    for what, xid in externals.items():
        lines.append('  %s["%s<br/>external"]' % (xid, _label(_cut(what, 60))))
        by_class["external"].append(xid)
    for t in tickets:
        for b in t["blocked_by"]:
            if b in nums:
                lines.append("  t%s --> t%s" % (b, t["num"]))
        for e in t["external"]:
            lines.append("  %s -.-> t%s" % (externals[e], t["num"]))
    if any("-->" in ln or "-.->" in ln for ln in lines):
        lines.append("  linkStyle default %s" % LINKS)
    for name, style in CLASSES:
        lines.append("  classDef %s %s" % (name, style))
    for name, _ in CLASSES:
        if by_class[name]:
            lines.append("  class %s %s" % (",".join(by_class[name]), name))
    lines.append("```")
    return lines


def summary(out, now):
    count = lambda s: sum(1 for t in out["tickets"] if t["state"] == s)
    return "%d tickets: %d done, %d in progress, %d ready, %d waiting · read %s" % (
        len(out["tickets"]), count("done"), count("claimed"), count("ready"), count("waiting"),
        time.strftime("%H:%M", time.localtime(now)))


def block(out, now, error=None, old=None):
    """The whole block between and including the markers, as lines.

    With `error`, the diagram of `old` (the block there now) is kept and the summary
    line names the error; with no old diagram the block is that line alone."""
    if error is None:
        body = diagram(out) + ["", summary(out, now)]
    else:
        kept = _old_diagram(old or [])
        line = "Ticket source unreadable at %s: %s" % (
            time.strftime("%H:%M", time.localtime(now)), " ".join(str(error).split())[:300])
        body = kept + ([""] if kept else []) + [line]
    return [START] + body + [END]


def _old_diagram(old):
    """The mermaid lines of an existing block, fence to fence, or []."""
    try:
        a = old.index("```mermaid")
        b = old.index("```", a + 1)
    except ValueError:
        return []
    return old[a:b + 1]


def _timeless(lines):
    """A block with the read time taken out of its summary line, for comparison."""
    keep = []
    for ln in lines:
        m = SUMMARY_RE.match(ln)
        keep.append((m.group(1) or (m.group(2) + m.group(3))) if m else ln)
    return keep


def _span(lines):
    """(start, end) indices of the marker lines, or None when there is no whole block."""
    s = next((i for i, ln in enumerate(lines) if START_RE.match(ln)), None)
    if s is None:
        return None
    e = next((i for i in range(s + 1, len(lines)) if END_RE.match(lines[i])), None)
    return None if e is None else (s, e)


def _top(lines):
    """Where a new section goes: after the `# ` heading and its `_Status:` line, before
    the first `## `; at the very top when there is no heading."""
    h = objective._heading_at(lines)
    if h < 0:
        return 0
    i = h + 1
    j = i
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j < len(lines) and lines[j].startswith("_Status:"):
        i = j + 1
    return i


def place(text, make):
    """`text` with its graph block replaced, or a new section inserted at the top.

    `make(old_block_lines_or_None)` returns the new block's lines. An unchanged block,
    the read time aside, gives `text` back as it was."""
    lines = text.split("\n")
    span = _span(lines)
    if span:
        s, e = span
        old = lines[s:e + 1]
        new = make(old)
        if _timeless(new) == _timeless(old):
            return text
        return "\n".join(lines[:s] + new + lines[e + 1:])
    new = make(None)
    head = next((i for i, ln in enumerate(lines) if SECTION_RE.match(ln)), None)
    if head is not None:                    # the heading is there, the block is not
        return "\n".join(lines[:head + 1] + [""] + new + lines[head + 1:])
    at = _top(lines)
    before = lines[:at]
    after = lines[at:]
    while after and not after[0].strip():
        after = after[1:]
    return "\n".join(before + ["", HEADING, ""] + new + [""] + after)


# ------------------------------------------------------------------ reading

def _frontier_module():
    spec = importlib.util.spec_from_file_location("frontier", str(FRONTIER_PY))
    fr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fr)
    return fr


def read(source, track, fetch=True, cfg=None):
    """(frontier output, error) for a source. A folder is read now; a GitHub graph from
    the pulse's cache, read again first when `fetch` and the cache is older than
    GH_STALE_S (a failed read never replaces the cache)."""
    if source.startswith("gh:"):
        cache = boss_store.frontier_cache(track, source, cfg)
        try:
            age = time.time() - cache.stat().st_mtime
        except OSError:
            age = None
        if fetch and (age is None or age > GH_STALE_S):
            try:
                r = subprocess.run([sys.executable, str(FRONTIER_PY), "--json", source],
                                   capture_output=True, text=True, timeout=GH_READ_S)
                if r.returncode == 0:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cache.with_suffix(".tmp%d" % os.getpid())
                    tmp.write_text(r.stdout, encoding="utf-8")
                    os.replace(tmp, cache)
                elif age is None:
                    return None, (r.stderr or r.stdout).strip() or "frontier.py exit %d" % r.returncode
            except (subprocess.SubprocessError, OSError) as exc:
                if age is None:
                    return None, str(exc)
        try:
            text = cache.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, None               # nothing read yet: no graph, no error
        try:
            out = json.loads(text)
            out["tickets"]
            return out, None
        except (ValueError, KeyError, TypeError):
            return None, text.strip()[:300] or "empty frontier cache"
    fr = _frontier_module()
    folder = os.path.expanduser(source)
    try:
        tickets, errors = fr.load(folder)
    except OSError as exc:
        return None, str(exc)
    if tickets is None or errors:
        return None, "; ".join(errors) or "no tickets"
    return fr.classify(tickets), None


# ------------------------------------------------------------------ writing

def _write_if_same(path, expected, text):
    """Write `text` over `path` unless the file no longer holds `expected`. True when written."""
    path = path.resolve()
    tmp = path.with_name(".%s.graph%d" % (path.name, os.getpid()))
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode & 0o7777)
        if path.read_text(encoding="utf-8") != expected:
            return False
        os.replace(tmp, path)
        return True
    finally:
        tmp.unlink(missing_ok=True)


def update(track, fetch=True, now=None, cfg=None):
    """Bring one track's graph up to date. Returns "written", "unchanged" or "none"
    (no goal, no Tickets source, or a GitHub graph nobody has read yet).

    The frontier is read before the lock is taken: a GitHub read may take
    GH_READ_S, and the pulse, which waits on the same lock, has 5 s in all."""
    path = boss_store.objective_path(track, cfg)
    if path is None:
        return "none"
    try:
        source = objective.tickets_source(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return "none"
    if not source:
        return "none"
    out, error = read(source, track, fetch=fetch, cfg=cfg)
    if out is None and error is None:
        return "none"
    at = time.time() if now is None else now
    lock_dir = boss_store.state_dir(cfg)
    lock = None
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = open(lock_dir / LOCK_NAME, "a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    except OSError:
        if lock is not None:
            lock.close()
        lock = None
    try:
        for _ in range(2):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return "none"
            if objective.tickets_source(text) != source:
                return "unchanged"           # the source moved meanwhile: the next run draws it
            new = place(text, lambda old: block(out, at, error, old))
            if new == text:
                return "unchanged"
            if _write_if_same(path, text, new):
                return "written"
        return "unchanged"                   # changed under us twice: the next run catches up
    finally:
        if lock is not None:
            lock.close()


def _open_tracks(cfg=None):
    for track, _, text, reason in boss_store.open_tracks(cfg):
        if reason is None and objective.is_open(text) and objective.tickets_source(text):
            yield track, objective.tickets_source(text)


def _same_source(a, b):
    if a.startswith("gh:") or b.startswith("gh:"):
        return a == b
    try:
        return Path(os.path.expanduser(a)).resolve() == Path(os.path.expanduser(b)).resolve()
    except OSError:
        return False


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "track" and len(argv) == 2:
        tracks = [argv[1]]
    elif cmd == "source" and len(argv) == 2:
        tracks = [t for t, s in _open_tracks() if _same_source(s, argv[1])]
    elif cmd == "sweep" and len(argv) == 1:
        tracks = [t for t, _ in _open_tracks()]
    else:
        print(next(p for p in __doc__.split("\n\n") if "goal_graph.py track" in p), file=sys.stderr)
        return 2
    for track in tracks:
        try:
            result = update(track)
        except Exception as exc:            # one bad track never stops the others
            print("goal_graph: %s: %s" % (track, exc), file=sys.stderr)
            continue
        if cmd == "track":
            print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
