#!/usr/bin/env python3
"""Read a folder of tickets and say which ones a boss may hand out now.

The tickets are the local-file format `to-tickets` writes: one `NN-slug.md`
per ticket, first line `# NN: title`, a `**Blocked by:**` field (inline, or a
bullet list under it), a `**Status:**` line and, once a worker has taken it, a
`**Claimed by:**` line.

A blocker is either another ticket (`- 03: title`, or `03, 05` inline) or
something outside the team (`- External: who does what`). A ticket is:

  done      Status is done
  claimed   a Claimed by line is present and it is not done
  ready     every ticket it waits on is done, nothing external is open
  waiting   anything else

Usage:
    frontier.py <issues-dir>           the frontier as text, for the brief
    frontier.py --json <issues-dir>    the same, as JSON

Exit 2 when the input is not a ticket set: no ticket files, a ticket with no
Blocked by field, or a reference to a ticket that does not exist. That is the
hand-to-boss input check; a boss started on a broken graph works the wrong
frontier.
"""
import json
import re
import sys
from pathlib import Path

FIELD = re.compile(r"^\*\*([A-Za-z ]+):\*\*\s*(.*)$")
TICKET_FILE = re.compile(r"^(\d{1,3})-.*\.md$")
NUMBER = re.compile(r"(?<![\w.:/-])(\d{1,3})\b(?![.:/-]\d)")


def parse(path):
    lines = path.read_text().splitlines()
    t = {"num": TICKET_FILE.match(path.name).group(1), "file": path.name,
         "title": "", "status": "", "claimed_by": "", "blocked_raw": None}
    if lines and lines[0].startswith("# "):
        t["title"] = lines[0][2:].split(":", 1)[-1].strip()
    i = 0
    while i < len(lines):
        m = FIELD.match(lines[i].strip())
        if m:
            key, val = m.group(1).strip().lower(), m.group(2).strip()
            if key == "blocked by":
                items = [val] if val else []
                j = i + 1
                while j < len(lines) and (lines[j].strip().startswith("- ") or not lines[j].strip()):
                    if lines[j].strip().startswith("- "):
                        items.append(lines[j].strip()[2:].strip())
                    elif items and j + 1 < len(lines) and not lines[j + 1].strip().startswith("- "):
                        break
                    j += 1
                t["blocked_raw"] = items
                i = j
                continue
            if key == "status":
                t["status"] = val.lower()
            elif key == "claimed by":
                t["claimed_by"] = val
        i += 1
    return t


def split_blockers(items):
    internal, external = [], []
    for item in items:
        if re.match(r"(?i)^external\b", item):
            external.append(re.sub(r"(?i)^external\s*:?\s*", "", item))
        elif re.match(r"(?i)^none\b", item):
            continue
        else:
            internal += NUMBER.findall(item)
    return internal, external


def frontier(folder):
    files = sorted(p for p in Path(folder).glob("*.md") if TICKET_FILE.match(p.name))
    if not files:
        return None, ["no ticket files (NN-slug.md) in %s" % folder]
    tickets = [parse(p) for p in files]
    known = {t["num"].zfill(2) for t in tickets}
    errors = []
    for t in tickets:
        if t["blocked_raw"] is None:
            errors.append("%s: no **Blocked by:** field" % t["file"])
            t["blocked_by"], t["external"] = [], []
            continue
        internal, t["external"] = split_blockers(t["blocked_raw"])
        t["blocked_by"] = [n.zfill(2) for n in internal]
        for n in t["blocked_by"]:
            if n not in known:
                errors.append("%s: blocked by %s, which has no ticket file" % (t["file"], n))
    state = {t["num"].zfill(2): t for t in tickets}
    for t in tickets:
        if t["status"] == "done":
            t["state"] = "done"
        elif t["claimed_by"]:
            t["state"] = "claimed"
        elif t["external"] or any(state.get(n, {}).get("status") != "done" for n in t["blocked_by"]):
            t["state"] = "waiting"
        else:
            t["state"] = "ready"
    out = {
        "tickets": [{k: t[k] for k in ("num", "file", "title", "status", "state",
                                        "claimed_by", "blocked_by", "external")} for t in tickets],
        "ready": [t["num"] for t in tickets if t["state"] == "ready"],
        "external": [{"num": t["num"], "what": e} for t in tickets
                     if t["state"] != "done" for e in t["external"]],
    }
    return out, errors


def as_text(out):
    by = lambda s: [t for t in out["tickets"] if t["state"] == s]
    rows = ["Ready now: " + (", ".join(out["ready"]) or "none")]
    for t in by("ready"):
        rows.append("  %s  %s" % (t["num"], t["title"]))
    claimed = by("claimed")
    if claimed:
        rows.append("Claimed: " + ", ".join("%s (%s)" % (t["num"], t["claimed_by"]) for t in claimed))
    waiting = [t for t in by("waiting") if t["blocked_by"]]
    if waiting:
        rows.append("Waiting on other tickets:")
        rows += ["  %s  after %s" % (t["num"], ", ".join(t["blocked_by"])) for t in waiting]
    if out["external"]:
        rows.append("External blockers:")
        rows += ["  %s: %s" % (e["num"], e["what"]) for e in out["external"]]
    done = by("done")
    rows.append("Done: " + (", ".join(t["num"] for t in done) or "none"))
    return "\n".join(rows)


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if len(args) != 1:
        print(__doc__.strip().split("\n\n")[-2], file=sys.stderr)
        return 1
    out, errors = frontier(args[0])
    for e in errors:
        print("frontier: " + e, file=sys.stderr)
    if out is None or errors:
        return 2
    print(json.dumps(out, indent=2) if as_json else as_text(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
