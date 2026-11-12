#!/usr/bin/env python3
"""The consent token: the owner's "yes" to a tests-alone merge, kept where a command can check it.

A `CONSENT:` question is asked by the boss in its own turn with `AskUserQuestion`. When the owner presses the
one affirmative button, the PostToolUse hook (`boss-guard.py`) writes `pm/consent/<session_id>.json`; every
completed Ask of that session first deletes the file, so a later question of any kind withdraws it. The commands
that act on the consent (`codex_blocker.py --choose TRACK tests-alone`, `boss_review.py --waive`) read the token
themselves and fail closed: a token that is missing, unreadable, malformed, expired, written for another session,
track or command, or whose directory cannot be read, denies.

A fail-closed guardrail against a session that runs the command without asking. It is not a boundary against a
process of the same user that forges the file on purpose (coverage.md, R26, accepted by the owner 2026-11-12).

    parse_question(text)       (track, command hash) a CONSENT question names, or None
    issue(sid, ...)            write the token, atomically, mode 0600
    revoke(sid)                delete it
    check(track, hash, ...)    (ok, reason): does this session hold a valid token for exactly this?
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

import boss_store
import policy

SCHEMA = 1
ACTION = "tests-alone"
AFFIRMATIVE = "Yes, merge on tests alone"       # the one option label that counts as consent
QUESTION_RE = re.compile(
    r"CONSENT: merge PRs of (?P<track>\S+) on tests alone while Codex is down \(no review of any kind\), "
    r"only where nothing deploys\? Command: (?P<cmd>\S(?:.*\S)?)", re.DOTALL)
SHA_RE = re.compile(r"sha256:(?P<hex>[0-9a-f]{64})")


def cmd_hash(cmd: str) -> str:
    return hashlib.sha256(cmd.encode("utf-8", "surrogatepass")).hexdigest()


def consent_dir(cfg=None) -> Path:
    return boss_store.pm_dir(cfg) / "consent"


def token_path(sid: str, cfg=None) -> Path | None:
    if not sid or not boss_store.SID_RE.match(sid):
        return None
    return consent_dir(cfg) / (sid + ".json")


def parse_question(text) -> tuple[str, str] | None:
    """(track, sha256 of the command) for a question of exactly the form the SKILL asks, else None. The
    command is written out, or as `sha256:<64 hex>` when it is too long to show."""
    if not isinstance(text, str):
        return None
    m = QUESTION_RE.fullmatch(text)
    if not m or not boss_store.valid_track(m.group("track")):
        return None
    cmd = m.group("cmd")
    sha = SHA_RE.fullmatch(cmd)
    return m.group("track"), (sha.group("hex") if sha else cmd_hash(cmd))


def issue(sid: str, track: str, command_hash: str, tool_use_id: str, now: float | None = None, cfg=None) -> bool:
    """Write the token for `sid`: a temp file of mode 0600 in the directory, then rename. False when it could
    not be written (said nowhere: a missing token denies, which is the safe side)."""
    path = token_path(sid, cfg)
    if path is None:
        return False
    now = time.time() if now is None else now
    body = {"schema": SCHEMA, "session_id": sid, "tool_use_id": str(tool_use_id), "action": ACTION,
            "track": track, "command_sha256": command_hash, "issued": int(now),
            "expires": int(now) + policy.CONSENT_TTL}
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True


def revoke(sid: str, cfg=None) -> None:
    path = token_path(sid, cfg)
    if path is not None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def read(sid: str, cfg=None) -> tuple[dict | None, str]:
    """(token, reason): the token as stored, or None and why not."""
    path = token_path(sid, cfg)
    if path is None:
        return None, "no usable session id"
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, "no consent token"
    except OSError as exc:
        return None, "the consent token cannot be read (%s)" % type(exc).__name__
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        return None, "the consent token is not a private regular file of yours"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "the consent token cannot be read (%s)" % type(exc).__name__
    if not isinstance(data, dict):
        return None, "the consent token is malformed"
    ok = (data.get("schema") == SCHEMA and data.get("action") == ACTION
          and all(isinstance(data.get(k), str) and data[k] for k in ("session_id", "tool_use_id", "track", "command_sha256"))
          and all(type(data.get(k)) is int for k in ("issued", "expires")))
    return (data, "") if ok else (None, "the consent token is malformed")


def check(track: str, command_hash: str, *, now: float | None = None, sid: str | None = None,
          same_as: dict | None = None, cfg=None) -> tuple[bool, str, dict | None]:
    """(ok, reason, token). `sid` defaults to $CLAUDE_CODE_SESSION_ID. The token must be this session's, for this
    track and this command hash, and `now` (default: the clock) must be before its expiry. With `same_as`, the
    token must also be the very one read earlier (same tool-use id and issue time): the tests ran in between,
    so the question is whether the owner's yes still stands, not whether ten minutes have passed since."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "") if sid is None else sid
    token, why = read(sid, cfg)
    if token is None:
        return False, why, None
    if token["session_id"] != sid:
        return False, "the consent token is another session's", None
    if token["track"] != track:
        return False, "the consent token is for track %s, not %s" % (token["track"], track), None
    if token["command_sha256"] != command_hash:
        return False, "the consent token is for another command", None
    if same_as is not None:
        if (token["tool_use_id"], token["issued"]) != (same_as["tool_use_id"], same_as["issued"]):
            return False, "the consent token was replaced", None
        return True, "", token
    when = time.time() if now is None else now
    if not (token["issued"] <= when < token["expires"]) or token["expires"] - token["issued"] > policy.CONSENT_TTL:
        return False, "the consent token has expired", None
    return True, "", token
