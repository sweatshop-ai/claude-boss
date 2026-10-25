#!/usr/bin/env python3
"""Tests for boss-panes.py --state and boss-lifecycle.sh retire --require-idle.

Run: python3 skills/boss/test_boss_lifecycle.py

Every test runs against a throwaway CLAUDE_CONFIG_DIR. tmux and boss-panes.py
are stubs; no test changes a real pane.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


class PanesState(unittest.TestCase):
    def load_panes(self, cfg):
        os.environ["CLAUDE_CONFIG_DIR"] = str(cfg)
        try:
            spec = importlib.util.spec_from_file_location("bp%d" % time.monotonic_ns(), str(HERE / "boss-panes.py"))
            bp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bp)
        finally:
            os.environ.pop("CLAUDE_CONFIG_DIR")
        return bp

    def test_state_refuses_a_record_without_a_matching_procstart(self):
        tmp = Path(tempfile.mkdtemp())
        kid = subprocess.Popen(["sleep", "30"])
        try:
            (tmp / "sessions").mkdir()
            bp = self.load_panes(tmp)
            os.environ["CLAUDE_CONFIG_DIR"] = str(tmp)
            bp.TMUX = bp.fleet.MemoryTmux([bp.fleet.Pane("%7")])   # tmux, the one thing faked
            stat = Path("/proc/%d/stat" % kid.pid).read_text()
            real = stat[stat.rindex(")") + 2:].split()[19]
            outs = []
            for ps in (None, "1", real):
                rec = {"pid": kid.pid, "sessionId": "s1", "status": "idle", "cwd": str(tmp),
                       "tmux": "w:@1.%7"}
                if ps is not None:
                    rec["procStart"] = ps
                (tmp / "sessions" / ("%d.json" % kid.pid)).write_text(json.dumps(rec))
                import io, contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    old = sys.argv
                    sys.argv = ["boss-panes.py", "--state", "%7"]
                    try:
                        bp.main()
                    finally:
                        sys.argv = old
                outs.append(buf.getvalue().split("\t")[0])
            self.assertEqual(outs, ["-", "-", "s1"])
        finally:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            kid.kill()
            kid.wait()
            shutil.rmtree(tmp)

    def set_name(self, with_agent_name):
        """Run --set-name for pane %7 against a live peer; returns (peer name, agent-name calls)."""
        tmp = Path(tempfile.mkdtemp())
        kid = subprocess.Popen(["sleep", "30"])
        old_path, old_argv = os.environ.get("PATH", ""), sys.argv
        try:
            (tmp / "sessions").mkdir()
            stat = Path("/proc/%d/stat" % kid.pid).read_text()
            (tmp / "sessions" / ("%d.json" % kid.pid)).write_text(json.dumps(
                {"pid": kid.pid, "sessionId": "s1", "cwd": str(tmp), "name": "derived", "tmux": "w:@1.%7",
                 "nameSource": "derived", "procStart": stat[stat.rindex(")") + 2:].split()[19]}))
            bindir = tmp / "bin"
            bindir.mkdir()
            calls = tmp / "calls"
            if with_agent_name:
                fake = bindir / "agent-name"
                fake.write_text("#!/bin/sh\necho \"$@\" >> %s\necho \"$3\"\n" % calls)
                fake.chmod(0o755)
            os.environ["PATH"] = str(bindir) + os.pathsep + "/usr/bin:/bin"
            bp = self.load_panes(tmp)
            bp.TMUX = bp.fleet.MemoryTmux([bp.fleet.Pane("%7")])
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                sys.argv = ["boss-panes.py", "--set-name", "%7", "reviewer-1"]
                bp.main()
            name = json.loads((tmp / "sessions" / ("%d.json" % kid.pid)).read_text())["name"]
            return name, calls.read_text().split("\n")[0] if calls.exists() else None
        finally:
            os.environ["PATH"], sys.argv = old_path, old_argv
            kid.kill()
            kid.wait()
            shutil.rmtree(tmp)

    def test_set_name_goes_through_agent_name_when_it_is_installed(self):
        # cc-agent-names keeps an assigned name across the next prompt and a
        # resume only when it is told; a direct write is undone by its hook.
        name, call = self.set_name(with_agent_name=True)
        self.assertEqual(call, "set s1 reviewer-1")
        self.assertEqual(name, "derived")              # the fake wrote nothing itself

    def test_set_name_writes_the_peer_file_without_agent_names(self):
        name, call = self.set_name(with_agent_name=False)
        self.assertIsNone(call)
        self.assertEqual(name, "reviewer-1")


# ------------------------------------------------- boss-lifecycle --require-idle

STUB_TMUX = r'''#!/usr/bin/env bash
# records every call; answers display-message from $STUB_DIR
echo "$*" >> "$STUB_DIR/calls"
case "$1" in
  display-message)
    fmt="${@: -1}"
    case "$fmt" in
      '#{pane_id}') echo '%5' ;;
      '#{@boss_pane}') echo '' ;;
      '#{pane_current_command}') cat "$STUB_DIR/cmd" ;;
      *) echo '' ;;
    esac ;;
  send-keys)
    if [[ "$*" == *"/exit"* && -f "$STUB_DIR/exits" ]]; then echo bash > "$STUB_DIR/cmd"; fi
    # Enter on the exit dialog: "Exit and stop tasks" is what it confirms.
    if [[ "$*" == "send-keys -t %5 Enter" && -f "$STUB_DIR/dialog" && ! -f "$STUB_DIR/slow" ]]; then
      echo bash > "$STUB_DIR/cmd"; fi ;;
  capture-pane)
    if [[ -s "$STUB_DIR/dialog" ]]; then cat "$STUB_DIR/dialog"
    elif [[ -f "$STUB_DIR/dialog" ]]; then
      printf '%s\n' "   Background work is running" "   The following will stop when you exit:" \
        "   shell · curl -s https://example.org/slow …" "   ❯ 1. Exit and stop tasks" "     2. Stay" \
        "   Enter to confirm · Esc to cancel"
    else echo '$ '; fi ;;
esac
exit 0
'''

STUB_PANES = r'''#!/usr/bin/env python3
import os, sys
if sys.argv[1:2] == ["--state"]:
    d = os.environ["STUB_DIR"]
    seen, later = os.path.join(d, "stated"), os.path.join(d, "row2")
    if os.path.exists(seen) and os.path.exists(later):
        print(open(later).read().strip("\n"))      # what a second read sees
    else:
        open(seen, "w").close()
        print(os.environ["STUB_ROW"])
elif sys.argv[1:2] == ["get"]:
    if os.path.exists(os.path.join(os.environ["STUB_DIR"], "get-fails")):
        sys.exit(1)                                   # a crash: no output at all
    row = os.environ["STUB_ROW"].split("\t")
    known = {"name": "Wanda", "session": "w-sid", "owner": "-",
             "status": row[1] if len(row) > 1 else "-"}
    print("\t".join(known.get(f, "-") for f in sys.argv[3:]))
'''


class RequireIdle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copy(HERE / "boss-lifecycle.sh", self.tmp / "boss-lifecycle.sh")
        (self.tmp / "boss-panes.py").write_text(STUB_PANES)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "tmux").write_text(STUB_TMUX)
        os.chmod(bindir / "tmux", 0o755)
        (self.tmp / "cmd").write_text("claude\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_retire(self, row, *extra, exits=True, dialog=False, require_idle=True):
        if exits:
            (self.tmp / "exits").touch()
        if dialog:
            (self.tmp / "dialog").write_text("" if dialog is True else dialog)
        env = dict(os.environ, PATH="%s:%s" % (self.tmp / "bin", os.environ["PATH"]), TMUX="stub",
                   TMUX_PANE="%1", STUB_DIR=str(self.tmp), STUB_ROW=row, BOSS_EXIT_WAIT="2")
        r = subprocess.run(["bash", str(self.tmp / "boss-lifecycle.sh"), "retire", "%5"]
                           + (["--require-idle"] if require_idle else []) + list(extra),
                           env=env, capture_output=True, text=True, timeout=60)
        calls = (self.tmp / "calls").read_text() if (self.tmp / "calls").exists() else ""
        keys = [l for l in calls.splitlines() if l.startswith("send-keys")]
        return r, keys

    def test_an_unreadable_owner_refuses_instead_of_reading_as_unowned(self):
        # An empty owner means "unowned", which the cross-boss guard lets through.
        (self.tmp / "get-fails").touch()
        r, keys = self.run_retire("w-sid\tidle\tpin1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read the owner of %5", r.stderr)
        self.assertEqual(keys, [])

    def test_idle_exits_with_no_escape(self):
        r, keys = self.run_retire("w-sid\tidle\tpin1", "--expect-session", "w-sid", "--expect-last", "pin1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter"])

    def test_refusals_send_no_keys(self):
        for row, extra, words in (
                ("w-sid\tbusy\tpin1", (), "not idle"),
                ("w-sid\twaiting\tpin1", (), "not idle"),
                ("-\t-\t-", (), "not idle"),
                ("other\tidle\tpin1", ("--expect-session", "w-sid"), "not w-sid"),
                ("w-sid\tidle\tpin2", ("--expect-last", "pin1"), "new input"),
                ("w-sid\tidle\t-", ("--expect-last", "-"), "no pin to compare")):
            (self.tmp / "calls").unlink(missing_ok=True)
            r, keys = self.run_retire(row, *extra)
            self.assertEqual(r.returncode, 1, row)
            self.assertIn(words, r.stderr, row)
            self.assertEqual(keys, [], row)

    def test_leftover_background_work_on_an_idle_worker_is_stopped(self):
        """Idle, same input as before /exit: the dialog is about an orphaned
        background task (a curl, a watcher), not a turn. Confirm 'Exit and stop tasks'."""
        r, keys = self.run_retire("w-sid\tidle\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Enter"])
        self.assertIn("curl -s https://example.org/slow", r.stdout + r.stderr)

    def test_the_exit_records_do_not_count_as_a_turn(self):
        """/exit writes its own user records before the dialog: the plain pin
        moves, the past-exit pin (4th field) does not."""
        (self.tmp / "row2").write_text("w-sid\tidle\tpin-exit\tpin1\n")
        r, keys = self.run_retire("w-sid\tidle\tpin1\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys[-1], "send-keys -t %5 Enter")

    def test_a_confirmed_exit_that_is_slow_gets_no_escape(self):
        (self.tmp / "slow").touch()
        r, keys = self.run_retire("w-sid\tidle\tpin1\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("still shutting down", r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Enter"])

    def test_an_unfamiliar_dialog_is_not_confirmed(self):
        r, keys = self.run_retire("w-sid\tidle\tpin1", exits=False,
                                  dialog="   Background work is running\n   ❯ 1. Stay\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Escape"])

    def test_the_default_retire_also_stops_leftover_background_work(self):
        r, keys = self.run_retire("w-sid\tidle\tpin1", exits=False, dialog=True, require_idle=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys[-1], "send-keys -t %5 Enter")
        self.assertEqual(keys.count("send-keys -t %5 /exit Enter"), 1)

    def test_a_turn_in_the_gap_gets_one_escape_for_the_dialog(self):
        (self.tmp / "row2").write_text("w-sid\tbusy\tpin2\n")
        r, keys = self.run_retire("w-sid\tidle\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("a turn started", r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Escape"])

    def test_no_dialog_no_escape(self):
        r, keys = self.run_retire("w-sid\tidle\tpin1", exits=False)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter"])

    def test_expect_flags_need_require_idle(self):
        env = dict(os.environ, PATH="%s:%s" % (self.tmp / "bin", os.environ["PATH"]), TMUX="stub",
                   TMUX_PANE="%1", STUB_DIR=str(self.tmp), STUB_ROW="x")
        r = subprocess.run(["bash", str(self.tmp / "boss-lifecycle.sh"), "retire", "%5", "--expect-last", "p"],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("only apply with --require-idle", r.stderr)


# ------------------------------------------- list and fields, through fleet.py

# Answers list-panes from $STUB_DIR/panes (in fleet.FORMAT's field order),
# display-message with the target itself, and logs everything else.
STUB_TMUX_FLEET = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_DIR/calls"
case "$1" in
  list-panes) cat "$STUB_DIR/panes" ;;
  display-message) echo "$4" ;;
esac
exit 0
'''


class ListAndFields(unittest.TestCase):
    """boss-lifecycle.sh and boss-panes.py with real fleet.py, a stub tmux and
    live peer files: the sessions are `sleep` children with a matching procStart."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "sessions").mkdir()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "tmux").write_text(STUB_TMUX_FLEET)
        os.chmod(bindir / "tmux", 0o755)
        self.kids = []
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]), TMUX="stub",
                        TMUX_PANE="%1", STUB_DIR=str(self.tmp), CLAUDE_CONFIG_DIR=str(self.tmp))
        (self.tmp / "panes").write_text(
            "%1\tboss:0.0\t%1\tclaude\t/w/boss\t-\n"
            "%5\tboss:0.1\t%1\tclaude\t/w/api\tWanda\n"
            "%6\tmail:1.0\t-\tbash\t/w/mail\tGone\n")

    def tearDown(self):
        for k in self.kids:
            k.kill()
            k.wait()
        shutil.rmtree(self.tmp)

    def session(self, sid, pane, name, started, status="idle"):
        kid = subprocess.Popen(["sleep", "60"])
        self.kids.append(kid)
        stat = Path("/proc/%d/stat" % kid.pid).read_text()
        (self.tmp / "sessions" / ("%d.json" % kid.pid)).write_text(json.dumps(
            {"pid": kid.pid, "sessionId": sid, "name": name, "status": status,
             "startedAt": started, "tmux": "boss:@1.%s" % pane, "entrypoint": "sdk-cli",
             "cwd": str(self.tmp), "procStart": stat[stat.rindex(")") + 2:].split()[19]}))

    def call(self, *args, script="boss-lifecycle.sh"):
        cmd = ["bash", str(HERE / script)] if script.endswith(".sh") else [sys.executable, str(HERE / script)]
        return subprocess.run(cmd + list(args), env=self.env, capture_output=True, text=True, timeout=60)

    def test_fields_are_asked_for_by_name(self):
        self.session("s-wanda", "%5", "Wanda", 1000, status="busy")
        r = self.call("get", "%5", "status", "name", "owner", "session", script="boss-panes.py")
        self.assertEqual(r.stdout, "busy\tWanda\t%1\ts-wanda\n")
        r = self.call("get", "%6", "name", "owner", script="boss-panes.py")
        self.assertEqual(r.stdout, "-\t-\n")

    def test_an_unknown_field_is_an_error_not_a_dash(self):
        r = self.call("get", "%5", "nmae", script="boss-panes.py")
        self.assertEqual(r.returncode, 2)
        self.assertIn("nmae", r.stderr)

    def test_list_reads_names_from_sessions_and_explains_a_shared_pane(self):
        self.session("s-lucas", "%1", "Lucas", 500)
        self.session("s-wanda", "%5", "Wanda", 1000)
        self.session("s-casimir", "%5", "Casimir", 2000, status="busy")
        r = self.call("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        rows = {ln.split("\t")[0]: ln.split("\t") for ln in lines if ln.startswith("%")}
        self.assertEqual(rows["%5"][1:4], ["boss:0.1", "Wanda", "idle"])
        self.assertIn("shared-pane", rows["%5"][5])
        self.assertEqual(rows["%5"][6], "mine")
        # a pane with no live session keeps its mirrored name and shows its command
        self.assertEqual(rows["%6"][2:4], ["Gone", "bash"])
        self.assertEqual(rows["%1"][6], "self")
        why = lines[lines.index("\t".join(rows["%5"])) + 1]
        self.assertTrue(why.startswith("  shared-pane: 2 live sessions name pane %5"), why)
        self.assertIn("Casimir (s-casimir", why)

    def test_list_mine_keeps_only_the_boss_and_its_panes(self):
        r = self.call("list", "--mine")
        self.assertEqual([ln.split("\t")[0] for ln in r.stdout.splitlines()[1:]], ["%1", "%5"])

    def test_claim_stamps_through_the_fleet(self):
        self.session("s-x", "%6", "Xavi", 1000)
        self.call("claim", "%6")
        self.assertIn("set-option -p -t %6 @boss_pane %1", (self.tmp / "calls").read_text())


if __name__ == "__main__":
    unittest.main()
