#!/usr/bin/env python3
"""Resolve every tmux pane to the Claude session running in it.

One place answers all the questions the boss keeps asking badly:

  who is this pane   -> the agent-names plugin's name, which is the SAME name
                        ListAgents and SendMessage resolve. Not a second name
                        invented by boss-lifecycle.sh and reconciled by hand.
  is it safe to stop -> the session's own `status` field. `busy` means a turn
                        is in flight, and retire's Escape/Escape//exit would
                        abort it.
  what is it costing -> context carried on its most recent turn, read from the
                        session transcript, plus a priced cost-per-turn over
                        the last 200 turns.

Output is TSV, one line per resolved pane:

    pane_id  name  session_id  status  ctx_k  cost_per_turn_k  turns

Panes with no Claude session are omitted. Nothing here writes; --set-name is the
one exception and it goes through the plugin's own state file, atomically.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))

# Relative Opus token prices. Cache reads are a tenth of fresh input, so raw
# context traffic overstates spend ~7.5x; weighting is what makes the number
# comparable between a young session and an old one.
W_IN, W_CACHE_WRITE, W_CACHE_READ, W_OUT = 1.0, 1.25, 0.10, 5.0
BAND = 200


def ppid_of(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read()
        # comm can contain spaces and parens; everything after the LAST ')'.
        return int(data[data.rindex(b")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def ancestors(pid, stop_at, limit=40):
    """Walk up from pid looking for stop_at. Panes nest a shell then claude."""
    seen = 0
    while pid > 1 and seen < limit:
        if pid == stop_at:
            return True
        pid = ppid_of(pid)
        seen += 1
    return False


def transcript_for(rec):
    return registry.transcript_of(rec, CFG)


def usage_tail(path, band=BAND):
    """Last-turn context and priced cost/turn over the final `band` turns.

    Reads the whole file: transcripts are append-only JSONL and a turn's usage
    block is not fixed-width, so seeking from the end is not reliable.
    """
    rows = []
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                u = (d.get("message") or {}).get("usage")
                if not u:
                    continue
                rows.append((u.get("input_tokens", 0),
                             u.get("cache_creation_input_tokens", 0),
                             u.get("cache_read_input_tokens", 0),
                             u.get("output_tokens", 0)))
    except OSError:
        return 0, 0, 0
    if not rows:
        return 0, 0, 0
    last = rows[-1]
    ctx = last[0] + last[1] + last[2]
    tail = rows[-band:]
    cost = sum(r[0] * W_IN + r[1] * W_CACHE_WRITE + r[2] * W_CACHE_READ + r[3] * W_OUT
               for r in tail) / len(tail)
    return ctx, cost, len(rows)


TAIL_BYTES = 4 * 1024 * 1024


def last_conversation_uuid(path, nbytes=TAIL_BYTES):
    """uuid of the last user, assistant or queued_command record in the tail.

    This is the pin `boss-lifecycle.sh --require-idle --expect-last` compares
    against: a worker that took any input after the boss looked has a newer one.
    Not the file size, because idle sessions still append records of their own
    (away_summary, ai-title, bridge-session, measured 2026-09-18).
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - nbytes))
            data = fh.read()
    except OSError:
        return None
    lines = data.split(b"\n")
    if size > nbytes:
        lines = lines[1:]                 # the first line is cut in half
    last = None
    for raw in lines:
        if b'"uuid"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        t = d.get("type")
        if t in ("user", "assistant") or (
                t == "attachment" and (d.get("attachment") or {}).get("type") == "queued_command"):
            last = d.get("uuid") or last
    return last


def load_sessions():
    """Live sessions only: a reused pid or an orphaned worker is not one."""
    out = []
    for rec in registry.live(CFG):
        rec["_path"] = Path(rec["path"])
        out.append(rec)
    return out


def panes():
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "{}\t{}".format("#{pane_id}", "#{pane_pid}")],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.stdout.splitlines():
        pid_s, _, pane_pid = line.partition("\t")
        try:
            rows.append((pid_s, int(pane_pid)))
        except ValueError:
            continue
    return rows


def resolve():
    sess = load_sessions()
    rows = []
    for pane_id, pane_pid in panes():
        for rec in sess:
            if ancestors(rec["pid"], pane_pid):
                rows.append((pane_id, rec))
                break
    return rows


def main():
    args = sys.argv[1:]
    if args and args[0] == "--set-name":
        # boss-lifecycle spawn/claim uses this so the plugin stays the single
        # store of a worker's name. Mirrors adopt_all.py: never clobber a name
        # the user set by hand with /rename.
        pane_id, name = args[1], args[2]
        for pid, rec in resolve():
            if pid != pane_id:
                continue
            path = rec["_path"]
            try:
                with path.open(encoding="utf-8") as fh:
                    fresh = json.load(fh)
                if fresh.get("nameSource") == "user":
                    print(fresh.get("name", ""), end="")
                    return 0
                fresh["name"] = name
                fresh.pop("nameSource", None)
                tmp = path.with_suffix(".json.boss-tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    json.dump(fresh, fh)
                os.replace(tmp, path)
                print(name, end="")
                return 0
            except (OSError, ValueError):
                return 1
        return 1

    if args and args[0] == "--state":
        # boss-lifecycle --require-idle: session id, status and pin, fast (no
        # usage scan), read immediately before the keystroke.
        for pane_id, rec in resolve():
            if pane_id != args[1]:
                continue
            t = transcript_for(rec)
            pin = last_conversation_uuid(t) if t else None
            print("\t".join([rec.get("sessionId") or "-", rec.get("status") or "-", pin or "-"]))
            return 0
        print("-\t-\t-")
        return 1

    want = args[0] if args else None
    for pane_id, rec in resolve():
        if want and pane_id != want:
            continue
        t = transcript_for(rec)
        ctx, cost, turns = usage_tail(t) if t else (0, 0, 0)
        print("\t".join([
            pane_id,
            rec.get("name") or "-",
            rec.get("sessionId") or "-",
            rec.get("status") or "-",
            f"{ctx/1000:.0f}",
            f"{cost/1000:.0f}",
            str(turns),
        ]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
