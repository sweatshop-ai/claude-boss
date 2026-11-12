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
                                 the current streak)

    python3 codex_health.py      prints {"state", "failures", "answers", "skipped"}

Only `codex` attempts count (the fallback's lines are ignored, and a fallback
answering does not turn the Codex attempt before it into a success). All repos
count together: there is one Codex per config dir. `absent`, `timeout` and
`error` are failures, `answered` is a success, `noverdict` is neither. The
`round` field is never read. The state starts `up`; policy.CODEX_DOWN_AFTER
failures in a row make it `down`; from `down`, policy.CODEX_UP_AFTER answers in
a row make it `up` again.
"""
import json
import sys
from pathlib import Path

import boss_store
import policy

FAILURES = frozenset(("absent", "timeout", "error"))
REASONS = FAILURES | {"noverdict", "answered"}


def default_path():
    return boss_store.pm_dir() / "reviews" / "attempts.jsonl"


def _entry(raw):
    """The decoded line when it has a usable shape, else None."""
    try:
        e = json.loads(raw.decode("utf-8"))
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
    streak, last = [], None
    for raw in lines:
        if not raw.strip():
            continue
        e = _entry(raw)
        if e is None or (e["reviewer"] == "codex" and e["reason"] not in REASONS):
            skipped += 1
            continue
        if e["reviewer"] != "codex":
            continue
        if e["reason"] == "answered":
            answers, failures, streak = answers + 1, 0, []
            if state == "down" and answers >= policy.CODEX_UP_AFTER:
                state = "up"
        elif e["reason"] in FAILURES:
            failures, answers = failures + 1, 0
            last = e
            streak.append("%s#%d" % (e["repo"], e["pr"]))
            if failures >= policy.CODEX_DOWN_AFTER:
                state = "down"
    return {"state": state, "failures": failures, "answers": answers, "skipped": skipped,
            "last_repo": last["repo"] if last else None, "last_pr": last["pr"] if last else None,
            "last_reason": last["reason"] if last else None, "prs": len(set(streak))}


def main():
    h = health()
    print(json.dumps({k: h[k] for k in ("state", "failures", "answers", "skipped")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
