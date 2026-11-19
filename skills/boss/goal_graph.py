#!/usr/bin/env python3
"""The ticket graph at the top of a goal page, kept up to date (goal-graph ticket 01).

A goal with a `## Tickets` source gets a section `## Ticket graph` right under its
`# Objective` heading and `_Status:` line. Inside it, between two marker comments,
a mermaid flowchart drawn from `frontier.py`'s classification, by fixed rules:

  - one node per ticket, in ticket order, id `t<num>`, label `<num> · <title>` (title
    cut at 48 characters) and on a second line the state with its sign: `○ ready`,
    the worker's name for a claimed ticket, `⏸ waiting`, `✅ done`; a claimed ticket's
    worker carries 🔨 (a turn in flight), 🧪 (a job of its own open) or 🔍 (a review
    running) when the activity feed says so, and nothing at rest
  - one edge per Blocked by within the source; an external blocker is a dashed node
    of its own, `x<n>`, with a dashed edge to the ticket
  - colours by state only, the same five classes in every goal
  - one summary line under the diagram, with the time of the read

The activity feed is optional: a URL in `<pm>/goal-graph.signs-url` that answers
`{"signs": {track: {name: "busy"|"watching"|"reviewing"}}}` (agentview's
`/api/signs`). No file, or no answer within SIGNS_S, draws the names without signs.

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

  boss-pulse.py   update(track) after it read the track's tickets, on every Stop of
                  an open track's boss (a GitHub graph from the cache it just read)
  frontier.py     `goal_graph.py source <source>` after a claim it made
  the timer       `goal_graph.py sweep` every minute (boss-goal-graph.timer)

Command line (exit 0, also when a track cannot be read, which goes to stderr;
2 on a bad call):

    goal_graph.py track <track>     update one track, print written or unchanged
    goal_graph.py source <source>   update every open track whose tickets are <source>,
                                    reading a GitHub graph again whatever its cache's age
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
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402
import objective  # noqa: E402
import pulse  # noqa: E402

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
SIGNS_FILE = "goal-graph.signs-url"
SIGNS_S = 1             # the pulse has 5 s in all; a feed slower than this draws no signs
WORKER_SIGNS = {"busy": "🔨", "watching": "🧪", "reviewing": "🔍"}
STATE_SIGNS = {"ready": "○", "waiting": "⏸", "done": "✅"}
_FEED = {}              # url -> the feed's signs, read once per process (the sweep draws every track)
LOCK_NAME = ".goal-graph.lock"   # its own: the pulse's state lock is held for milliseconds, a goal write may wait on a slow disk

# Light fills with dark text: readable on sheaf's light and dark theme alike.
CLASSES = (
    ("done", "fill:#d4f0da,stroke:#2e7d32,color:#16361c"),
    ("claimed", "fill:#d6e5fa,stroke:#1f5fb4,color:#0e2a52"),
    ("ready", "fill:#fbe8c0,stroke:#b7791f,color:#46300a"),
    ("waiting", "fill:#e4e4e4,stroke:#777777,color:#2b2b2b"),
    ("external", "fill:#f9dada,stroke:#c62828,color:#560f0f,stroke-dasharray:5 3"),
)


def _label(text):
    """Text safe inside a quoted mermaid label: no quotes, backticks or angle brackets."""
    text = re.sub(r"[\"`<>]", "", " ".join(str(text).split()))
    return text.replace("#", "＃")      # `#name;` is an entity code in a mermaid label


def _cut(text, n=TITLE_MAX):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _worker(claimed_by):
    """`Farid 2026-10-27 12:16` (a folder claim) or `Farid` (a GitHub label) -> `Farid`."""
    words = (claimed_by or "").split()
    return words[0] if words else "claimed"


def activity(track, cfg=None):
    """`{name casefolded: sign glyph}` of the track's workers doing something now, from
    the feed named in SIGNS_FILE; empty when there is none or it does not answer. The
    feed gives one sign per worker, already ordered (review beats a turn, which beats a job)."""
    try:
        url = (boss_store.pm_dir(cfg) / SIGNS_FILE).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    if not re.match(r"https?://", url):
        return {}
    if url not in _FEED:
        try:
            with urllib.request.urlopen(url, timeout=SIGNS_S) as r:
                got = json.loads(r.read(1 << 20)).get("signs")
            _FEED[url] = got if isinstance(got, dict) else {}
        except Exception:            # http.client's errors are no OSError; a feed never fails a write
            _FEED[url] = {}
    mine = _FEED[url].get(track)
    return {str(n).casefold(): WORKER_SIGNS[s] for n, s in mine.items() if s in WORKER_SIGNS} \
        if isinstance(mine, dict) else {}


def _second_line(t, signs):
    """`🔨 Farid` for a claimed ticket (no sign at rest), `✅ done` and the like for the rest."""
    if t["state"] == "claimed":
        name = _worker(t["claimed_by"])
        sign = signs.get(name.casefold())
        return "%s %s" % (sign, name) if sign else name
    sign = STATE_SIGNS.get(t["state"])
    return "%s %s" % (sign, t["state"]) if sign else t["state"]


def diagram(out, signs=None):
    """The mermaid block for one `frontier.py --json` output, as lines. `signs` is
    `activity`'s answer."""
    tickets = out["tickets"]
    nums = {t["num"] for t in tickets}
    lines = ["```mermaid", "flowchart TD"]
    by_class = {name: [] for name, _ in CLASSES}
    externals = {}
    for t in tickets:
        state = t["state"]
        word = _second_line(t, signs or {})
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
    # No linkStyle and no %%{init}%% line: the edges keep mermaid's own colour, and the block
    # carries only what the spec names (removed in 0.29.1 while chasing a page that would not load).
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


def block(out, now, error=None, old=None, signs=None):
    """The whole block between and including the markers, as lines.

    With `error`, the diagram of `old` (the block there now) is kept and the summary
    line names the error; with no old diagram the block is that line alone."""
    if error is None:
        body = diagram(out, signs) + ["", summary(out, now)]
    else:
        kept = _old_diagram(old or [])
        line = "Ticket source unreadable at %s: %s" % (
            time.strftime("%H:%M", time.localtime(now)), _label(str(error))[:300])
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
    """(start, end) indices of the marker lines, or None when there is no whole block.

    The first end marker with the start marker nearest above it, both outside a
    code fence: a stray start marker higher up (a section half deleted, a fenced
    example) never takes the owner's text between it and the block with it."""
    s, fenced = None, False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            fenced = not fenced
        elif fenced:
            continue
        elif START_RE.match(ln):
            s = i
        elif END_RE.match(ln) and s is not None:
            return s, i
    return None


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
    at = objective.top_at(lines)
    before = lines[:at]
    after = lines[at:]
    while after and not after[0].strip():
        after = after[1:]
    return "\n".join(before + ["", HEADING, ""] + new + [""] + after)


# ------------------------------------------------------------------ reading

def read(source, track, fetch=True, cfg=None, stale=GH_STALE_S):
    """(frontier output, error) for a source; (None, None) for a GitHub graph nobody
    has read yet. A folder is read now, as frontier.py reads it; a GitHub graph from
    the cache the pulse keeps, read again first when `fetch` and the cache is older
    than GH_STALE_S. A failed read keeps the cached frontier and returns its error."""
    if source.startswith("gh:"):
        failed = None
        if fetch:
            _, _, age = boss_store.cached_frontier(track, source, cfg)
            if age is None or age > stale:
                try:
                    failed = boss_store.refresh_frontier(track, source, pulse.FRONTIER_PY, GH_READ_S, cfg)
                except (subprocess.SubprocessError, OSError) as exc:
                    failed = str(exc)
        out, error, age = boss_store.cached_frontier(track, source, cfg)
        if age is None:
            return None, None
        return out, error or failed
    spec = importlib.util.spec_from_file_location("frontier", str(pulse.FRONTIER_PY))
    fr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fr)
    try:
        tickets, errors = fr.load(os.path.expanduser(source))
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


def update(track, fetch=True, now=None, cfg=None, stale=GH_STALE_S):
    """Bring one track's graph up to date. Returns "written"; "unchanged"; "deferred"
    when the goal changed under the write (its source moved, or its text changed
    twice), for the next run; or "none" (no goal, no Tickets source, or a GitHub
    graph nobody has read yet).

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
    out, error = read(source, track, fetch=fetch, cfg=cfg, stale=stale)
    if out is None and error is None:
        return "none"
    at = time.time() if now is None else now
    signs = activity(track, cfg)
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
                return "deferred"            # the source moved meanwhile: the next run draws it
            new = place(text, lambda old: block(out, at, error, old, signs))
            if new == text:
                return "unchanged"
            if _write_if_same(path, text, new):
                return "written"
        return "deferred"                    # changed under us twice: the next run catches up
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
        # folders first: they take milliseconds, a GitHub graph up to GH_READ_S
        tracks = [t for t, s in sorted(_open_tracks(), key=lambda ts: ts[1].startswith("gh:"))]
    else:
        print(next(p for p in __doc__.split("\n\n") if "goal_graph.py track" in p), file=sys.stderr)
        return 2
    for track in tracks:
        try:
            result = update(track, stale=0 if cmd == "source" else GH_STALE_S)
        except Exception as exc:            # one bad track never stops the others
            print("goal_graph: %s: %s" % (track, exc), file=sys.stderr)
            continue
        if cmd == "track":
            print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
