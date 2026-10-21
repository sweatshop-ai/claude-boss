#!/usr/bin/env python3
"""Read a folder of tickets, say which ones a boss may hand out now, and claim one.

The tickets are the local-file format `to-tickets` writes: one `NN-slug.md`
per ticket, first line `# NN: title`, a `**Blocked by:**` field (inline, or a
bullet list under it), a `**Status:**` line and, once the boss has handed it
out, a `**Claimed by:**` line.

A blocker is either another ticket (`- 03: title`, or `03, 05` inline; only
the leading id of each item counts) or something outside the team
(`- External: who does what`). Ids are compared in one form, two digits
(`1`, `01` and `001` are the same ticket). A ticket is:

  done      Status starts with the word done
  claimed   a Claimed by line is present and it is not done
  ready     every ticket it waits on is done, nothing external is open
  waiting   anything else

A source can also be `gh:owner/repo#N`: the sub-issues of issue N are the
tickets, GitHub's native issue dependencies are the Blocked by, a closed issue
is done, and a `worker:<name>` label is the claim (every worker writes as one
GitHub account, so the assignee cannot say who). An open blocker outside the
sub-issues is external.

Usage:
    frontier.py <issues-dir>                     the frontier as text, for the brief
    frontier.py --json <issues-dir>              the same, as JSON
    frontier.py claim <issues-dir> <NN> <name>   write the claim line, set in-progress
    frontier.py claim gh:owner/repo#N <issue> <name>   label the issue worker:<name>

Exit 2 when the input is not a ticket graph: no ticket files, a file that is
not UTF-8, a ticket with no Blocked by field, a reference to a ticket that
does not exist, a ticket that blocks itself, or a cycle. A boss started on a
broken graph works the wrong frontier, or waits for ever.

`claim` exits 3 when the ticket is not ready: already claimed (the claimant is
named), done, or still blocked. It writes only that one file, under a lock,
and leaves committing it to the caller.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

FIELD = re.compile(r"^\*\*([A-Za-z ]+):\*\*\s*(.*)$")
TICKET_FILE = re.compile(r"^(\d{1,3})-.*\.md$")
LEADING_ID = re.compile(r"^\s*#?(\d{1,3})\b(?![.:/-]\d)")


def tid(raw):
    """The one form a ticket id takes everywhere: at least two digits."""
    return str(int(raw)).zfill(2)


class BadInput(Exception):
    pass


def parse(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as e:
        raise BadInput("%s: not UTF-8 (byte %d)" % (path.name, e.start))
    t = {"num": tid(TICKET_FILE.match(path.name).group(1)), "file": path.name,
         "path": path, "title": "", "status": "", "claimed_by": "", "blocked_raw": None}
    if lines and lines[0].startswith("# "):
        t["title"] = lines[0][2:].split(":", 1)[-1].strip()
    i = 0
    while i < len(lines):
        m = FIELD.match(lines[i].strip())
        if m:
            key, val = m.group(1).strip().lower(), m.group(2).strip()
            if key == "blocked by":
                # inline items are comma-separated; bullet items are one each,
                # commas and all, since a title may carry one
                items = [s for s in re.split(r"[,;]", val) if s.strip()] if val else []
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
                t["status"] = val
            elif key == "claimed by":
                t["claimed_by"] = val
        i += 1
    return t


def is_done(status):
    word = re.match(r"[\W_]*([A-Za-z-]+)", status or "")
    return bool(word) and word.group(1).lower() == "done"


def split_blockers(items):
    internal, external = [], []
    for item in items:
        item = item.strip()
        if re.match(r"(?i)^external\b", item):
            external.append(re.sub(r"(?i)^external\s*:?\s*", "", item))
            continue
        m = LEADING_ID.match(item)
        if m:
            internal.append(tid(m.group(1)))
    return internal, external


def find_cycle(edges):
    """One cycle in the blocked-by graph as a list of ids, or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in edges}
    stack = []

    def visit(n):
        colour[n] = GREY
        stack.append(n)
        for m in edges.get(n, []):
            if colour.get(m) == GREY:
                return stack[stack.index(m):] + [m]
            if colour.get(m) == WHITE:
                found = visit(m)
                if found:
                    return found
        stack.pop()
        colour[n] = BLACK
        return None

    for n in sorted(edges):
        if colour[n] == WHITE:
            found = visit(n)
            if found:
                return found
    return None


GH_SOURCE = re.compile(r"^gh:([\w.-]+/[\w.-]+)#(\d+)$")
WORKER_LABEL = "worker:"


def gh_api(*args):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise BadInput("gh api %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:200]))
    # --paginate prints one JSON document per page: read them all, join lists.
    docs, text, i = [], r.stdout.strip(), 0
    dec = json.JSONDecoder()
    while i < len(text):
        doc, i = dec.raw_decode(text, i)
        docs.append(doc)
        while i < len(text) and text[i].isspace():
            i += 1
    if len(docs) > 1 and all(isinstance(d, list) for d in docs):
        return [x for d in docs for x in d]
    return docs[0] if docs else None


def gh_ticket(repo, issue, blockers, members):
    """One sub-issue as a ticket. The claim is a `worker:<name>` label: every
    worker writes as the same GitHub account, so the assignee cannot say who."""
    claimed = next((l["name"][len(WORKER_LABEL):] for l in issue.get("labels") or []
                    if l.get("name", "").startswith(WORKER_LABEL)), "")
    internal = [str(b["number"]) for b in blockers if b["number"] in members]
    external = [b.get("html_url") or "#%d" % b["number"] for b in blockers
                if b["number"] not in members and b.get("state") == "open"]
    return {"num": str(issue["number"]), "file": "%s#%d" % (repo, issue["number"]),
            "path": None, "title": issue.get("title", ""),
            "status": "done" if issue.get("state") == "closed" else "open",
            "claimed_by": claimed, "blocked_raw": [], "blocked_by": internal,
            "external": external}


def load_github(repo, parent):
    """The sub-issues of issue `parent`, each blocked by GitHub's native issue
    dependencies (`issues/<n>/dependencies/blocked_by`)."""
    try:
        subs = gh_api("--paginate", "repos/%s/issues/%s/sub_issues" % (repo, parent))
        if not subs:
            return None, ["%s#%s has no sub-issues" % (repo, parent)]
        members = {s["number"] for s in subs}
        tickets = [gh_ticket(repo, s, gh_api("--paginate", "repos/%s/issues/%d/dependencies/blocked_by"
                                             % (repo, s["number"])) or [], members)
                   for s in subs]
    except (BadInput, subprocess.SubprocessError, OSError, ValueError) as e:
        return None, [str(e)]
    edges = {t["num"]: t["blocked_by"] for t in tickets}
    cycle = find_cycle(edges)
    return tickets, ["cycle in blocked-by: %s" % " -> ".join(cycle)] if cycle else []


def claim_github(repo, parent, num, name):
    """Label sub-issue `num` worker:<name>, only when the live graph says it is ready."""
    tickets, errors = load_github(repo, parent)
    if tickets is None or errors:
        for e in errors:
            print("frontier: " + e, file=sys.stderr)
        return 2
    classify(tickets)
    num = str(int(num))
    t = next((t for t in tickets if t["num"] == num), None)
    if t is None:
        print("frontier: %s is not a sub-issue of %s#%s" % (num, repo, parent), file=sys.stderr)
        return 2
    if t["state"] == "claimed":
        print("frontier: %s is already claimed by %s" % (num, t["claimed_by"]), file=sys.stderr)
        return 3
    if t["state"] != "ready":
        why = "done" if t["state"] == "done" else "blocked by %s" % ", ".join(
            t["open_blockers"] + ["external: " + e for e in t["external"]])
        print("frontier: %s is not ready (%s)" % (num, why), file=sys.stderr)
        return 3
    label = WORKER_LABEL + name
    try:
        # GitHub's docs do not say whether adding an unknown label creates it:
        # create it first, and an "already exists" refusal is fine.
        gh_api("-X", "POST", "repos/%s/labels" % repo, "-f", "name=" + label)
    except BadInput:
        pass
    try:
        gh_api("-X", "POST", "repos/%s/issues/%s/labels" % (repo, num), "-f", "labels[]=" + label)
    except (BadInput, subprocess.SubprocessError, OSError, ValueError) as e:
        print("frontier: %s" % e, file=sys.stderr)
        return 2
    print("https://github.com/%s/issues/%s" % (repo, num))
    return 0


def load(folder):
    gh = GH_SOURCE.match(str(folder))
    if gh:
        return load_github(*gh.groups())
    files = sorted(p for p in Path(folder).glob("*.md") if TICKET_FILE.match(p.name))
    if not files:
        return None, ["no ticket files (NN-slug.md) in %s" % folder]
    tickets, errors = [], []
    for p in files:
        try:
            tickets.append(parse(p))
        except BadInput as e:
            errors.append(str(e))
    seen = {}
    for t in tickets:
        if t["num"] in seen:
            errors.append("%s and %s: both are ticket %s" % (seen[t["num"]], t["file"], t["num"]))
        seen[t["num"]] = t["file"]
    for t in tickets:
        if t["blocked_raw"] is None:
            errors.append("%s: no **Blocked by:** field" % t["file"])
            t["blocked_by"], t["external"] = [], []
            continue
        t["blocked_by"], t["external"] = split_blockers(t["blocked_raw"])
        for n in t["blocked_by"]:
            if n == t["num"]:
                errors.append("%s: ticket %s blocks itself" % (t["file"], n))
            elif n not in seen:
                errors.append("%s: blocked by %s, which has no ticket file" % (t["file"], n))
    edges = {t["num"]: [n for n in t["blocked_by"] if n in seen and n != t["num"]] for t in tickets}
    cycle = find_cycle(edges)
    if cycle:
        errors.append("cycle in Blocked by: %s" % " -> ".join(cycle))
    return tickets, errors


def classify(tickets):
    by = {t["num"]: t for t in tickets}
    for t in tickets:
        t["open_blockers"] = [n for n in t["blocked_by"] if n in by and not is_done(by[n]["status"])]
        if is_done(t["status"]):
            t["state"] = "done"
        elif t["claimed_by"]:
            t["state"] = "claimed"
        elif t["external"] or t["open_blockers"]:
            t["state"] = "waiting"
        else:
            t["state"] = "ready"
    return {
        "tickets": [{k: t[k] for k in ("num", "file", "title", "status", "state", "claimed_by",
                                        "blocked_by", "open_blockers", "external")} for t in tickets],
        "ready": [t["num"] for t in tickets if t["state"] == "ready"],
        "external": [{"num": t["num"], "what": e} for t in tickets
                     if t["state"] != "done" for e in t["external"]],
    }


def as_text(out):
    by = lambda s: [t for t in out["tickets"] if t["state"] == s]
    rows = ["Ready now: " + (", ".join(out["ready"]) or "none")]
    for t in by("ready"):
        rows.append("  %s  %s" % (t["num"], t["title"]))
    claimed = by("claimed")
    if claimed:
        rows.append("Claimed: " + ", ".join("%s (%s)" % (t["num"], t["claimed_by"]) for t in claimed))
    waiting = [t for t in by("waiting") if t["open_blockers"]]
    if waiting:
        rows.append("Waiting on other tickets:")
        rows += ["  %s  after %s" % (t["num"], ", ".join(t["open_blockers"])) for t in waiting]
    if out["external"]:
        rows.append("External blockers:")
        rows += ["  %s: %s" % (e["num"], e["what"]) for e in out["external"]]
    rows.append("Done: " + (", ".join(t["num"] for t in by("done")) or "none"))
    return "\n".join(rows)


def claim(folder, num, name):
    gh = GH_SOURCE.match(folder)
    if gh:
        return claim_github(gh.group(1), gh.group(2), num, name)
    num = tid(num)
    # lock the folder itself, so no lock file is left in the owner's repo
    lock = os.open(folder, os.O_RDONLY)
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        tickets, errors = load(folder)
        if tickets is None or errors:
            for e in errors:
                print("frontier: " + e, file=sys.stderr)
            return 2
        out = classify(tickets)
        t = next((t for t in tickets if t["num"] == num), None)
        if t is None:
            print("frontier: no ticket %s" % num, file=sys.stderr)
            return 2
        if t["state"] == "claimed":
            print("frontier: %s is already claimed by %s" % (num, t["claimed_by"]), file=sys.stderr)
            return 3
        if t["state"] != "ready":
            why = "done" if t["state"] == "done" else "blocked by %s" % ", ".join(
                t["open_blockers"] + ["external: " + e for e in t["external"]])
            print("frontier: %s is not ready (%s)" % (num, why), file=sys.stderr)
            return 3
        line = "**Claimed by:** %s %s" % (name, datetime.now().strftime("%Y-%m-%d %H:%M"))
        lines = t["path"].read_text(encoding="utf-8").splitlines()
        at = next((i for i, l in enumerate(lines) if FIELD.match(l.strip())
                   and FIELD.match(l.strip()).group(1).lower() == "status"), None)
        if at is None:
            lines += ["", line, "", "**Status:** in-progress"]
        else:
            lines[at:at + 1] = [line, "", "**Status:** in-progress"]
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".claim-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, t["path"])
        print(t["path"])
        return 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)


def main(argv):
    if argv[:1] == ["claim"]:
        if len(argv) != 4:
            print("usage: frontier.py claim <issues-dir> <NN> <name>", file=sys.stderr)
            return 1
        return claim(*argv[1:])
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if len(args) != 1:
        print("usage: frontier.py [--json] <issues-dir> | claim <issues-dir> <NN> <name>", file=sys.stderr)
        return 1
    tickets, errors = load(args[0])
    for e in errors:
        print("frontier: " + e, file=sys.stderr)
    if tickets is None or errors:
        return 2
    out = classify(tickets)
    print(json.dumps(out, indent=2) if as_json else as_text(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
