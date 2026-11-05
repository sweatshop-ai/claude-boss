#!/usr/bin/env python3
"""ctx-over-measure — of the workers past 250k, how many the boss asked for a boundary, and what happened.

Ticket 03. Reads worker transcripts (a session whose first 256 KB holds a
boss dispatch), one at a time and in batches, and writes one row per worker to a
private file under the config dir: transcripts name clients and the plugin repo
is public. Stdout carries overall figures only.

Run it under the transcript lock, never beside other readers:

    flock ~/.claude/pm/.boss-efficiency-transcripts.lock nice -n 19 ionice -c3 \\
        python3 routines/ctx_over_measure.py --days 14

It stops when the load average passes 20. No LLM, no network.

Per worker: the turn where context first reached CTX-SPLIT (150k) and CTX-OVER
(250k), whether a message from another session reached it after that wording a
boundary ("handoff", "boundary", "restart", "split"), how many turns it took
after the ask, and what share of the session's cost was spent above 250k.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "skills" / "boss")]
import boss_store  # noqa: E402
import policy  # noqa: E402
from boss_efficiency_core import cost, usage  # noqa: E402

BATCH = 25
PEEK = 256 * 1024
MAX_LOAD = 20
RESTART_TURNS = 35          # the owner's line: a restart pays when more than this is left
ASK_WITHIN = 15             # a worker that ended this many turns after the ask reached its boundary
CROSS = re.compile(r"<cross-session-message")
ASK = re.compile(r"CTX-OVER|you are at \d+k|past the (?:150k|250k)|(?:next|current) boundary|stop at the (?:next|current) (?:boundary|state)\b|write the hand-?off", re.I)


def is_worker(path):
    """True when a boss dispatch reached the session as a message of its own. A boss only writes
    the words, or reads them in a tool result."""
    try:
        with open(path, errors="replace") as fh:
            seen = 0
            for line in fh:
                seen += len(line)
                if seen > PEEK:
                    return False
                if "Boss dispatch from " not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                c = (d.get("message") or {}).get("content")
                if d.get("type") == "user" and not d.get("isSidechain") and not (
                        isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)):
                    return bool(CROSS.search(text_of(c)[:400]))
    except OSError:
        pass
    return False


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def scan(path):
    """One worker transcript -> its row, or None when it never reported usage."""
    turns, asks = {}, []       # message id -> (ctx, cost); (turn index when seen, text is a boundary ask)
    order = []
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            m = d.get("message") or {}
            if d.get("type") == "assistant" and m.get("id"):
                u = usage(m.get("usage") or {})
                if m["id"] not in turns:
                    order.append(m["id"])
                turns[m["id"]] = (u["i"] + u["cw"] + u["cr"], cost(u))
            elif d.get("type") == "user" and isinstance(m.get("content"), (str, list)):
                if isinstance(m["content"], list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"]):
                    continue
                tx = text_of(m["content"])
                if CROSS.search(tx[:400]) and ASK.search(tx):
                    asks.append(len(order))
    if not order:
        return None
    ctxs = [turns[i][0] for i in order]
    costs = [turns[i][1] for i in order]

    def first(limit):
        return next((n for n, c in enumerate(ctxs) if c >= limit), None)

    split, over = first(policy.WORKER_SPLIT), first(policy.WORKER_OVER)
    row = dict(file=os.path.basename(path), turns=len(order), peak=max(ctxs), cost=round(sum(costs)),
               split_at=split, over_at=over,
               cost_over=round(sum(c for x, c in zip(ctxs, costs) if x >= policy.WORKER_OVER)))
    if over is not None:
        late = [a for a in asks if a > over]
        early = [a for a in asks if split is not None and split < a <= over]
        row["left_at_cross"] = len(order) - over
        row["asked_after"] = bool(late)
        row["asked_between"] = bool(early)
        if late:
            row["turns_after_ask"] = len(order) - late[0]
            row["ended_after_ask"] = len(order) - late[0] <= ASK_WITHIN
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=14)
    ap.add_argument("--out", help="rows file (default: <config>/pm/ctx-over-measure.jsonl)")
    a = ap.parse_args(argv)
    cfg = Path(boss_store.config_dir())
    out = Path(a.out) if a.out else boss_store.pm_dir(cfg) / "ctx-over-measure.jsonl"
    since = time.time() - a.days * 86400
    files = sorted(p for p in (cfg / "projects").glob("*/*.jsonl") if p.stat().st_mtime >= since)
    rows = []
    for i in range(0, len(files), BATCH):
        if os.getloadavg()[0] > MAX_LOAD:
            print("stopped: load %.1f over %d after %d files" % (os.getloadavg()[0], MAX_LOAD, i), file=sys.stderr)
            return 3
        for p in files[i:i + BATCH]:
            if is_worker(p):
                r = scan(p)
                if r:
                    rows.append(r)
        time.sleep(0.5)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(report(rows, len(files)))
    return 0


def pct(n, d):
    return "%d%%" % round(100 * n / d) if d else "n/a"


def report(rows, scanned):
    n = len(rows)
    s150 = [r for r in rows if r["split_at"] is not None]
    over = [r for r in rows if r["over_at"] is not None]
    asked = [r for r in over if r["asked_after"]]
    cost_all = sum(r["cost"] for r in rows)
    cost_over = sum(r["cost_over"] for r in rows)
    left = [r["left_at_cross"] for r in over]
    lines = ["transcripts scanned %d, worker sessions %d" % (scanned, n),
             "past 150k %d (%s), past 250k %d (%s)" % (len(s150), pct(len(s150), n), len(over), pct(len(over), n)),
             "past 250k and asked for a boundary after the crossing: %d of %d (%s)" % (len(asked), len(over), pct(len(asked), len(over))),
             "past 250k, asked between 150k and 250k only: %d" % sum(1 for r in over if r["asked_between"] and not r["asked_after"]),
             "past 250k and never asked: %d" % sum(1 for r in over if not r["asked_after"] and not r["asked_between"])]
    if asked:
        ended = sum(1 for r in asked if r["ended_after_ask"])
        lines.append("of those asked: ended within %d turns of the ask %d (%s), carried on %d" % (
            ASK_WITHIN, ended, pct(ended, len(asked)), len(asked) - ended))
        lines.append("turns taken after the ask: median %d" % statistics.median(r["turns_after_ask"] for r in asked))
    if left:
        more = sum(1 for x in left if x > RESTART_TURNS)
        lines.append("turns left at the crossing: median %d; more than %d left in %d of %d (%s)" % (
            statistics.median(left), RESTART_TURNS, more, len(left), pct(more, len(left))))
    lines.append("share of worker cost spent above 250k: %s" % pct(cost_over, cost_all))
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
