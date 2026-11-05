#!/usr/bin/env python3
"""PreToolUse guard for boss sessions — warns and logs; it denies one thing.

The boss skill has carried three pages of bold FORBIDDEN prose telling the
coordinator not to implement. Measured across 15 boss sessions it did not work:
983 Bash calls of which 35 were the lifecycle script, 238 Edits, 47 Writes, and
real source files changed. Prose that long stops reading as a rule.

A hard deny was the obvious fix and is the wrong one. The boss legitimately
needs `gh` for the board, the tracker wrapper, the alert wrapper, background
`sleep` for escalation timers, and — once the skill is split — its own
references/ files. Worse, a hook that misfires leaves the boss unable to inspect
the failure, and only the owner can unstick it from outside.

So this warns and records. The log is the thing the prose never produced:
evidence of which calls actually happen, so a later allowlist can be built from
data instead of imagination.

The one deny: AskUserQuestion, when this boss has a live concierge. An open
question stops the boss's turn, and the concierge exists so that it does not.
It cannot leave a boss stuck: no concierge, a dead one, or a tmux that does not
answer, and the question goes through as before. So does a question starting
`CONSENT:`, which only the boss's own turn can ask.

Active only for sessions that registered themselves as a boss:
    ~/.claude/pm/.boss-sessions/<session_id>
"""
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boss_store  # noqa: E402
import fleet  # noqa: E402
import registry  # noqa: E402


# Commands a coordinator genuinely runs. Everything else is a worker's job.
#
# Measured on pm/boss-guard.log 2026-09-20: 1,227 of 2,589 firings named one of
# these. `boss-goal`, `boss-start` and `team-line` were missing outright, and the
# rest arrived behind a `cd X &&` or `VAR=...` prefix that defeated a match
# anchored at position 0. Half the guard's volume was the boss being told off
# for running the boss's own commands — team-line most of all, which the harness
# instructs every session to run at the end of every turn.
ALLOWED_CMD = re.compile(
    r"^\s*(?:"
    r"(?:\S*/)?boss-lifecycle\.sh|"
    r"(?:\S*/)?boss-tracker|"
    r"(?:\S*/)?boss-alert|"
    r"(?:\S*/)?boss-goal|"
    r"(?:\S*/)?boss-start|"
    r"(?:\S*/)?boss-panes\.py|"
    r"(?:\S*/)?boss-run\b|"
    r"(?:\S*/)?team-line\b|"
    r"gh\b|"
    r"sleep\b|"
    r"date\b|"
    r"tmux\b"
    r")")

# `cd somewhere &&` and leading `VAR=value` assignments are shell throat-clearing,
# not the command. Strip them and the real head is what follows. Only a leading
# `cd` counts: `npm run build && cd x` is still a build.
PREFIX = re.compile(r"^\s*(?:cd\s+[^\s;&|]+\s*(?:&&|;)\s*|[A-Za-z_][A-Za-z0-9_]*=\S*\s*[;]?\s*)")


def strip_prefix(cmd, limit=6):
    """`cd /repo && B=bin; $B/boss-goal next` -> `$B/boss-goal next`."""
    for _ in range(limit):
        m = PREFIX.match(cmd)
        if not m or not m.group(0).strip():
            break
        cmd = cmd[m.end():]
    return cmd

# Paths the boss owns outright: its own state, and its own code.
#
# This was keyed to a literal `/.claude/skills/boss/`, which stopped being the
# boss's home when it became a plugin. Both halves are now computed, so the
# boundary follows the install rather than a string that used to be true. The
# literal `/.claude/pm/` stays as well, because a boss often writes the path in
# tilde or relative form and the resolved prefix would miss it.
PLUGIN = Path(os.environ.get("CLAUDE_PLUGIN_ROOT",
                             str(Path(__file__).resolve().parent.parent.parent)))
LOOSE = re.compile(r"/\.claude/pm/")


def owns(path):
    p = str(path)
    return p.startswith((str(boss_store.pm_dir()), str(PLUGIN))) or bool(LOOSE.search(p))


WRITERS = {"echo", "printf", "cat"}
FILTERS = {"tail", "head", "cut", "wc"}
HEREDOC = re.compile(r"""(?<!<)<<-?\s*(['"]?)(\w+)\1(?=\s|$|[;&|<>])""")
# `s/a/b/g`: one delimiter, no escapes, flags that neither write (`w`) nor run (`e`).
# No part holds the delimiter or a newline, so a `;` or a second command cannot be
# absorbed by a lazy group. Any other sed program is not read; it counts as work.
SED_SUBSTITUTE = re.compile(r"s([/|#,:@])(?:(?!\1)[^\\\n])*\1(?:(?!\1)[^\\\n])*\1[gpI0-9]*")
# the flags that take a value, per filter: `-c` is one for head and cut, none for wc
VALUE_FLAGS = {"head": {"-n", "-c"}, "tail": {"-n", "-c"}, "cut": {"-d", "-f", "-c", "-b"}, "wc": set()}
# the other flags a filter may carry, short ones only: a long option can open a file
# (`wc --files0-from`), and `tail -f` never ends. `-5`, `-n5` and `-d,` are attached forms.
COUNT_FLAG = re.compile(r"-(?:\d+|[nc]\d+)")
PLAIN_FLAGS = {"head": COUNT_FLAG, "tail": COUNT_FLAG,
               "cut": re.compile(r"-(?:[dfcb].+|s)"), "wc": re.compile(r"-[lwcm]+")}
DATE = re.compile(r"\$\(date(?:[ \t]+[^()`;&|<>\n]*)?\)")
SEPARATORS = {";", "&&", "|"}
REDIRECTS = {">", ">>", "<"}
MAX_PARSED = 20_000     # splitting 1 MB of quoted text took 28 s; the hook has 5


def own_state(path, cwd_own=False):
    """A path under pm/, or a plain relative one when the cwd is. A path with
    `..` or a variable in it is not read."""
    if ".." in path.split("/") or "$" in path:
        return False
    if path.startswith(("/", "~")):
        return bool(LOOSE.search(path)) or path.startswith(str(boss_store.pm_dir()) + "/")
    return cwd_own


def split_heredocs(cmd):
    """The command with heredoc bodies taken out, or None when a heredoc never
    closes. A line break between statements becomes `;`. A body whose delimiter
    is unquoted stays in the text, because the shell runs its substitutions."""
    lines, pending = [], None
    for line in cmd.strip().split("\n"):
        if pending is not None:
            delimiter, quoted = pending
            if line.strip() == delimiter:
                pending = None
            elif not quoted and ("$(" in line or "`" in line):
                return None
            continue
        found = HEREDOC.search(line)
        if found:
            before = line[:found.start()]
            if "#" in before or before.count("'") % 2 or before.count('"') % 2:
                return None     # the marker may be a comment or quoted text: not read
            pending = (found.group(2), bool(found.group(1)))
            line = before + line[found.end():]
        lines.append(line)
    return None if pending is not None else " ; ".join(lines)


def statement_is_coordination(words, cwd_own):
    """One statement: the boss's own tool, a stamp, or a write to its own state."""
    while words and re.match(r"(?:export$|[A-Za-z_]\w*=)", words[0]):
        words = words[1:]
    if not words:
        return True
    redirects = [i for i, w in enumerate(words) if w in (">", ">>")]
    if not all(i + 1 < len(words) and own_state(words[i + 1], cwd_own) for i in redirects):
        return False
    if ALLOWED_CMD.fullmatch(words[0]):
        return True
    if words[0] == "cat":
        # what cat reads is as much its business as what it writes
        inputs = [w for i, w in enumerate(words[1:], 1)
                  if i - 1 not in redirects and i not in redirects and w not in REDIRECTS]
        inputs += [words[i + 1] for i, w in enumerate(words) if w == "<" and i + 1 < len(words)]
        return bool(redirects) and all(w == "-" or own_state(w, cwd_own) for w in inputs)
    if words[0] in WRITERS:
        return True
    return (words[0] == "sed" and len(words) == 4 and words[1] == "-i"
            and bool(SED_SUBSTITUTE.fullmatch(words[2])) and own_state(words[3], cwd_own))


def filter_is_plain(words):
    """`head -n 5`, `cut -d , -f 2`, `wc -l`: flags and their values, no file, no `<`."""
    takes_value = False
    for w in words[1:]:
        if takes_value:
            takes_value = False
        elif w in VALUE_FLAGS.get(words[0], ()):
            takes_value = True
        elif w != "-" and not PLAIN_FLAGS[words[0]].fullmatch(w):
            return False
    return True


def is_coordination(cmd):
    """True when every statement of a Bash call is coordination.

    An Edit under pm/ was never flagged, and the same line appended from the
    shell was. Measured on 22 boss sessions: the appended line arrives between
    `cd pm`, a `$(date)` stamp and the team-line call, so the statements are
    judged one by one. One statement of anything else flags the call, and so
    does text that does not parse or a substitution other than `date`. A script
    is never coordination, wherever it runs: its reach cannot be read from its
    text, and an unlogged edit costs more here than a noisy line.
    """
    if len(cmd) > MAX_PARSED:
        return False
    text = split_heredocs(DATE.sub("STAMP", cmd))
    if text is None or "$(" in text or "`" in text:
        return False
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    cwd_own, words, piped, used, cd_dirs = False, [], False, False, []
    for token in tokens + [";"]:
        if token not in SEPARATORS:
            if not token.strip("();<>|&") and token not in REDIRECTS:
                return False          # `||`, `&`, a subshell: not read further
            words.append(token)
            continue
        if words:
            if words[0] == "cd" and len(words) == 2:
                cwd_own = own_state(words[1].rstrip("/") + "/")
                cd_dirs.append(os.path.expanduser(words[1]))
            elif piped and words[0] in FILTERS:
                if not filter_is_plain(words):
                    return False
            elif statement_is_coordination(words, cwd_own):
                used = True
            else:
                return False
        words, piped = [], token == "|"
        if token != "&&":
            # after `;` the next statement runs even when a cd of the chain failed
            if not all(os.path.isdir(d) for d in cd_dirs):
                cwd_own = False
            cd_dirs = []
    return used


CONSENT = "CONSENT:"
WATCHED = {"Bash", "Edit", "Write", "NotebookEdit", "Read", "Glob", "Grep", "Agent"}


def starts_teammate(ti):
    """True when this Agent call launches an agent-teams teammate.

    With CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS on, the harness turns any Agent call
    that carries a `name` into a teammate, except a fork or a call that passes
    `isolation`, which still run as subagents.
    """
    return bool(ti.get("name")) and ti.get("subagent_type") != "fork" \
        and not ti.get("isolation")


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def bump(sid):
    """Count this firing against the session. Returns the new total.

    Measured on pm/boss-guard.log 2026-09-20: 2,589 firings across 21 sessions
    in 14 days, one of them 725 on its own. The hook said the same 330-character
    sentence every time — about 215,000 tokens, of which everything after the
    first carried no information. The count is what carries information after
    that, so keep it per session and let main() decide when to speak.
    """
    def count(st):
        st["n"] = int(st.get("n") or 0) + 1

    return boss_store.update_state(sid, "guard", count)["n"]


def ti_questions(payload):
    return (payload.get("tool_input") or {}).get("questions") or []


def is_consent(questions):
    """A question for the owner's consent to a gated action. A peer message is never
    consent, so this one has to be asked in the boss's own turn."""
    return any(str(q.get("question") or "").startswith(CONSENT) for q in questions
               if isinstance(q, dict))


def concierge_name(sid):
    """The name of this boss's live concierge, or None."""
    try:
        seats = fleet.view(fleet.Tmux(timeout=3), registry.live(boss_store.config_dir()))
    except fleet.TmuxUnavailable:
        return None
    me = fleet.seat_of(seats, sid=sid)
    seat = fleet.concierge_of(seats, me.pane.id) if me else None
    return (seat.session.get("name") or seat.pane.coord) if seat else None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    sid = payload.get("session_id") or ""
    if not boss_store.is_boss(sid):
        return 0                      # not a boss session; nothing to say

    tool = payload.get("tool_name") or ""
    if tool == "AskUserQuestion":
        name = None if is_consent(ti_questions(payload)) else concierge_name(sid)
        if name:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"An open question stops your turn. Send it to your concierge "
                        f"{name} by SendMessage, starting `ASK <id>:`, with "
                        f"notify_when_idle: true, and keep dispatching whatever does "
                        f"not depend on the answer. See references/concierge.md."),
                }
            }))
        return 0
    if tool not in WATCHED:
        return 0
    ti = payload.get("tool_input") or {}

    detail = ""
    if tool == "Bash":
        cmd = (ti.get("command") or "").strip()
        if ALLOWED_CMD.match(cmd) or ALLOWED_CMD.match(strip_prefix(cmd)) or is_coordination(cmd):
            return 0
        detail = cmd[:200]
    elif tool == "Agent":
        detail = str(ti.get("name") or ti.get("description") or "")[:200]
    else:
        fp = ti.get("file_path") or ti.get("path") or ti.get("pattern") or ""
        if owns(fp):
            return 0
        detail = str(fp)[:200]

    try:
        boss_store.markers_dir().mkdir(parents=True, exist_ok=True)
        with (boss_store.pm_dir() / "boss-guard.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session": sid,
                "tool": tool,
                "detail": detail,
            }) + "\n")
    except OSError:
        pass

    n = bump(sid)
    if tool == "Agent" and starts_teammate(ti):
        # Every one is said. A teammate has no pane and no stamp, so nothing else
        # the boss runs (list --mine, the pulse, the workers watch) will ever
        # mention it; the throttle below is for the cheap, frequent calls.
        msg = (f"Boss guard: Agent with name `{detail[:60]}` starts an agent-teams "
               f"teammate — no pane, invisible to `list --mine` and the pulse, and "
               f"it dies with you. A boss never leads teammates: dispatch to a "
               f"worker. (Not blocked; logged.)")
    elif n == 1:
        msg = (f"Boss guard: this session is coordinating, and {tool} on "
               f"`{detail[:90]}` is implementation work. Dispatch it to a worker "
               f"instead. (Not blocked, and recorded in pm/boss-guard.log — if this "
               f"really is coordination, say so and carry on.)")
    elif n & (n - 1) == 0:
        # Powers of two. Repeating the sentence says nothing; the running total
        # does, and it grows louder exactly as the problem does. Across the 21
        # logged sessions this speaks 137 times instead of 2,589.
        msg = (f"Boss guard: {tool} on `{detail[:60]}` — your {ordinal(n)} "
               f"implementation-shaped call this session. Dispatch, or say why not.")
    else:
        return 0                      # logged, not spoken
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
