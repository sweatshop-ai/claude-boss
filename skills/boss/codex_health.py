#!/usr/bin/env python3
"""Whether Codex is down, derived from the attempts log in one scan.

Every review run appends its reviewer attempts to `pm/reviews/attempts.jsonl`
(boss_review.append_attempts). This module reads that file and keeps no counter
and writes nothing: the state is a function of the file, so two readers agree
and a lost write cannot leave a counter out of step. 05c raises and clears the
blocker from it.

    health(path=None) -> dict    state, failures, answers, skipped, and for the
                                 blocker text: last_repo, last_pr, last_reason
                                 and prs (distinct repo#pr among the failures of
                                 the current streak); last_ts is the `ts` of the
                                 newest failure in file order, as an aware
                                 datetime, or None when it has no usable `ts`

    python3 codex_health.py      prints {"state", "failures", "answers", "skipped"}

Only `codex` attempts count (the fallback's lines are ignored, and a fallback
answering does not turn the Codex attempt before it into a success). All repos
count together: there is one Codex per config dir. `absent`, `timeout` and
`error` are failures, `answered` is a success, `noverdict` is neither. The
`round` field is never read. The state starts `up`; policy.CODEX_DOWN_AFTER
failures in a row make it `down`; from `down`, policy.CODEX_UP_AFTER answers in
a row make it `up` again.

A line is skipped and counted when it is not one JSON object with a usable shape: a blank or whitespace-only
line (the writer never writes one, so it is a hand edit), a torn or unparseable line, and a line that names a
key twice (json would keep the last value, so a hand-edited line could change its reviewer). A skipped line is
never a failure and never an answer. The duplicate-key check applies at any depth, so a writer that dumped
a dict with keys `1` and `"1"` would have every such line skipped; today's writer (boss_review.append_attempts)
has no such field, and the skip count is in the command's output, so it is left (ticket 30).

Accepted: a write that tears without its newline (a full disk) is followed by the next append on the same
line. The merged line is not parseable, so it is skipped and the one real attempt after the tear goes
uncounted; `down` can come one attempt late. The reader does not resynchronise: guessing where a line
starts could count a line twice, and a wrong count raises a false blocker or hides an outage.

An unreadable log other than a missing one (permission, a directory, a parent that is a file) raises
OSError from health(), so the blocker's sync reports it; the command prints it on stderr and exits 2.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import boss_store
import policy

FAILURES = frozenset(("absent", "timeout", "error"))
REASONS = FAILURES | {"noverdict", "answered"}


def default_path():
    return boss_store.pm_dir() / "reviews" / "attempts.jsonl"


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _entry(raw):
    """The decoded line when it has a usable shape, else None."""
    try:
        e = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(e, dict):
        return None
    repo, pr = e.get("repo"), e.get("pr")
    if not (isinstance(repo, str) and repo and type(pr) is int and pr > 0):
        return None
    if not (isinstance(e.get("reviewer"), str) and isinstance(e.get("reason"), str)):
        return None
    return e


def _ts(e):
    """The entry's `ts` as an aware datetime (UTC `Z` or an offset), else None."""
    raw = e.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def health(path=None):
    path = Path(path) if path is not None else default_path()
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = b""
    lines = data.split(b"\n")
    skipped = 1 if lines[-1] else 0         # no closing newline: the last write was torn
    lines = lines[:-1]
    state, failures, answers = "up", 0, 0
    recovered = False       # an answered streak of CODEX_UP_AFTER was read since the last down period
    streak, last = [], None
    for raw in lines:
        e = _entry(raw)
        if e is None or (e["reviewer"] == "codex" and e["reason"] not in REASONS):
            skipped += 1
            continue
        if e["reviewer"] != "codex":
            continue
        if e["reason"] == "answered":
            answers, failures, streak = answers + 1, 0, []
            if answers >= policy.CODEX_UP_AFTER:
                recovered = True
            if state == "down" and answers >= policy.CODEX_UP_AFTER:
                state = "up"
        elif e["reason"] in FAILURES:
            failures, answers = failures + 1, 0
            last = e
            streak.append("%s#%d" % (e["repo"], e["pr"]))
            if failures >= policy.CODEX_DOWN_AFTER:
                state = "down"
                recovered = False
    return {"state": state, "failures": failures, "answers": answers, "recovered": recovered, "skipped": skipped,
            "last_repo": last["repo"] if last else None, "last_pr": last["pr"] if last else None,
            "last_reason": last["reason"] if last else None,
            "last_ts": _ts(last) if last else None, "prs": len(set(streak))}


def main():
    try:
        h = health()
    except OSError as e:
        print("codex_health: cannot read %s: %s" % (e.filename or default_path(), e.strerror or e), file=sys.stderr)
        return 2
    print(json.dumps({k: h[k] for k in ("state", "failures", "answers", "skipped")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
