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
                        the last 200 turns (transcript.py).

Which session runs in which pane, and who owns a pane, is fleet.py's to say;
this is its command line.

Output is TSV, one line per resolved pane:

    pane_id  name  session_id  status  ctx_k  cost_per_turn_k  turns  flags

`turns` counts the turns in the transcript's last 4 MB, not the whole session.

`flags` is policy.flag_for() for the session's role (boss when it holds a boss
marker, worker otherwise), plus `shared-pane` when more than one live session
names the pane, space-separated, or "-".

Panes with no Claude session are omitted from it.

    get <pane> <field>...     the named fields, tab-separated, "-" when empty;
                              an unknown field exits 2 (fields: see FIELDS)
    list --boss <pane> [--mine]
                              the roster boss-lifecycle.sh list prints, with a
                              line under a shared pane saying who else is there
    stamp <pane> <boss-pane>  mark the pane as owned by that boss

Nothing here writes; --set-name and stamp are the exceptions. --set-name
calls cc-agent-names' `agent-name set` when that is on PATH,
and writes the peer file atomically when it is not.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402
import fleet  # noqa: E402
import policy  # noqa: E402
import registry  # noqa: E402
import transcript  # noqa: E402

CFG = registry.config_dir()


def transcript_for(rec):
    return registry.transcript_of(rec, CFG)


def load_sessions():
    """Live sessions only: a reused pid or an orphaned worker is not one."""
    out = []
    for rec in registry.live(CFG):
        rec["_path"] = Path(rec["path"])
        out.append(rec)
    return out


TMUX = fleet.Tmux(timeout=10)


def seats():
    return fleet.view(TMUX, load_sessions())


def resolve():
    """(pane_id, session) for every pane a live session runs in."""
    return [(s.pane.id, s.session) for s in seats() if s.session]


def usage(rec):
    t = transcript_for(rec)
    return transcript.usage(transcript.tail(t)) if t else (0, 0, 0)


def flags_of(seat, ctx, cost):
    rec = seat.session
    role = policy.BOSS if boss_store.is_boss(rec.get("sessionId") or "", CFG) else policy.WORKER
    pol = policy.flag_for(ctx, cost, role) if transcript_for(rec) else []
    return pol + seat.flags()


# Every field `get` knows, and how to read it off a seat.
FIELDS = {
    "name": lambda s: (s.session or {}).get("name"),
    "status": lambda s: (s.session or {}).get("status"),
    "session": lambda s: (s.session or {}).get("sessionId"),
    "owner": lambda s: s.pane.owner,
}


def cmd_get(pane, names):
    bad = [n for n in names if n not in FIELDS]
    if bad or not names:
        print("boss-panes get: unknown field %s; known: %s" % (
            ", ".join(bad) or "(none given)", " ".join(FIELDS)), file=sys.stderr)
        return 2
    seat = fleet.seat_of(seats(), pane=pane) or fleet.Seat(fleet.Pane(pane))
    print("\t".join(str(FIELDS[n](seat) or "-") for n in names))
    return 0 if seat.pane.coord else 1


def cmd_list(boss, mine_only):
    """Columns: pane, coord, name, state, ctx, cost/turn + flags, owner tag, path.
    The coordinate is session-qualified on purpose: pane INDEXES collide across
    tmux sessions, so a bare index sends the owner to the wrong terminal."""
    print("PANE\tCOORD\tNAME\tSTATE\tCTX\tCOST/TURN\tOWNER\tPATH")
    for s in seats():
        p = s.pane
        if p.id == boss and boss:
            tag = "self"
        elif not p.owner:
            tag = "unowned"
        elif p.owner == boss:
            tag = "mine"
        else:
            tag = "other(%s)" % p.owner
        if mine_only and tag not in ("mine", "self"):
            continue
        if s.session:
            # Live name and status from the session; a crashed worker has none
            # and keeps the name mirrored on its pane, which is what makes it
            # recognisable in the watchdog.
            ctx, cost, _ = usage(s.session)
            flags = flags_of(s, ctx, cost)
            name, state = s.session.get("name") or "-", s.session.get("status") or "-"
            ctx_s, cost_s = "%.0f" % (ctx / 1000), "%.0f" % (cost / 1000)
        else:
            flags, name, state, ctx_s, cost_s = [], p.mirror or "-", p.command, "-", "-"
        print("\t".join([p.id, p.coord, name, state, ctx_s + "k",
                         cost_s + "k" + "".join(" " + f for f in flags), tag,
                         p.path + (" <- you" if tag == "self" else "")]))
        why = s.explain()
        if why:
            print("  " + why)
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] == "get":
        return cmd_get(args[1] if len(args) > 1 else "", args[2:])
    if args and args[0] == "list":
        boss = args[args.index("--boss") + 1] if "--boss" in args[:-1] else ""
        return cmd_list(boss, "--mine" in args)
    if args and args[0] == "stamp":
        if len(args) != 3:
            print("usage: boss-panes.py stamp <pane> <boss-pane>", file=sys.stderr)
            return 2
        return 0 if TMUX.stamp(args[1], args[2]) else 1
    if args and args[0] == "--set-name":
        # boss-lifecycle spawn/claim/restart/move name a worker through here.
        # With cc-agent-names installed, `agent-name set` is the one way in: it
        # remembers the name as assigned, so the plugin's hook keeps it on the
        # next prompt and gives it back on resume. Without the plugin there is
        # no hook to undo it, and the peer file is written directly. A name set
        # by hand with /rename is never clobbered either way.
        pane_id, name = args[1], args[2]
        for pid, rec in resolve():
            if pid != pane_id:
                continue
            if shutil.which("agent-name"):
                try:
                    out = subprocess.run(["agent-name", "set", rec.get("sessionId") or "", name],
                                         capture_output=True, text=True, timeout=10)
                except (OSError, subprocess.SubprocessError):
                    return 1
                print(out.stdout.strip(), end="")
                return out.returncode
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
            recs = transcript.tail(t) if t else []
            pin = transcript.pin(recs)
            past = transcript.pin(recs, past_exit=True)
            print("\t".join([rec.get("sessionId") or "-", rec.get("status") or "-",
                             pin or "-", past or "-"]))
            return 0
        print("-\t-\t-\t-")
        return 1

    want = args[0] if args else None
    for seat in seats():
        pane_id, rec = seat.pane.id, seat.session
        if not rec or (want and pane_id != want):
            continue
        ctx, cost, turns = usage(rec)
        flags = flags_of(seat, ctx, cost)
        print("\t".join([
            pane_id,
            rec.get("name") or "-",
            rec.get("sessionId") or "-",
            rec.get("status") or "-",
            f"{ctx/1000:.0f}",
            f"{cost/1000:.0f}",
            str(turns),
            " ".join(flags) or "-",
        ]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
