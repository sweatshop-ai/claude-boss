#!/usr/bin/env python3
"""boss-unask: the owner's report that a kind of question should not reach them.

    boss-unask record <track> <kind>   stdin: the question, a line `--- owner ---`, the owner's words
    boss-unask list <track>            the kinds reported on this track, with counts

One line per report goes to `$CLAUDE_CONFIG_DIR/pm/unwanted-questions.jsonl`, mode 600.
The file holds the owner's words and a question's text, so it stays out of the repo,
out of Codex and out of GitHub. `kind` is a short slug the session picks (reuse one
`list` already shows); the weekly routine counts by it and never reads the texts.
"""
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone

import boss_store

KIND_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_QUESTION = 1000        # the owner's words are the label: they get four times the room
MAX_WORDS = 4000
FILE = "unwanted-questions.jsonl"
SEP = "--- owner ---"


def path(cfg=None):
    return boss_store.pm_dir(cfg) / FILE


def _clean(s, cap):
    return " ".join(s.split())[:cap]


def parse(text):
    """(question, words) from stdin: the first `--- owner ---` line splits them; both must be non-empty.

    A plain `---` is a markdown rule a question may hold, so it is not the separator.
    """
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if l.strip() == SEP:
            q, w = _clean(" ".join(lines[:i]), MAX_QUESTION), _clean(" ".join(lines[i + 1:]), MAX_WORDS)
            if q and w:
                return q, w
            break
    raise ValueError("stdin must be the question, a line '%s', then the owner's words" % SEP)


def record(track, kind, text, cfg=None, session=None, now=None):
    if not boss_store.valid_track(track):
        raise ValueError("not a track name: %r" % track)
    if not KIND_RE.fullmatch(kind or ""):
        raise ValueError("not a kind slug: %r (lowercase letters, digits, -)" % kind)
    q, w = parse(text)
    now = now or datetime.now(timezone.utc)
    rec = dict(date=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               session=session or os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
               track=track, kind=kind, question=q, words=w)
    p = path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = os.open(p.parent / ".unwanted-questions.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fd = os.open(p, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b") as f:             # owns the fd; a file object finishes a short write
            os.fchmod(fd, 0o600)
            size = os.fstat(fd).st_size
            lead = b"\n" if size and os.pread(fd, 1, size - 1) != b"\n" else b""   # a torn last line stays alone
            f.write(lead + (json.dumps(rec, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(lock)
    return rec


def read(cfg=None):
    """Every well-formed report; a damaged line is skipped, not fatal."""
    out = []
    try:
        text = path(cfg).read_text()
    except OSError:
        return out
    for l in text.splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if (isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("date", "track", "kind"))
                and boss_store.valid_track(r["track"]) and KIND_RE.fullmatch(r["kind"])):
            out.append(r)
    return out


def listing(track, cfg=None):
    by = {}
    for r in read(cfg):
        if r["track"] == track:
            by.setdefault(r["kind"], []).append(r)
    lines = []
    for kind, rs in sorted(by.items()):
        lines.append("%s (%d)" % (kind, len(rs)))
        lines += ["  - " + str(r.get("question", "")) for r in rs[-3:]]
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv):
    try:
        if len(argv) == 3 and argv[0] == "record":
            rec = record(argv[1], argv[2], sys.stdin.read())
            print("recorded %s on %s" % (rec["kind"], rec["track"]))
        elif len(argv) == 2 and argv[0] == "list":
            sys.stdout.write(listing(argv[1]))
        else:
            raise ValueError("usage: boss-unask record <track> <kind> (stdin)  |  list <track>")
    except (ValueError, OSError) as e:
        print("boss-unask: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
