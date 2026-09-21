#!/usr/bin/env python3
"""Measure TypeSafe Jev on the boss's per-event judgments (#76, 2026-09-18).

For each labelled event in the sample (a worker report or idle notice as the
/boss session received it), build the state the boss had (its last dispatch to
that worker, the report, the tracker note, the worker's context size, whether a
handoff file is on disk) and ask Jev five typed questions:

  task_complete  noul    is the reported work finished
  evidenced      noul    does every done-claim carry a path, exit code, SHA or count
  next_action    choice  dispatch / park / restart / ask_worker / escalate
  needs_owner    noul    does the next step need the owner's own hand
  redirected     noul    did the owner redirect this worker in its pane

Dry run by default: prints the request for one event (--event evNN) or checks
every request for leaks and prints its size. Nothing leaves the machine.

--send calls POST https://api.typesafe.ai/v1/systemone (TYPESAFE_API_KEY from
~/.config/tiroir/typesafe.env), saves each response next to the sample and
scores the answers against the hand labels: accuracy per question, and accuracy
on the subset answered at confidence >= 0.85. The classifier blocks sending
transcripts from a Claude session, so the owner runs --send themselves with `!`.

Redaction runs on every string before it enters a request, and a second pass
(leaks()) re-scans the serialised request and refuses to send if anything
host-, path-, person- or key-shaped survived. Tests: test_boss_event_jev.py.

Usage:
  boss-event-jev.py [--event ev12]          dry run
  boss-event-jev.py --send [--event ev12]   call the API, save, score
  boss-event-jev.py --score                 score the saved results again
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
KEY_FILE = os.path.expanduser("~/.config/tiroir/typesafe.env")
PLANS = os.path.expanduser("~/.claude/plans")
SAMPLE = f"{PLANS}/2026-09-18-boss-jev-sample.jsonl"
RESULTS = f"{PLANS}/2026-09-18-boss-jev-results.jsonl"
SCORE = f"{PLANS}/2026-09-18-boss-jev-score.json"
CONF = 0.85

# --- redaction ----------------------------------------------------------------
# Every replacement is a typed placeholder, so a path or a hash still reads as
# evidence to the model ("<ROOT_PATH>", "<HASH>") without its value.

# The host and person names to redact are YOUR fleet and YOUR colleagues, so
# they are site configuration and live outside this repository. Publishing the
# denylist would disclose exactly what the denylist exists to protect.
#
# Point BOSS_REDACT_LIST at a JSON file shaped like tools/boss-redact.example.json:
#     {"hosts": ["box-one", "box-two"], "persons": ["A Name"]}
# Longest first: "box-one-dev" must come before "box-one", or it is cut to
# "<HOST>-dev". The loader sorts by length, so order in the file does not matter.
#
# With no file, both lists are empty: the pattern rules below (keys, bearer
# tokens, URLs, emails, IPs, paths) still run, and nothing here invents a name
# to redact. Every run reports what it loaded.
REDACT_FILE = Path(os.environ.get(
    "BOSS_REDACT_LIST",
    str(Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        / "boss-redact.json")))


def _load_redact():
    """hosts, persons, and the owner's own name.

    `owner` is separate from `persons` because it maps to OWNER rather than
    <PERSON>: the model is asked whether a step needs the owner's own hand, so
    it has to be able to tell that one person from the rest. With no name
    configured the rule never fires and the owner is simply not recognised.
    """
    try:
        data = json.loads(REDACT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], [], ""
    longest = lambda xs: sorted({str(x) for x in xs if str(x).strip()},
                                key=len, reverse=True)
    return (longest(data.get("hosts") or []),
            longest(data.get("persons") or []),
            str(data.get("owner") or "").strip())


HOSTS, PERSONS, OWNER_NAME = _load_redact()
TOKEN_FILE = (
    r"(?:[\w./-]*/)?(?:library-tokens[\w.-]*|door-e2e-[\w.-]*\.txt|[\w.-]*\.env(?:\.[\w-]+)?"
    r"|\.env(?:\.[\w-]+)?|[\w.-]*creds?[\w.-]*|[\w.-]*secrets?[\w.-]*\.\w+|[\w.-]+\.(?:pem|key))"
)

_RULES = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "<PRIVATE_KEY>"),
    ("prefixed_key", re.compile(r"\b(?:sk|pk|rk|apik|ghp|gho|ghs|ghu|github_pat|glpat|xox[abprs]|AKIA|AIza)[-_A-Za-z0-9]{10,}"), "<SECRET>"),
    ("bearer", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1<SECRET>"),
    ("key_value", re.compile(r"(?i)\b([A-Z0-9_]*(?:password|passwd|secret|token|api[_-]?key|webhook[_-]?url))(\s*[=:]\s*)(?!<)[^\s'\"`,;]+"), r"\1\2<SECRET>"),
    ("url", re.compile(r"\bhttps?://[^\s'\"`<>)\]]+"), "<URL>"),
    # The domain must end in letters, so root@<ip> keeps its <IP> label.
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    ("socket", re.compile(r"(?:uds:)?/run/user/\d+/[\w./-]+"), "<SOCKET>"),
    ("token_file", re.compile(TOKEN_FILE), "<TOKEN_FILE>"),
    ("root_path", re.compile(r"/root(?:/[^\s'\"`,;)\]]*)?"), "<ROOT_PATH>"),
    ("etc_tiroir", re.compile(r"/etc/tiroir(?:/[^\s'\"`,;)\]]*)?"), "<ETC_PATH>"),
    ("home", re.compile(r"/home/[\w.-]+"), "~"),
    ("ipv4", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"), "<IP>"),
    ("domain", re.compile(r"(?<![\w.-])(?:[a-z0-9-]+\.)+(?:me|com|net|org|io|ai|app|dev|test|it|be|fr|eu|ts\.net)(?![\w-])", re.I), "<HOST>"),
    # An empty HOSTS would compile to `(?:)`, which matches at every position.
    # A pattern that can never match is the right empty case.
    ("host", re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(h) for h in HOSTS) + r")(?![\w])"
                        if HOSTS else r"(?!x)x"), "<HOST>"),
    # A channel id carries a digit; without that, "CONSTRAINT" is a channel.
    ("slack_id", re.compile(r"\b(?:C(?=[A-Z0-9]*\d)[A-Z0-9]{8,12}|\d{10}\.\d{6})\b"), "<SLACK_ID>"),
    ("hash", re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32,}(?![0-9a-fA-F])"), "<HASH>"),
    ("long_token", re.compile(r"(?<![\w/=+-])(?=[A-Za-z0-9_+=]*\d)(?=[A-Za-z0-9_+=]*[A-Za-z])[A-Za-z0-9_+=]{32,}(?![\w/=+-])"), "<LONG_TOKEN>"),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b"), "<IBAN>"),
    ("codice_fiscale", re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b"), "<CODICE_FISCALE>"),
    ("phone", re.compile(r"(?<![\d.])(?:\+\d{2}[\s.]?)?3\d{2}[\s.]?\d{6,7}(?![\d.])"), "<PHONE>"),
    ("owner", re.compile(r"(?i)" + re.escape(OWNER_NAME)
                         if OWNER_NAME else r"(?!x)x"), "OWNER"),
    # Same trap as HOSTS: an empty alternation matches everywhere, which would
    # stamp <PERSON> between every character.
    ("person", re.compile(r"(?i)(?<![A-Za-z])(?:" + "|".join(re.escape(p) for p in PERSONS) + r")(?![A-Za-z])"
                          if PERSONS else r"(?!x)x"), "<PERSON>"),
]


def redact(text):
    if not isinstance(text, str):
        return text
    for _, pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


# What must never appear in a request, checked on the serialised JSON after
# redaction. Deliberately wider than one rule each, so a bug in a rule above
# shows up here instead of in a request.
_LEAKS = [
    ("ipv4", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("root_path", re.compile(r"/root\b")),
    ("etc_tiroir", re.compile(r"/etc/tiroir")),
    ("home_path", re.compile(r"/home/")),
    ("host", re.compile(r"(?i)"
                        + ("|".join(re.escape(h) for h in HOSTS) + "|" if HOSTS else "")
                        + r"tail[0-9a-f]+\.ts\.net")),
    ("token_file", re.compile(r"library-tokens|door-e2e-|\.env\b|slack\.env|typesafe\.env")),
    ("key_shaped", re.compile(r"\b(?:sk|ghp|gho|xox[abprs]|AKIA|glpat)[-_][A-Za-z0-9]{8,}|[0-9a-fA-F]{32,}")),
    ("person", re.compile(r"(?i)" + "|".join(re.escape(n) for n in PERSONS)
                          if PERSONS else r"(?!x)x")),
    ("url", re.compile(r"https?://")),
]


def leaks(obj):
    """Names and positions of anything in the serialised object that should
    have been redacted. Empty means the request may be sent."""
    s = json.dumps(obj, ensure_ascii=False)
    found = []
    for name, pat in _LEAKS:
        for m in pat.finditer(s):
            found.append((name, m.start()))
    return found


# --- request --------------------------------------------------------------------

BOSS_RULES = [
    "The boss coordinates several worker sessions and reads each worker's report.",
    "A worker whose task is finished, whose handoff file is on disk and whose context is above "
    "400,000 tokens is restarted by the boss without asking OWNER.",
    "Merging on a reviewer's GO and running a staged, rollback-ready apply are the boss's call.",
    "Only OWNER can: create a credential or password file, sign in through a browser, change "
    "Claude Code settings or permission rules, pay for something.",
    "At most two workers are busy at once; the others are parked until a task can start.",
]

QUESTIONS = {
    "task_complete": {
        "type": "noul",
        "instructions": "Does `report` say that the work it reports on is finished, with nothing "
                        "left for this worker to do on it?",
        "criteria": {
            "true": "The report states that the task or check it was given is done: applied, "
                    "merged, staged as asked, answered, cleaned up, or oriented and parked.",
            "false": "The report is a progress update, says work is still running or waiting on a "
                     "review or a person, says a step was refused, interrupted or blocked, or only "
                     "acknowledges an instruction.",
        },
    },
    "evidenced": {
        "type": "noul",
        "instructions": "Does every claim of finished work in `report` come with concrete evidence: "
                        "a file path, an exit code, a commit SHA or PR head, or a count or value "
                        "read from the system?",
        "criteria": {
            "true": "Each claim that something is done names such evidence.",
            "false": "At least one claim that something is done has no such evidence, or the "
                     "report claims no finished work at all.",
        },
    },
    "next_action": {
        "type": "choice",
        "instructions": "Given `report`, `dispatch`, `worker` and `boss_rules`, what should the boss "
                        "do next with this worker?",
        "criteria": {
            "dispatch": "Send this worker a new or changed instruction now: its next task, a go on "
                        "something it proposed, an answer to its question, or a correction to how "
                        "it works.",
            "park": "Send nothing and let the worker wait: it is mid-task with nothing to decide, "
                    "or waiting on something already requested, or no next task can start yet.",
            "restart": "Restart the worker's session: its task is finished, its handoff file is on "
                       "disk, and its context is above 400,000 tokens.",
            "ask_worker": "Ask the worker for something missing from the report before deciding: "
                          "a verdict, a SHA, or a result it did not state.",
            "escalate": "Take it to OWNER: the only way forward is an action that only OWNER can "
                        "take.",
        },
    },
    # Question ids travel to the API too (the model does not see them), so a
    # sample whose hand labels use a different key needs BOSS_JEV_LABEL_MAP.
    "needs_owner": {
        "type": "noul",
        "instructions": "Does `report` show that the next step needs an action that only OWNER can "
                        "take, as listed in `boss_rules`?",
        "criteria": {
            "true": "A credential or password file OWNER must create, a browser sign-in, a change to "
                    "Claude Code settings or permission rules, a purchase, or a decision the report "
                    "says is reserved to OWNER.",
            "false": "Anything the boss or a worker can do: merges on a GO, staged applies, "
                     "restarts, fixes, new tasks, or waiting on a review that is running.",
        },
    },
    "redirected": {
        "type": "noul",
        "instructions": "Does `report` say that OWNER gave this worker a new instruction directly in "
                        "the worker's own pane, different from `dispatch`?",
        "criteria": {
            "true": "The report says OWNER typed a new or different instruction to this worker.",
            "false": "The report says OWNER gave it nothing, or does not mention OWNER speaking to it.",
        },
    },
}


def build_state(row):
    s = row["state"]
    ctx = s.get("worker_context_tokens")
    return {
        "boss_rules": BOSS_RULES,
        "worker": {
            "name": row["worker"],
            "event": "idle notice from the worker's harness" if row["kind"] == "idle_notice"
                     else "message from the worker",
            "context_tokens": ctx if ctx is not None else "unknown",
            "handoff_file_on_disk": bool(s.get("handoff_on_disk")),
        },
        "dispatch": redact(s.get("dispatch") or "(no dispatch found)"),
        "report": redact(s["report"]),
        "tracker_note": redact(s.get("tracker_note") or ""),
    }


def build_request(row):
    return {"model": MODEL, "state": build_state(row), "questions": QUESTIONS}


# --- scoring --------------------------------------------------------------------

def judge(qid, answer):
    """(predicted label, confidence) for one answer. Noul has no confidence
    field; its confidence here is max(p, 1 - p)."""
    if answer.get("type") == "noul":
        p = float(answer["noul"])
        return p >= 0.5, max(p, 1 - p)
    return answer["choice"], float(answer.get("confidence", 0.0))


# Maps a question id to the key its hand label uses in the sample, for a sample
# labelled before the ids settled. Identity by default.
#     BOSS_JEV_LABEL_MAP='{"needs_owner": "needs_owner_old"}'
try:
    LABEL_OF = json.loads(os.environ.get("BOSS_JEV_LABEL_MAP") or "{}")
except ValueError:
    LABEL_OF = {}


def score(pairs):
    """pairs: [(row, answers)]. Returns {qid: stats} plus misses."""
    out = {}
    for qid in QUESTIONS:
        n = right = hi_n = hi_right = 0
        misses = []
        for row, answers in pairs:
            if qid not in answers:
                continue
            pred, conf = judge(qid, answers[qid])
            truth = row["labels"][LABEL_OF.get(qid, qid)]
            ok = pred == truth
            n += 1
            right += ok
            if conf >= CONF:
                hi_n += 1
                hi_right += ok
            if not ok:
                misses.append({"id": row["id"], "label": truth, "jev": pred, "conf": round(conf, 3)})
        out[qid] = {
            "n": n,
            "accuracy": round(right / n, 3) if n else None,
            "n_conf_ge_0.85": hi_n,
            "coverage_conf_ge_0.85": round(hi_n / n, 3) if n else None,
            "accuracy_conf_ge_0.85": round(hi_right / hi_n, 3) if hi_n else None,
            "misses": misses,
        }
    return out


def print_score(sc):
    print(f"\n{'question':<15}{'n':>4}{'acc':>8}{'n@.85':>8}{'cover':>8}{'acc@.85':>9}")
    for qid, s in sc.items():
        fmt = lambda v: "-" if v is None else f"{v:.3f}"
        print(f"{qid:<15}{s['n']:>4}{fmt(s['accuracy']):>8}{s['n_conf_ge_0.85']:>8}"
              f"{fmt(s['coverage_conf_ge_0.85']):>8}{fmt(s['accuracy_conf_ge_0.85']):>9}")
    for qid, s in sc.items():
        for m in s["misses"]:
            print(f"  miss {qid} {m['id']}: label={m['label']} jev={m['jev']} conf={m['conf']}")


# --- I/O ------------------------------------------------------------------------

def load_sample(path=SAMPLE):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def api_key():
    with open(KEY_FILE) as fh:
        for line in fh:
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"TYPESAFE_API_KEY not found in {KEY_FILE}")


def post(body, key, attempts=4):
    data = json.dumps(body).encode()
    for i in range(attempts):
        req = urllib.request.Request(API, data=data, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and i < attempts - 1:
                time.sleep(2 ** i)
                continue
            raise SystemExit(f"API error {e.code}: {e.read()[:300]!r}")
    raise SystemExit("API: retries exhausted")


def write_private(path, lines):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--event", help="one event id from the sample, e.g. ev12")
    ap.add_argument("--send", action="store_true", help="call the API (default: dry run)")
    ap.add_argument("--score", action="store_true", help="score the saved results file again")
    ap.add_argument("--sample", default=SAMPLE)
    args = ap.parse_args()

    rows = load_sample(args.sample)
    if args.event:
        rows = [r for r in rows if r["id"] == args.event]
        if not rows:
            raise SystemExit(f"no event {args.event} in {args.sample}")

    if args.score:
        saved = {}
        with open(RESULTS, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                saved[r["id"]] = r["answers"]
        pairs = [(r, saved[r["id"]]) for r in rows if r["id"] in saved]
        sc = score(pairs)
        print_score(sc)
        return 0

    requests = [(r, build_request(r)) for r in rows]
    bad = [(r["id"], leaks(req)) for r, req in requests]
    bad = [(i, lk) for i, lk in bad if lk]
    if bad:
        for i, lk in bad:
            print(f"LEAK {i}: " + ", ".join(sorted({n for n, _ in lk})), file=sys.stderr)
        print("refusing: redaction left host-, path-, person- or key-shaped text in a request",
              file=sys.stderr)
        return 2

    if not args.send:
        if args.event:
            print(json.dumps(requests[0][1], indent=2, ensure_ascii=False))
        total = sum(len(json.dumps(q, ensure_ascii=False)) for _, q in requests)
        print(f"dry run: {len(requests)} request(s), leak check clean, {total} chars in all "
              f"(~{total // 4} tokens). Nothing sent. --send to call {API}.", file=sys.stderr)
        return 0

    key = api_key()
    results, pairs = [], []
    for r, req in requests:
        res = post(req, key)
        results.append({"id": r["id"], "answers": res.get("answers", {}), "usage": res.get("usage"),
                        "model": res.get("model")})
        pairs.append((r, res.get("answers", {})))
        print(f"  {r['id']} ok ({(res.get('usage') or {}).get('input_tokens', '?')} input tokens)",
              file=sys.stderr)
    if not args.event:
        write_private(RESULTS, results)
    sc = score(pairs)
    usage = sum((x.get("usage") or {}).get("input_tokens", 0) for x in results)
    if not args.event:
        write_private(SCORE, [{"conf_threshold": CONF, "events": len(pairs),
                               "input_tokens": usage, "questions": sc}])
        print(f"results: {RESULTS}\nscore:   {SCORE}")
    print_score(sc)
    print(f"\ninput tokens in all: {usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
