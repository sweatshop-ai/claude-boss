#!/usr/bin/env python3
"""Reading a Claude session transcript, in one place.

A transcript is append-only JSONL. Everything the boss needs from it sits near
the end, so only the last TAIL bytes are read:

    tail(path)        -> the parsed records in the last TAIL bytes
    usage(records)    -> (context of the last turn, priced cost per turn over
                          the last BAND turns, turns seen)
    pin(records)      -> uuid of the last user, assistant or queued_command record

The tail is enough. Measured 2026-10-01 on the six largest transcripts on the
machine (20-33 MB): 4 MB held 264-491 turns, never fewer than BAND, and a full
read gave the same context and cost while taking 2-5x longer. `turns` is
therefore the turns seen in the tail, not the session's total.
"""
import json
import os

TAIL = 4 * 1024 * 1024
BAND = 200

# Relative Opus token prices. Cache reads are a tenth of fresh input, so raw
# context traffic overstates spend ~7.5x; weighting is what makes the number
# comparable between a young session and an old one. policy.py's cost lines are
# in these units.
W_IN, W_CACHE_WRITE, W_CACHE_READ, W_OUT = 1.0, 1.25, 0.10, 5.0


def tail(path, nbytes=TAIL):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - nbytes))
            data = fh.read()
    except (OSError, TypeError):
        return []
    lines = data.split(b"\n")
    if size > nbytes:
        lines = lines[1:]                 # the first line is cut in half
    out = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def usage(records, band=BAND):
    rows = []
    for d in records:
        m = d.get("message")
        u = m.get("usage") if isinstance(m, dict) else None
        if u:
            rows.append((u.get("input_tokens", 0), u.get("cache_creation_input_tokens", 0),
                         u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0)))
    if not rows:
        return 0, 0, 0
    last = rows[-1]
    recent = rows[-band:]
    cost = sum(r[0] * W_IN + r[1] * W_CACHE_WRITE + r[2] * W_CACHE_READ + r[3] * W_OUT
               for r in recent) / len(recent)
    return last[0] + last[1] + last[2], cost, len(rows)


EXIT_MARKS = ("<local-command-caveat>", "<local-command-stdout>")


def is_exit_record(d):
    """A user record `/exit` itself writes: the local-command caveat, the
    `/exit` line, its stdout. Any other slash command is input."""
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    c = msg.get("content")
    return isinstance(c, str) and (c.startswith(EXIT_MARKS)
                                   or c.lstrip().startswith("<command-name>/exit</command-name>"))


def pin(records, past_exit=False):
    """The pin `boss-lifecycle.sh --require-idle --expect-last` compares against:
    a worker that took any input after the boss looked has a newer one. Not the
    file size, because idle sessions still append records of their own
    (away_summary, ai-title, bridge-session, measured 2026-09-18).

    `past_exit` leaves out what `/exit` writes before its "Background work is
    running" dialog, so the boss can tell that dialog on an idle worker from
    a turn that started in the gap, and counts a prompt queued behind the
    dialog (an `enqueue` record), which exiting would drop."""
    last = None
    for d in records:
        t = d.get("type")
        if past_exit and t == "user" and is_exit_record(d):
            continue
        if past_exit and t == "queue-operation" and d.get("operation") == "enqueue":
            # A prompt that arrived behind the dialog: exiting would drop it.
            last = "enqueue@%s" % d.get("timestamp")
            continue
        if t in ("user", "assistant") or (
                t == "attachment" and (d.get("attachment") or {}).get("type") == "queued_command"):
            last = d.get("uuid") or last
    return last
