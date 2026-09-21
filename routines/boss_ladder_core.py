#!/usr/bin/env python3
"""boss-ladder core — post due escalation rungs from tracker marker lines.

The failure this exists to prevent: the P12 ladder
(${CLAUDE_PLUGIN_ROOT}/skills/boss/references/escalation.md) fires only when the boss wakes,
because the timer is a detached `sleep` that re-invokes the session. Once the Jev
hook absorbs no-action events the boss may sleep through a rung, and a ladder
nobody climbs is the same as no ladder. This reads the marker that the boss (or
the hook) leaves on an Open-blockers line and posts the rung that is due, with no
boss turn.

No LLM anywhere: the decision is arithmetic on two timestamps.

Marker, appended to a `## Open blockers` line:

    [ladder id=a1b2c3d4 t0=2026-09-18T10:53+02:00 last=0
     next=2026-09-18T10:58+02:00 pane=20:0.2 ask="put the u2 file on lab-0"]

  id       required, [a-z0-9]{4,16}, stable forever. The key. Survives any
           rewording of the line, and keys the state journal.
  t0       required, ISO 8601 WITH offset. When the blocker was raised. Never
           rewritten.
  last     required, the rung already posted. Born 0: the hook posts rung 0.
  next     required, ISO 8601 with offset. Authoritative gate — nothing posts
           before now >= next. Pushing it forward by hand defers a rung without
           losing t0, which is how "rungs held while the owner is at the keyboard"
           works.
  ask      required, double-quoted, no '"' inside. The one action. Slack text.
  pane     optional, sess:win.pane.
  cost     optional, quoted. What is idle behind it.
  cleared  optional, ISO 8601. Present -> the line is skipped forever. This
           never posts `boss-alert clear` itself; whoever sets cleared= posts it,
           because only they know it actually cleared.

A line with no marker is ignored. A malformed marker is logged and skipped,
never guessed at.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(os.environ.get("HOME") or Path.home())
HERE = Path(__file__).resolve().parent          # <plugin>/routines
CFG = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(HOME / ".claude")))
PM_DIR = Path(os.environ.get("BOSS_LADDER_PM", CFG / "pm"))
STATE = Path(os.environ.get("BOSS_LADDER_STATE",
                            CFG / "routines" / "state" / "boss-ladder.json"))
BOSS_ALERT = os.environ.get("BOSS_ALERT",
                            str(HERE.parent / "skills" / "boss" / "bin" / "boss-alert"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

ID_RE = re.compile(r"^[a-z0-9]{4,16}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REQUIRED = ("id", "t0", "last", "next", "ask")
KNOWN = set(REQUIRED) | {"pane", "cost", "cleared"}

# What the hook writes into ask= until the boss names the action.
PLACEHOLDER = "(boss names it)"
# Agreed with Berit 2026-09-18: her hook and this routine both take
# fcntl.flock on this sibling, because both write by temp file + rename and
# a lock on the tracker's own inode does not survive the replace.
def lock_path(path: Path) -> Path:
    return path.parent / f".{path.name}.lock"


BLOCKERS_RE = re.compile(r"^##\s+Open blockers.*?$", re.M)
NEXT_H2_RE = re.compile(r"^##\s", re.M)


def blockers_range(lines: list[str]) -> tuple[int, int]:
    """Line indices of the `## Open blockers` body, or (0, 0) if there is none.

    A marker only means anything on a blocker line. Reading the whole file makes
    prose that documents the marker format — in a roster row, in a state note —
    parse as a malformed marker, which is exactly what happened at 14:59 on
    2026-09-18. due_rungs has always scoped itself this way.
    """
    start = None
    for i, line in enumerate(lines):
        if start is None:
            if BLOCKERS_RE.match(line):
                start = i + 1
        elif NEXT_H2_RE.match(line):
            return start, i
    return (start, len(lines)) if start is not None else (0, 0)


class Concurrent(Exception):
    """The tracker changed between our read and our write."""


class MarkerError(Exception):
    """A token that starts with [ladder but does not parse. Never guessed at."""


# ---------------------------------------------------------------- the ladder

# After 24 h the ladder says so once and stops for good, matching the
# staleness guard boss-pulse.py's due_rungs already had (mins > 60 * 24).
STOP_MIN = 24 * 60

def rung_for(elapsed_min: int) -> int | None:
    """Highest rung reached at `elapsed_min`: 5, 15, 30, 60, 120, every 120.

    escalation.md: "T+30, then every 30 ... widening". Lucas set the widening on
    2026-09-18: 30 -> 60 -> 120, then every 120 until the stop. A blocker that
    has held two hours is more urgent than one that has held five minutes, so
    the rung label stays the elapsed minutes, which is what boss-alert prints.
    """
    if elapsed_min < 5:
        return None
    if elapsed_min < 15:
        return 5
    if elapsed_min < 30:
        return 15
    if elapsed_min < 60:
        return 30
    if elapsed_min < 120:
        return 60
    if elapsed_min >= STOP_MIN:
        return STOP_MIN
    return (elapsed_min // 120) * 120


def next_rung(rung: int) -> int:
    return {5: 15, 15: 30, 30: 60, 60: 120}.get(rung, min(rung + 120, STOP_MIN))


# ---------------------------------------------------------------- parsing

def _parse_ts(value: str, field: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise MarkerError(f"{field}={value!r} is not ISO 8601")
    if dt.tzinfo is None:
        # A naive timestamp is ambiguous across a DST change, and this routine
        # is nothing but time arithmetic.
        raise MarkerError(f"{field}={value!r} has no UTC offset")
    return dt


def scan_marker(line: str):
    """Return (raw_token, fields) for the first [ladder ...] token, or None."""
    start = line.find("[ladder")
    if start < 0:
        return None
    after = start + len("[ladder")
    if after < len(line) and line[after] not in " \t]":
        return None  # [ladderish — not our token
    i, fields = after, {}
    while True:
        while i < len(line) and line[i] in " \t":
            i += 1
        if i >= len(line):
            raise MarkerError("marker is not closed with ']'")
        if line[i] == "]":
            i += 1
            break
        eq = line.find("=", i)
        if eq < 0:
            raise MarkerError(f"no '=' after {line[i:i + 20]!r}")
        key = line[i:eq]
        if not KEY_RE.match(key):
            raise MarkerError(f"bad field name {key!r}")
        if key in fields:
            raise MarkerError(f"duplicate field {key!r}")
        j = eq + 1
        if j < len(line) and line[j] == '"':
            end = line.find('"', j + 1)
            if end < 0:
                raise MarkerError(f"{key}= has no closing quote")
            fields[key], i = line[j + 1:end], end + 1
        else:
            end = j
            while end < len(line) and line[end] not in " \t]":
                end += 1
            fields[key], i = line[j:end], end
    return line[start:i], fields


def validate(fields: dict) -> dict:
    missing = [k for k in REQUIRED if k not in fields]
    if missing:
        raise MarkerError(f"missing field(s): {', '.join(missing)}")
    unknown = sorted(set(fields) - KNOWN)
    if unknown:
        raise MarkerError(f"unknown field(s): {', '.join(unknown)}")
    if not ID_RE.match(fields["id"]):
        raise MarkerError(f"id={fields['id']!r} is not [a-z0-9]{{4,16}}")
    if not fields["ask"].strip():
        raise MarkerError("ask= is empty")
    try:
        last = int(fields["last"])
    except ValueError:
        raise MarkerError(f"last={fields['last']!r} is not a number")
    if last < 0:
        raise MarkerError(f"last={last} is negative")
    out = {
        "id": fields["id"], "last": last,
        "t0": _parse_ts(fields["t0"], "t0"),
        "next": _parse_ts(fields["next"], "next"),
        "ask": fields["ask"],
        "pane": fields.get("pane", ""), "cost": fields.get("cost", ""),
        "cleared": fields.get("cleared", ""),
    }
    if out["cleared"]:
        _parse_ts(out["cleared"], "cleared")
    return out


def slack_text(track: str, m: dict) -> str:
    parts = [f"{track}: {m['ask']}"]
    if m["pane"]:
        parts.append(f"pane {m['pane']}")
    if m["cost"]:
        parts.append(m["cost"])
    parts.append(f"since {m['t0'].strftime('%H:%M')} (T+0)")
    return " — ".join(parts)


def stop_text(track: str, m: dict) -> str:
    where = f" — pane {m['pane']}" if m["pane"] else ""
    return (f"{track}: ladder stopped at 24 h, still open — {m['ask']}{where} "
            f"— since {m['t0'].strftime('%Y-%m-%d %H:%M')} (T+0)")


def rewrite(raw: str, last: int, nxt: datetime) -> str:
    """Update last= and next= inside the token, byte for byte elsewhere."""
    out = re.sub(r"(?<=\blast=)[^\s\]]*", str(last), raw, count=1)
    return re.sub(r"(?<=\bnext=)[^\s\]]*", nxt.isoformat(), out, count=1)


# ---------------------------------------------------------------- state

def load_state() -> dict:
    try:
        st = json.loads(STATE.read_text())
    except (OSError, ValueError):
        st = {}
    st.setdefault("markers", {})
    st.setdefault("malformed", {})
    return st


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, STATE)


# ---------------------------------------------------------------- tracks

def open_tracks(pm_dir: Path):
    """(track, tracker_path) for every tracker whose goal says OPEN."""
    for md in sorted(pm_dir.glob("*.md")):
        name = md.name
        if name.startswith(".") or name.endswith((".goal.md", ".archive.md")):
            continue
        track = name[:-3]
        goal = pm_dir / f"{track}.goal.md"
        if not goal.exists():
            yield track, md, "no goal file"
            continue
        try:
            head = goal.read_text(errors="replace")
        except OSError as exc:
            yield track, md, f"goal unreadable: {exc}"
            continue
        yield track, md, None if "_Status: OPEN_" in head else "goal not OPEN"


# ---------------------------------------------------------------- the run

def post(rung: int, text: str) -> bool:
    try:
        r = subprocess.run([BOSS_ALERT, str(rung), text],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"    POST FAILED: {exc}")
        return False
    if r.returncode != 0:
        print(f"    POST FAILED rc={r.returncode}: {r.stderr.strip()[:200]}")
        return False
    print(f"    posted: {r.stdout.strip()[:200]}")
    return True


def malformed_key(track: str, line: str) -> str:
    """Journal key for an unreadable marker.

    There is no `id` to use — that is often the thing that is wrong. The marker
    fragment is the next best thing: it survives the line moving up or down the
    section, and it changes when the breakage changes, which is when it is worth
    saying again.
    """
    i = line.find("[ladder")
    frag = (line[i:] if i >= 0 else line).strip()[:200]
    return f"{track}/malformed/{hashlib.sha1(frag.encode()).hexdigest()[:12]}"


def _attempt(track: str, path: Path, now: datetime, state: dict, counts: dict,
             seen: set, mal_seen: set):
    """One read-modify-write pass. Returns the new text, or None if unchanged.

    Raises Concurrent if the tracker changed under us between read and write.
    """
    def report_malformed(n: int, line: str, reason: str) -> None:
        # Said once to #claude-ops and then remembered, and the run still exits
        # 0. A unit that stays red hides the next failure (Lucas, 2026-09-18).
        counts["malformed"] += 1
        print(f"  {path.name}:{n + 1} MALFORMED, skipped: {reason}")
        key = malformed_key(track, line)
        mal_seen.add(key)
        if key in state["malformed"]:
            return
        text = (f"{track}: unreadable ladder marker at {path.name}:{n + 1} — "
                f"{reason} — nothing is escalating from that line")
        if DRY_RUN:
            print(f"    would post: boss-alert 0 {text!r}")
            return
        if post(0, text):
            state["malformed"][key] = {"at": now.isoformat(),
                                       "where": f"{path.name}:{n + 1}",
                                       "reason": reason}
            save_state(state)

    stat = path.stat()
    lines = path.read_text(errors="replace").splitlines(keepends=True)
    changed = False
    lo, hi = blockers_range(lines)
    for n in range(lo, hi):
        line = lines[n]
        try:
            found = scan_marker(line)
        except MarkerError as exc:
            report_malformed(n, line, str(exc))
            continue
        if not found:
            continue
        raw, fields = found
        try:
            m = validate(fields)
        except MarkerError as exc:
            report_malformed(n, line, str(exc))
            continue
        counts["markers"] += 1
        key = f"{track}/{m['id']}"
        seen.add(key)
        tag = f"  {path.name}:{n + 1} [{m['id']}]"
        if m["cleared"]:
            counts["cleared"] += 1
            state["markers"].pop(key, None)
            continue

        # Reconcile a crash around a post: the journal knows a rung went out that
        # the file never recorded. Adopt it rather than post it twice — a channel
        # that repeats itself becomes wallpaper.
        rec = state["markers"].get(key, {})
        if rec.get("last_posted", -1) > m["last"]:
            adopted = rec["last_posted"]
            print(f"{tag} ADOPTING rung {adopted} from the journal "
                  f"(file said {m['last']}); not re-posting")
            nxt = m["t0"] + timedelta(minutes=next_rung(adopted))
            if not DRY_RUN:
                lines[n] = line.replace(raw, rewrite(raw, adopted, nxt), 1)
                changed = True
            counts["adopted"] += 1
            continue

        elapsed = int((now - m["t0"]).total_seconds() // 60)
        if now < m["next"]:
            print(f"{tag} held until {m['next'].isoformat()} "
                  f"(elapsed {elapsed}m, last {m['last']})")
            continue

        # The boss never named the action. escalation.md wants one action per
        # alert; "see the tracker" is the unactionable alert that turns the
        # channel into wallpaper, so the rungs hold. But a blocker nobody has
        # defined after half an hour is itself worth knowing — say that once.
        if m["ask"].strip() == PLACEHOLDER:
            counts["placeholder"] += 1
            if elapsed < 30 or rec.get("placeholder_alerted"):
                print(f"{tag} ask= is still the placeholder, holding "
                      f"(elapsed {elapsed}m)")
                continue
            where = f" (pane {m['pane']})" if m["pane"] else ""
            text = (f"{track}: a blocker has sat {elapsed} min with no action "
                    f"named{where} — id {m['id']}, ask= in the tracker is still "
                    f"the placeholder")
            print(f"{tag} placeholder unfilled for {elapsed}m, saying so once")
            if DRY_RUN:
                print(f"    would post: boss-alert {elapsed} {text!r}")
                continue
            if post(elapsed, text):
                rec = dict(rec, placeholder_alerted=True)
                state["markers"][key] = rec
                save_state(state)
            continue

        if rec.get("stopped"):
            print(f"{tag} ladder stopped at 24 h, staying quiet")
            continue

        due = rung_for(elapsed)
        if due is None or due <= m["last"]:
            print(f"{tag} nothing due (elapsed {elapsed}m, last {m['last']})")
            continue

        # One rung per run, never a burst: Persistent=true means a laptop waking
        # after three hours would otherwise fire five at once.
        stopping = due >= STOP_MIN
        text = stop_text(track, m) if stopping else slack_text(track, m)
        print(f"{tag} DUE rung {due} (elapsed {elapsed}m, last {m['last']})")
        if DRY_RUN:
            print(f"    would post: boss-alert {due} {text!r}")
            continue
        # Record the intent before posting. If we die mid-post we do not know
        # whether it landed, and the adopt path above then declines to repeat it.
        state["markers"][key] = dict(rec, last_posted=due, t0=m["t0"].isoformat(),
                                     posted_at=now.isoformat(), pending=True)
        save_state(state)
        if not post(due, text):
            state["markers"][key].update(pending=False, last_posted=m["last"])
            save_state(state)
            continue
        state["markers"][key]["pending"] = False
        if stopping:
            # Said once, and never again for this blocker.
            state["markers"][key]["stopped"] = True
        save_state(state)
        nxt = m["t0"] + timedelta(minutes=next_rung(due))
        lines[n] = line.replace(raw, rewrite(raw, due, nxt), 1)
        changed = True
        counts["posted"] += 1

    if not changed:
        return None
    fresh = path.stat()
    if (fresh.st_mtime_ns, fresh.st_size) != (stat.st_mtime_ns, stat.st_size):
        raise Concurrent()
    return "".join(lines)


def process_tracker(track: str, path: Path, now: datetime, state: dict,
                    seen: set, mal_seen: set) -> dict:
    counts = {"markers": 0, "posted": 0, "cleared": 0, "malformed": 0,
              "adopted": 0, "placeholder": 0}
    with open(lock_path(path), "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        for attempt in range(3):
            counts = {k: 0 for k in counts}
            attempt_seen, attempt_mal = set(), set()
            try:
                text = _attempt(track, path, now, state, counts, attempt_seen,
                                attempt_mal)
            except Concurrent:
                # The boss's Edit tool takes no lock, so the flock alone does not
                # prove the file stood still. Re-read and redo; the journal keeps
                # the replayed pass from posting a rung twice.
                print(f"  {path.name} changed under us, retry {attempt + 1}/3")
                continue
            seen |= attempt_seen
            mal_seen |= attempt_mal
            if text is None:
                return counts
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".boss-ladder-")
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            os.chmod(tmp, path.stat().st_mode & 0o7777)
            os.replace(tmp, path)
            return counts
        print(f"  {path.name} kept changing, gave up after 3 tries")
    return counts


def run(now: datetime) -> int:
    state = load_state()
    totals = {"markers": 0, "posted": 0, "cleared": 0, "malformed": 0,
              "adopted": 0, "placeholder": 0, "vanished": 0}
    seen, mal_seen, scanned = set(), set(), set()
    for track, path, skip in open_tracks(PM_DIR):
        if skip:
            continue
        scanned.add(track)
        c = process_tracker(track, path, now, state, seen, mal_seen)
        for k in c:
            totals[k] += c[k]

    # A marker rewritten out of the tracker counts as cleared (Lucas, 2026-09-18):
    # say so once and never post about it again. Only for tracks we actually
    # walked — a goal that goes closed hides its markers, and that is not a clear.
    for key in [k for k in state["markers"] if k.split("/", 1)[0] in scanned]:
        if key not in seen:
            print(f"  {key} vanished from the tracker, counting as cleared")
            state["markers"].pop(key)
            totals["vanished"] += 1

    # An unreadable marker that is gone is forgotten, so the same breakage coming
    # back is worth saying again rather than being swallowed as already-reported.
    for key in [k for k in state["malformed"] if k.split("/", 1)[0] in scanned]:
        if key not in mal_seen:
            print(f"  {key} no longer present; forgetting it")
            state["malformed"].pop(key)

    if not DRY_RUN:
        save_state(state)
    print(f"markers={totals['markers']} posted={totals['posted']} "
          f"cleared={totals['cleared']} vanished={totals['vanished']} "
          f"adopted={totals['adopted']} placeholder={totals['placeholder']} "
          f"malformed={totals['malformed']}")
    # Always 0. A malformed marker is reported to #claude-ops once; a unit left
    # red on every tick hides the next failure.
    return 0


# ---------------------------------------------------------------- selftest

def _fixture(tmp: Path, track: str, body: str, status: str = "OPEN") -> Path:
    (tmp / f"{track}.goal.md").write_text(f"# Objective — {track}\n_Status: {status}_\n")
    p = tmp / f"{track}.md"
    p.write_text(body)
    return p


def _fake_alert(tmp: Path, ok: bool = True) -> Path:
    log = tmp / "posts.log"
    script = tmp / "fake-boss-alert"
    script.write_text("#!/usr/bin/env bash\n"
                      f'printf "%s\\t%s\\n" "$1" "$2" >> {log}\n'
                      f"exit {0 if ok else 1}\n")
    script.chmod(0o755)
    return script


def selftest() -> int:
    global PM_DIR, STATE, BOSS_ALERT, DRY_RUN, post
    import io
    import contextlib
    import shutil

    fails, checks = [], 0

    def check(name, got, want):
        nonlocal checks
        checks += 1
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    # --- the ladder itself: 5, 15, 30, then every 30
    for elapsed, want in [(0, None), (4, None), (5, 5), (14, 5), (15, 15),
                          (29, 15), (30, 30), (59, 30), (60, 60), (119, 60),
                          (120, 120), (239, 120), (240, 240), (1439, 1320),
                          (1440, 1440), (5000, 1440)]:
        check(f"rung_for({elapsed})", rung_for(elapsed), want)
    for r, want in [(5, 15), (15, 30), (30, 60), (60, 120), (120, 240),
                    (1320, 1440), (1440, 1440)]:
        check(f"next_rung({r})", next_rung(r), want)

    # --- parsing
    raw, f = scan_marker('- x [ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 '
                         'next=2026-09-18T10:58+02:00 pane=20:0.2 ask="do the thing"]')
    check("ask with spaces", f["ask"], "do the thing")
    check("pane", f["pane"], "20:0.2")
    check("raw ends at ]", raw.endswith("]"), True)
    check("no marker", scan_marker("- a plain blocker line, no marker"), None)
    check("[ladderish ignored", scan_marker("- see [ladderish] elsewhere"), None)
    r2, f2 = scan_marker('x [ladder id=ab12 t0=2026-09-18T10:53Z last=0 '
                         'next=2026-09-18T10:58Z ask="brackets ] inside"]')
    check("] inside a quoted value", f2["ask"], "brackets ] inside")

    for bad, why in [
        ('[ladder id=ab12 last=0 ask="x"]', "missing t0/next"),
        ('[ladder id=AB t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 ask="x"]', "bad id"),
        ('[ladder id=ab12 t0=2026-09-18T10:53 last=0 next=2026-09-18T10:58+02:00 ask="x"]', "naive t0"),
        ('[ladder id=ab12 t0=nope last=0 next=2026-09-18T10:58+02:00 ask="x"]', "unparseable t0"),
        ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=x next=2026-09-18T10:58+02:00 ask="x"]', "last not a number"),
        ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 ask=""]', "empty ask"),
        ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 next=2026-09-18T10:58+02:00 ask="x" wat=1]', "unknown field"),
    ]:
        checks += 1
        try:
            validate(scan_marker(bad)[1])
            fails.append(f"malformed accepted ({why}): {bad}")
        except MarkerError:
            pass
    for bad, why in [('[ladder id=ab12 ask="unterminated]', "no closing quote"),
                     ('[ladder id=ab12 ask="x"', "not closed"),
                     ('[ladder id]', "no '='"),
                     ('[ladder Id=ab12]', "bad field name"),
                     ('[ladder id=ab id=cd]', "duplicate field")]:
        checks += 1
        try:
            scan_marker(bad)
            fails.append(f"malformed token accepted ({why}): {bad}")
        except MarkerError:
            pass

    # --- rewrite touches only last= and next=
    before = ('[ladder id=ab12 t0=2026-09-18T10:53+02:00 last=0 '
              'next=2026-09-18T10:58+02:00 pane=20:0.2 ask="keep me"]')
    after = rewrite(before, 15, datetime(2026, 9, 18, 11, 23, tzinfo=timezone(timedelta(hours=2))))
    check("rewrite last", "last=15" in after, True)
    check("rewrite next", "next=2026-09-18T11:23:00+02:00" in after, True)
    check("rewrite keeps ask", 'ask="keep me"' in after, True)
    check("rewrite keeps t0", "t0=2026-09-18T10:53+02:00" in after, True)
    check("rewrite keeps pane", "pane=20:0.2" in after, True)

    tz = timezone(timedelta(hours=2))
    t0 = "2026-09-18T10:00+02:00"
    tmp = Path(tempfile.mkdtemp(prefix="boss-ladder-selftest-"))
    try:
        PM_DIR = tmp
        STATE = tmp / "state.json"
        BOSS_ALERT = str(_fake_alert(tmp))
        DRY_RUN = False

        due = _fixture(tmp, "duetrack", f'''# PM Tracker
## Open blockers
- plain line, no marker at all
- blocked on the owner [ladder id=due1 t0={t0} last=0 next=2026-09-18T10:05+02:00 pane=20:0.2 ask="put the u2 file on lab-0"]
- held by hand [ladder id=notdue1 t0={t0} last=30 next=2026-09-19T11:00+02:00 ask="deferred by hand"]
- done with [ladder id=clr1 t0={t0} last=5 next=2026-09-18T10:15+02:00 cleared=2026-09-18T10:20+02:00 ask="was blocked"]
''')
        _fixture(tmp, "closedtrack", f'''## Open blockers
- should never fire [ladder id=closed1 t0={t0} last=0 next=2026-09-18T10:05+02:00 ask="closed track"]
''', status="DONE")

        # 10:20 -> elapsed 20 -> rung 15 is due for due1; nothing else moves.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 10, 20, tzinfo=tz))
        posts = (tmp / "posts.log").read_text().splitlines()
        check("one post", len(posts), 1)
        check("rung label", posts[0].split("\t")[0], "15")
        check("track in text", posts[0].startswith("15\tduetrack: put the u2 file"), True)
        check("pane in text", "pane 20:0.2" in posts[0], True)
        body = due.read_text()
        check("last advanced", "id=due1 t0=2026-09-18T10:00+02:00 last=15" in body, True)
        check("next advanced", "next=2026-09-18T10:30:00+02:00" in body, True)
        check("cleared untouched", "id=clr1 t0=2026-09-18T10:00+02:00 last=5" in body, True)
        check("held-by-hand untouched", "id=notdue1 t0=2026-09-18T10:00+02:00 last=30" in body, True)
        check("held-by-hand said so", "held until 2026-09-19" in buf.getvalue(), True)
        check("closed track skipped", "closed1" in (tmp / "posts.log").read_text(), False)

        # Same minute again: next= now gates it. No second post.
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 10, 21, tzinfo=tz))
        check("no re-post in the hold", len((tmp / "posts.log").read_text().splitlines()), 1)

        # 13:00 -> elapsed 180. One rung per run, not a burst of five.
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 13, 0, tzinfo=tz))
        posts = (tmp / "posts.log").read_text().splitlines()
        check("one rung per run after a sleep", len(posts), 2)
        check("catch-up rung is 120", posts[1].split("\t")[0], "120")

        # A journal ahead of the file = a crash around a post. Adopt, don't repeat.
        st = json.loads(STATE.read_text())
        st["markers"]["duetrack/due1"]["last_posted"] = 300
        STATE.write_text(json.dumps(st))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 15, 30, tzinfo=tz))
        check("adopted, not re-posted", len((tmp / "posts.log").read_text().splitlines()), 2)
        check("adopt said so", "ADOPTING" in buf.getvalue(), True)
        check("file caught up", "id=due1 t0=2026-09-18T10:00+02:00 last=300" in due.read_text(), True)

        # ask= still the placeholder: hold under 30 min, say it once after.
        ph_t0 = "2026-09-18T14:00+02:00"
        ph = _fixture(tmp, "phtrack", f'''## Open blockers
- x [ladder id=ph01 t0={ph_t0} last=0 next=2026-09-18T14:05+02:00 pane=20:0.9 ask="(boss names it)"]
''')
        before_ph = len((tmp / "posts.log").read_text().splitlines())
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 14, 20, tzinfo=tz))
        check("placeholder holds under 30m",
              len((tmp / "posts.log").read_text().splitlines()), before_ph)
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 14, 40, tzinfo=tz))
        posts = (tmp / "posts.log").read_text().splitlines()
        check("placeholder says so once at 30m+", len(posts), before_ph + 1)
        check("placeholder text names the gap", "no action named" in posts[-1], True)
        check("placeholder leaves last=0", "id=ph01 t0=2026-09-18T14:00+02:00 last=0" in ph.read_text(), True)
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 15, 10, tzinfo=tz))
        check("placeholder never repeats",
              len((tmp / "posts.log").read_text().splitlines()), before_ph + 1)
        # Fill it in and the normal ladder takes over.
        ph.write_text(ph.read_text().replace('ask="(boss names it)"', 'ask="sign in to Cloudflare"'))
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 15, 20, tzinfo=tz))
        posts = (tmp / "posts.log").read_text().splitlines()
        check("filled ask resumes the ladder", len(posts), before_ph + 2)
        check("resumed text is the action", "sign in to Cloudflare" in posts[-1], True)

        # A failed post must not advance the marker.
        BOSS_ALERT = str(_fake_alert(tmp, ok=False))
        (tmp / "posts.log").unlink()
        fail_t0 = "2026-09-18T16:00+02:00"
        ft = _fixture(tmp, "failtrack", f'''## Open blockers
- x [ladder id=fail1 t0={fail_t0} last=0 next=2026-09-18T16:05+02:00 ask="will not post"]
''')
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 16, 20, tzinfo=tz))
        check("failed post leaves last=0", "id=fail1 t0=2026-09-18T16:00+02:00 last=0" in ft.read_text(), True)
        check("failed post leaves no journal rung",
              json.loads(STATE.read_text())["markers"]["failtrack/fail1"]["last_posted"], 0)

        # A tracker that changes while we are posting is retried, not clobbered.
        # That is the real window: the foreign write lands during the Slack call.
        checks += 1
        BOSS_ALERT = str(_fake_alert(tmp))   # the previous block left the failing one
        conc_t0 = "2026-09-18T18:00+02:00"
        cf = _fixture(tmp, "conctrack", f'''## Open blockers
- x [ladder id=conc1 t0={conc_t0} last=0 next=2026-09-18T18:05+02:00 ask="racy"]
''')
        real_post, fired = post, {"conc": 0}

        def racy_post(rung, text):
            # Only this track's post opens the window; the other fixtures are
            # still live at 18:20 and would otherwise trip it first.
            if not text.startswith("conctrack:"):
                return real_post(rung, text)
            fired["conc"] += 1
            if fired["conc"] == 1:
                cf.write_text(cf.read_text() + "- a line someone else added\n")
            return real_post(rung, text)

        globals()["post"] = racy_post
        try:
            with contextlib.redirect_stdout(io.StringIO()) as cbuf:
                run(datetime(2026, 9, 18, 18, 20, tzinfo=tz))
        finally:
            globals()["post"] = real_post
        if "changed under us" not in cbuf.getvalue():
            fails.append("concurrent write was not detected")
        check("foreign line survived", "someone else added" in cf.read_text(), True)
        check("retry did not post twice", fired["conc"], 1)
        check("retry still advanced the marker",
              "id=conc1 t0=2026-09-18T18:00+02:00 last=15" in cf.read_text(), True)

        # DRY_RUN writes nothing and posts nothing.
        BOSS_ALERT = str(_fake_alert(tmp))
        (tmp / "posts.log").write_text("")
        DRY_RUN = True
        dry_before = ft.read_text()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 20, 0, tzinfo=tz))
        check("DRY_RUN posts nothing", (tmp / "posts.log").read_text(), "")
        check("DRY_RUN writes nothing", ft.read_text(), dry_before)
        check("DRY_RUN says what it would post", "would post: boss-alert" in buf.getvalue(), True)
        # --- the 24 h stop: one final line, then quiet for good
        DRY_RUN = False
        sub = tmp / "stop"; sub.mkdir()
        PM_DIR, STATE = sub, sub / "state.json"
        BOSS_ALERT = str(_fake_alert(sub))
        _fixture(sub, "oldtrack", '''## Open blockers
- x [ladder id=old1 t0=2026-09-17T10:00+02:00 last=1320 next=2026-09-17T10:05+02:00 ask="ancient"]
''')
        for when in [(12, 0), (12, 5), (13, 0)]:
            with contextlib.redirect_stdout(io.StringIO()):
                run(datetime(2026, 9, 18, when[0], when[1], tzinfo=tz))
        posts = (sub / "posts.log").read_text().splitlines()
        check("24 h stop posts once", len(posts), 1)
        check("24 h stop rung", posts[0].split("\t")[0], "1440")
        check("24 h stop says so", "ladder stopped at 24 h, still open" in posts[0], True)
        check("24 h stop marks the journal",
              json.loads(STATE.read_text())["markers"]["oldtrack/old1"]["stopped"], True)

        # --- a marker rewritten out of the tracker counts as cleared
        sub = tmp / "vanish"; sub.mkdir()
        PM_DIR, STATE = sub, sub / "state.json"
        BOSS_ALERT = str(_fake_alert(sub))
        vt = _fixture(sub, "vtrack", '''## Open blockers
- x [ladder id=van1 t0=2026-09-18T10:00+02:00 last=0 next=2026-09-18T10:05+02:00 ask="going away"]
''')
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 10, 20, tzinfo=tz))
        check("vanish fixture posted first", len((sub / "posts.log").read_text().splitlines()), 1)
        check("vanish fixture is in the journal",
              "vtrack/van1" in json.loads(STATE.read_text())["markers"], True)
        vt.write_text("## Open blockers\n- x, the boss rewrote this line without the marker\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 11, 0, tzinfo=tz))
        check("vanished said once", "vanished from the tracker" in buf.getvalue(), True)
        check("vanished dropped from the journal",
              json.loads(STATE.read_text())["markers"], {})
        check("vanished posted nothing more",
              len((sub / "posts.log").read_text().splitlines()), 1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 12, 0, tzinfo=tz))
        check("vanished stays quiet", "vanished from the tracker" in buf.getvalue(), False)

        # --- prose outside ## Open blockers is not a marker
        # This is the 14:59 failure: a roster row documenting the format parsed
        # as a malformed marker and the routine exited 1 on every tick.
        sub = tmp / "scope"; sub.mkdir()
        PM_DIR, STATE = sub, sub / "state.json"
        BOSS_ALERT = str(_fake_alert(sub))
        _fixture(sub, "prose", '''# PM Tracker
## Roster
| Suraya | reads `[ladder id= t0= last= next= ask=]` markers |

## Open blockers
- a real one [ladder id=real1 t0=2026-09-18T10:00+02:00 last=0 next=2026-09-18T10:05+02:00 ask="the only action"]

## Notes
- the format is `[ladder ...]`, written by the hook
''')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(datetime(2026, 9, 18, 10, 20, tzinfo=tz))
        check("prose outside the section is not parsed", "MALFORMED" in buf.getvalue(), False)
        check("scoped run exits clean", rc, 0)
        check("the real marker still fired",
              len((sub / "posts.log").read_text().splitlines()), 1)
        check("and it is the right one",
              "the only action" in (sub / "posts.log").read_text(), True)
        check("a tracker with no blockers section is inert",
              blockers_range(["# T\n", "## Roster\n", "- x\n"]), (0, 0))
        # --- an unreadable marker: say it once, exit 0, forget it when it goes
        DRY_RUN = False
        sub = tmp / "mal"; sub.mkdir()
        PM_DIR, STATE = sub, sub / "state.json"
        BOSS_ALERT = str(_fake_alert(sub))
        good = ('- fine [ladder id=ok01 t0=2026-09-18T10:00+02:00 last=1440 '
                'next=2026-09-19T10:00+02:00 ask="quiet"]')
        bad = '- broken [ladder id=bad1 t0=nonsense last=0 next=2026-09-18T10:05+02:00 ask="x"]'
        mt = _fixture(sub, "maltrack", f"## Open blockers\n{good}\n{bad}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(datetime(2026, 9, 18, 10, 30, tzinfo=tz))
        posts = (sub / "posts.log").read_text().splitlines()
        check("malformed exits 0", rc, 0)
        check("malformed posts once", len(posts), 1)
        check("malformed names the file and line", "maltrack.md:3" in posts[0], True)
        check("malformed names the reason", "not ISO 8601" in posts[0], True)
        check("malformed says nothing escalates",
              "nothing is escalating from that line" in posts[0], True)
        check("malformed is in the journal",
              len(json.loads(STATE.read_text())["malformed"]), 1)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = run(datetime(2026, 9, 18, 11, 30, tzinfo=tz))
        check("malformed never repeats", len((sub / "posts.log").read_text().splitlines()), 1)
        check("still exits 0 while it sits there", rc, 0)

        # Fixed: the journal forgets it, so the same breakage later is news again.
        mt.write_text(f"## Open blockers\n{good}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 12, 30, tzinfo=tz))
        check("forgets a malformed line that is gone", "forgetting it" in buf.getvalue(), True)
        check("journal emptied", json.loads(STATE.read_text())["malformed"], {})
        mt.write_text(f"## Open blockers\n{good}\n{bad}\n")
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 13, 30, tzinfo=tz))
        check("the same breakage returning is said again",
              len((sub / "posts.log").read_text().splitlines()), 2)

        # A different breakage on the same line is its own report.
        mt.write_text(f"## Open blockers\n{good}\n"
                      '- broken [ladder id=ZZ t0=2026-09-18T10:00+02:00 last=0 '
                      'next=2026-09-18T10:05+02:00 ask="x"]\n')
        with contextlib.redirect_stdout(io.StringIO()):
            run(datetime(2026, 9, 18, 14, 30, tzinfo=tz))
        posts = (sub / "posts.log").read_text().splitlines()
        check("a different breakage is a new report", len(posts), 3)
        check("and it names the new reason", "is not [a-z0-9]" in posts[-1], True)

        # DRY_RUN reports nothing to Slack.
        DRY_RUN = True
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run(datetime(2026, 9, 18, 15, 30, tzinfo=tz))
        check("DRY_RUN posts no malformed alert",
              len((sub / "posts.log").read_text().splitlines()), 3)
        DRY_RUN = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for f in fails:
        print(f"FAIL {f}")
    print(f"selftest: {checks - len(fails)}/{checks} checks passed")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true",
                    help="run the fixture tests; posts nothing, touches no tracker")
    ap.add_argument("--now", help="ISO 8601 with offset, for testing")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    now = _parse_ts(a.now, "--now") if a.now else datetime.now().astimezone()
    return run(now)


if __name__ == "__main__":
    sys.exit(main())
