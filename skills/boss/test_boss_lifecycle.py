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
import boss_store  # noqa: E402


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
            os.environ["CLAUDE_CONFIG_DIR"] = str(tmp)  # panes reads it at call time
            bp.TMUX = bp.fleet.MemoryTmux([bp.fleet.Pane("%7")])
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                sys.argv = ["boss-panes.py", "--set-name", "%7", "reviewer-1"]
                bp.main()
            name = json.loads((tmp / "sessions" / ("%d.json" % kid.pid)).read_text())["name"]
            return name, calls.read_text().split("\n")[0] if calls.exists() else None
        finally:
            os.environ["PATH"], sys.argv = old_path, old_argv
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
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
      '#{@worker_role}') cat "$STUB_DIR/role" 2>/dev/null ;;
      *) echo '' ;;
    esac ;;
  send-keys)
    if [[ "$*" == *"/exit"* && -f "$STUB_DIR/exits" ]]; then echo bash > "$STUB_DIR/cmd"; fi
    if [[ "$*" == *" --model "* ]]; then echo claude > "$STUB_DIR/cmd"; touch "$STUB_DIR/launched"; fi
    # Enter on the exit dialog: "Exit and stop tasks" is what it confirms.
    if [[ "$*" == "send-keys -t %5 Enter" && -f "$STUB_DIR/dialog" && ! -f "$STUB_DIR/slow" ]]; then
      echo bash > "$STUB_DIR/cmd"; fi ;;
  set-option)
    if [[ -f "$STUB_DIR/set-fails" ]]; then exit 1; fi ;;
  split-window) echo %5 ;;
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
    seq, count = os.path.join(d, "rows"), os.path.join(d, "reads")
    if os.path.exists(seq):                        # one row per read, the last one repeats
        rows = open(seq).read().splitlines()
        n = int(open(count).read()) if os.path.exists(count) else 0
        open(count, "w").write(str(n + 1))
        print(rows[min(n, len(rows) - 1)])
    elif os.path.exists(seen) and os.path.exists(later):
        print(open(later).read().strip("\n"))      # what a second read sees
    else:
        open(seen, "w").close()
        print(os.environ["STUB_ROW"])
elif sys.argv[1:2] == ["--set-name"]:
    with open(os.path.join(os.environ["STUB_DIR"], "calls"), "a") as fh:
        fh.write("set-name " + " ".join(sys.argv[2:]) + "\n")
elif sys.argv[1:2] == ["get"]:
    if os.path.exists(os.path.join(os.environ["STUB_DIR"], "get-fails")):
        sys.exit(1)                                   # a crash: no output at all
    row = os.environ["STUB_ROW"].split("\t")
    d = os.environ["STUB_DIR"]
    after = os.path.join(d, "name-after")
    name = (open(after).read().strip() if os.path.exists(os.path.join(d, "launched"))
            and os.path.exists(after) else "Wanda")
    known = {"name": name, "session": "w-sid", "owner": "-",
             "waiting_for": os.environ.get("STUB_WAITING", "-"),
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

    def run_retire(self, row, *extra, exits=True, dialog=False, require_idle=True, extra_env=None, cmd="retire"):
        if exits:
            (self.tmp / "exits").touch()
        if dialog:
            (self.tmp / "dialog").write_text("" if dialog is True else dialog)
        env = dict(os.environ, PATH="%s:%s" % (self.tmp / "bin", os.environ["PATH"]), TMUX="stub",
                   TMUX_PANE="%1", STUB_DIR=str(self.tmp), STUB_ROW=row, BOSS_EXIT_WAIT="2",
                   **(extra_env or {}))
        r = subprocess.run(["bash", str(self.tmp / "boss-lifecycle.sh"), cmd, "%5"]
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

    def test_the_exit_dialog_itself_reads_as_waiting_not_as_a_turn(self):
        """Measured on Claude Code 2.1.311: with the "Background work is running"
        dialog up the session's status is `waiting`, whatever the worker was doing
        before. Same session, same input past /exit: still no turn."""
        (self.tmp / "row2").write_text("w-sid\twaiting\tpin-exit\tpin1\n")
        r, keys = self.run_retire("w-sid\tidle\tpin1\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Enter"])

    def test_a_turn_that_asks_something_in_the_gap_is_still_a_turn(self):
        (self.tmp / "row2").write_text("w-sid\twaiting\tpin2\tpin2\n")
        r, keys = self.run_retire("w-sid\tidle\tpin1\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("a turn started", r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Escape"])

    def run_waiting(self, rows, *extra, extra_env=None, wait="2", **kw):
        (self.tmp / "rows").write_text("\n".join(rows) + "\n")
        return self.run_retire(rows[-1], "--wait-idle", wait, *extra,
                               extra_env={"BOSS_RETRY_EVERY": "1", **(extra_env or {})}, **kw)

    def test_a_busy_worker_is_retried_until_its_turn_ends_and_nothing_is_typed_before(self):
        r, keys = self.run_waiting(["w-sid\tbusy\tp1\tp1"] * 2 + ["w-sid\tidle\tp2\tp2"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter"])
        self.assertIn("retrying every", r.stderr)

    def test_a_worker_that_stays_busy_is_refused_when_the_wait_runs_out(self):
        r, keys = self.run_waiting(["w-sid\tbusy\tp1\tp1"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("still busy after 2 s", r.stderr)
        self.assertEqual(keys, [])

    def test_the_wait_does_not_forgive_a_changed_session_or_input(self):
        r, keys = self.run_waiting(["other\tbusy\tp1\tp1", "other\tidle\tp1\tp1"], "--expect-session", "w-sid")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not w-sid", r.stderr)
        self.assertEqual(keys, [])

    def test_shell_is_not_idle_because_it_is_read_mid_turn_too(self):
        """Measured on Claude Code 2.1.311: `shell` (a background shell running)
        is read while a turn is still in flight, so it must not pass as idle."""
        r, keys = self.run_retire("w-sid\tshell\tpin1\tpin1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not idle", r.stderr)
        self.assertEqual(keys, [])

    def test_shell_and_waiting_are_retried_and_the_wait_can_end_in_a_refusal(self):
        r, keys = self.run_waiting(["w-sid\tshell\tp1\tp1", "w-sid\twaiting\tp1\tp1"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("still waiting after 2 s", r.stderr)
        self.assertEqual(keys, [])
        (self.tmp / "reads").unlink()
        r, keys = self.run_waiting(["w-sid\tshell\tp1\tp1"] * 2 + ["w-sid\tidle\tp1\tp1"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter"])

    def test_a_dialog_read_as_shell_after_exit_is_still_no_turn(self):
        (self.tmp / "row2").write_text("w-sid\tshell\tpin-exit\tpin1\n")
        r, keys = self.run_retire("w-sid\tidle\tpin1\tpin1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Enter"])

    def test_restart_waits_too_and_types_nothing_at_a_worker_that_stays_busy(self):
        (self.tmp / "rows").write_text("w-sid\tbusy\tp1\tp1\n")
        r, keys = self.run_retire("w-sid\tbusy\tp1\tp1", "--wait-idle", "1", cmd="restart",
                                  extra_env={"BOSS_RETRY_EVERY": "0.1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("still busy after 1 s", r.stderr)
        self.assertEqual(keys, [])

    def test_a_wait_written_with_a_leading_zero_is_read_as_decimal(self):
        # "08" is not octal: the loop used to be skipped and the restart died
        # "still busy" without waiting.
        r, keys = self.run_waiting(["w-sid\tbusy\tp1\tp1", "w-sid\tidle\tp2\tp2"], wait="08")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("value too great", r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter"])
        (self.tmp / "calls").unlink()
        (self.tmp / "cmd").write_text("claude\n")
        (self.tmp / "reads").unlink()
        r, keys = self.run_waiting(["w-sid\tbusy\tp1\tp1"], wait="09")
        self.assertEqual(r.returncode, 1)
        self.assertIn("still busy after 9 s", r.stderr)
        self.assertNotIn("value too great", r.stderr)

    def test_a_retry_interval_that_is_not_a_number_stops_with_an_error_line(self):
        for bad in ("abc", "1x", "-2", "1.2.3"):
            (self.tmp / "calls").unlink(missing_ok=True)
            r, keys = self.run_retire("w-sid\tbusy\tp1\tp1", "--wait-idle", "5", extra_env={"BOSS_RETRY_EVERY": bad})
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("ERROR: BOSS_RETRY_EVERY", r.stderr, bad)
            self.assertEqual(keys, [], bad)

    def test_a_retry_interval_below_one_second_is_raised_to_one(self):
        # 0 used to busy-loop a python status read for the whole wait.
        for tiny in ("0", "0.01"):
            (self.tmp / "reads").unlink(missing_ok=True)
            (self.tmp / "calls").unlink(missing_ok=True)
            r, keys = self.run_waiting(["w-sid\tbusy\tp1\tp1"], extra_env={"BOSS_RETRY_EVERY": tiny})
            self.assertEqual(r.returncode, 1, tiny)
            self.assertIn("retrying every 1 s", r.stderr, tiny)
            self.assertLessEqual(int((self.tmp / "reads").read_text()), 4, tiny)    # 1 + 2 s / 1 s

    def test_a_wait_that_is_not_a_whole_number_is_refused_before_anything_is_typed(self):
        for bad in ("abc", "1.5", "-1", "5s"):
            (self.tmp / "calls").unlink(missing_ok=True)
            r, keys = self.run_retire("w-sid\tidle\tp1\tp1", "--wait-idle", bad)
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("--wait-idle takes a number of seconds", r.stderr, bad)
            self.assertEqual(keys, [], bad)

    def test_wait_idle_takes_force_as_its_value_and_so_is_refused(self):
        # `--wait-idle --force` must not read as a wait of --force with the
        # force switch on: the number check refuses it and nothing is typed.
        r, keys = self.run_retire("w-sid\tbusy\tp1\tp1", "--wait-idle", "--force")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--wait-idle takes a number of seconds", r.stderr)
        self.assertEqual(keys, [])
        r, keys = self.run_retire("w-sid\tbusy\tp1\tp1", "--force", "--wait-idle", "1",
                                  extra_env={"BOSS_RETRY_EVERY": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("still busy after 1 s", r.stderr)          # --force does not relax --require-idle
        self.assertEqual(keys, [])

    def test_a_pin_cannot_hold_across_a_wait_and_the_refusal_says_so(self):
        r, keys = self.run_waiting(["w-sid\tbusy\tp1\tp1", "w-sid\tidle\tp2\tp2"], "--expect-last", "p1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("during the wait", r.stderr)
        self.assertEqual(keys, [])

    def test_shell_with_the_turn_over_is_restartable_and_the_stop_is_said_first(self):
        """The turn ended (the transcript's last record is turn_duration) and a
        background shell is left: the status reads `shell` for as long as it runs.
        /exit opens the background-work dialog; its list is printed, then confirmed."""
        r, keys = self.run_retire("w-sid\tshell\tp1\tp1\t1", exits=False, dialog=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Enter"])
        self.assertIn("turn is over", r.stderr)
        self.assertIn("will be stopped", r.stderr)
        self.assertIn("curl -s https://example.org/slow", r.stderr)

    def test_shell_with_a_turn_in_flight_or_unknown_stays_refused(self):
        for row in ("w-sid\tshell\tp1\tp1\t0", "w-sid\tshell\tp1\tp1\t-", "w-sid\tshell\tp1\tp1"):
            (self.tmp / "calls").unlink(missing_ok=True)
            r, keys = self.run_retire(row, exits=False, dialog=True)
            self.assertEqual(r.returncode, 1, row)
            self.assertIn("not idle", r.stderr, row)
            self.assertEqual(keys, [], row)

    def test_the_wait_ends_when_a_shell_is_left_after_the_turn(self):
        r, keys = self.run_waiting(["w-sid\tshell\tp1\tp1\t0", "w-sid\tshell\tp1\tp1\t1"], exits=False, dialog=True,
                                   extra_env={"BOSS_RETRY_EVERY": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(keys, ["send-keys -t %5 /exit Enter", "send-keys -t %5 Enter"])

    def test_wait_idle_needs_require_idle(self):
        r, keys = self.run_retire("x", "--wait-idle", "5", require_idle=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("only apply with --require-idle", r.stderr)

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
  list-panes) [[ -f "$STUB_DIR/tmux-fails" ]] && exit 1; cat "$STUB_DIR/panes" ;;
  set-option) [[ -f "$STUB_DIR/tmux-fails" ]] && exit 1 ;;
  display-message) echo "$4" ;;
esac
exit 0
'''


STUB_AGENT_NAME = r'''#!/usr/bin/env bash
echo "agent-name $*" >> "$STUB_DIR/calls"
echo "${@: -1}"
'''


class RestartKeepsName(unittest.TestCase):
    """A restarted worker starts under its name (cc-agent-names#5).

    Setting the name after the new session started was too late: the hook had
    already told the session another name, and it signed its messages so. The
    name is now set for a session id chosen first, and claude starts under it.
    """

    setUp, tearDown = RequireIdle.setUp, RequireIdle.tearDown

    def run_restart(self, with_agent_name=True):
        (self.tmp / "exits").touch()
        if with_agent_name:
            (self.tmp / "bin" / "agent-name").write_text(STUB_AGENT_NAME)
            os.chmod(self.tmp / "bin" / "agent-name", 0o755)
            path = "%s:%s" % (self.tmp / "bin", os.environ["PATH"])
        else:
            path = "%s:/usr/bin:/bin" % (self.tmp / "bin")
        env = dict(os.environ, PATH=path, TMUX="stub", TMUX_PANE="%1", STUB_DIR=str(self.tmp),
                   STUB_ROW="w-sid\tidle\tpin1", BOSS_EXIT_WAIT="2")
        r = subprocess.run(["bash", str(self.tmp / "boss-lifecycle.sh"), "restart", "%5"],
                           env=env, capture_output=True, text=True, timeout=60)
        return r, (self.tmp / "calls").read_text().splitlines()

    def test_the_name_is_set_for_the_new_session_before_it_starts(self):
        r, calls = self.run_restart()
        self.assertEqual(r.returncode, 0, r.stderr)
        sets = [i for i, c in enumerate(calls) if c.startswith("agent-name set ")]
        self.assertEqual(len(sets), 1, calls)
        sid, name = calls[sets[0]].split()[2:]
        self.assertEqual(name, "Wanda")
        launch = [i for i, c in enumerate(calls) if c.startswith("send-keys") and " --model " in c]
        self.assertEqual(len(launch), 1, calls)
        self.assertIn("--session-id '%s'" % sid, calls[launch[0]])
        self.assertLess(sets[0], launch[0])
        self.assertFalse([c for c in calls if c.startswith("set-name")], calls)

    def test_a_worker_starts_without_ask_user_question(self):
        # Only the boss asks the owner; a worker's question rings the chime for
        # a pane nobody watches and stalls the ticket (Thierry, 2026-10-30).
        r, calls = self.run_restart()
        self.assertEqual(r.returncode, 0, r.stderr)
        launch = [c for c in calls if c.startswith("send-keys") and " --model " in c]
        self.assertEqual(len(launch), 1, calls)
        self.assertIn("--disallowedTools AskUserQuestion", launch[0])

    def launches(self):
        return [c for c in (self.tmp / "calls").read_text().splitlines()
                if c.startswith("send-keys") and " --model " in c]

    def test_a_concierge_keeps_ask_user_question_and_runs_on_sonnet(self):
        # It holds the owner's questions; everyone else sends theirs to it.
        (self.tmp / "cmd").write_text("bash\n")
        env = dict(os.environ, PATH="%s:%s" % (self.tmp / "bin", os.environ["PATH"]), TMUX="stub",
                   TMUX_PANE="%1", STUB_DIR=str(self.tmp), STUB_ROW="w-sid\tidle\tpin1")
        r = subprocess.run(["bash", str(self.tmp / "boss-lifecycle.sh"), "spawn", str(self.tmp), "--concierge"],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        launch = self.launches()
        self.assertEqual(len(launch), 1)
        self.assertNotIn("--disallowedTools", launch[0])
        self.assertIn("--model 'sonnet'", launch[0])
        self.assertIn("set-option -p -t %5 @worker_role concierge",
                      (self.tmp / "calls").read_text())

    def test_a_restarted_concierge_is_still_a_concierge(self):
        (self.tmp / "role").write_text("concierge\n")
        r, _ = self.run_restart()
        self.assertEqual(r.returncode, 0, r.stderr)
        launch = self.launches()
        self.assertNotIn("--disallowedTools", launch[0])
        self.assertIn("--model 'sonnet'", launch[0])

    def run_lifecycle(self, *args, row="w-sid\twaiting\tpin1"):
        (self.tmp / "exits").touch()
        env = dict(os.environ, PATH="%s:%s" % (self.tmp / "bin", os.environ["PATH"]), TMUX="stub",
                   TMUX_PANE="%1", STUB_DIR=str(self.tmp), STUB_ROW=row, BOSS_EXIT_WAIT="2")
        return subprocess.run(["bash", str(self.tmp / "boss-lifecycle.sh")] + list(args),
                              env=env, capture_output=True, text=True, timeout=60)

    def test_a_concierge_holding_a_question_cannot_be_stopped(self):
        # Escape, Escape, /exit would erase the question and those queued behind it.
        (self.tmp / "role").write_text("concierge\n")
        for args in (["retire", "%5"], ["restart", "%5"], ["move", "%5", str(self.tmp)]):
            r = self.run_lifecycle(*args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("question", r.stderr)
        self.assertFalse(self.launches() if (self.tmp / "calls").exists() else [])

    def test_a_concierge_stuck_on_a_prompt_can_be_stopped(self):
        # No question is on screen, so "wait for the answer" would wait for ever.
        (self.tmp / "role").write_text("concierge\n")
        os.environ["STUB_WAITING"] = "permission prompt"
        self.addCleanup(os.environ.pop, "STUB_WAITING", None)
        self.assertEqual(self.run_lifecycle("retire", "%5").returncode, 0)

    def test_a_worker_waiting_on_a_prompt_can_still_be_retired(self):
        self.assertEqual(self.run_lifecycle("retire", "%5").returncode, 0)

    def test_a_concierge_gets_its_brief_from_a_file_so_a_restart_keeps_it(self):
        (self.tmp / "role").write_text("concierge\n")
        r, _ = self.run_restart()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--append-system-prompt-file", self.launches()[0])
        self.assertIn("concierge-brief.md", self.launches()[0])

    def test_a_retired_pane_is_no_concierge_any_more(self):
        (self.tmp / "role").write_text("concierge\n")
        r = self.run_lifecycle("retire", "%5", row="w-sid\tidle\tpin1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("set-option -pu -t %5 @worker_role", (self.tmp / "calls").read_text())

    def test_the_concierge_flag_means_spawn_only(self):
        r = self.run_lifecycle("restart", "%5", "--concierge", row="w-sid\tidle\tpin1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.launches() if (self.tmp / "calls").exists() else [])

    def test_a_name_held_elsewhere_is_reported_not_claimed(self):
        # Another live session holds Wanda, so the hook names the new one Greta.
        (self.tmp / "name-after").write_text("Greta\n")
        r, calls = self.run_restart()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("as Greta", r.stdout)
        self.assertIn("not Wanda", r.stderr)
        self.assertIn("set-option -p -t %5 @worker_name Greta", calls)

    def test_a_mirror_that_fails_fails_the_restart(self):
        # The watchdog only sees panes carrying @worker_name (Codex on #35).
        (self.tmp / "set-fails").touch()
        r, calls = self.run_restart()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("restarted", r.stdout)

    def test_without_agent_names_the_name_is_set_after_the_start_as_before(self):
        r, calls = self.run_restart(with_agent_name=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        launch = [c for c in calls if c.startswith("send-keys") and " --model " in c]
        self.assertEqual(len(launch), 1, calls)
        self.assertNotIn("--session-id", launch[0])
        self.assertIn("set-name %5 Wanda", calls)


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
            "%1\tboss:0.0\t%1\tclaude\t/w/boss\t-\t-\n"
            "%5\tboss:0.1\t%1\tclaude\t/w/api\tWanda\t-\n"
            "%6\tmail:1.0\t-\tbash\t/w/mail\tGone\t-\n")

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

    def test_a_second_concierge_spawn_returns_the_one_that_lives(self):
        self.session("c-sid", "%7", "Odile", 1000)
        with (self.tmp / "panes").open("a") as fh:
            fh.write("%7\tboss:0.2\t%1\tclaude\t/w/pm\tOdile\tconcierge\n")
        r = self.call("spawn", str(self.tmp), "--concierge")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "%7\tOdile")
        self.assertNotIn("split-window", (self.tmp / "calls").read_text())

    def test_list_mine_keeps_only_the_boss_and_its_panes(self):
        r = self.call("list", "--mine")
        self.assertEqual([ln.split("\t")[0] for ln in r.stdout.splitlines()[1:]], ["%1", "%5"])

    def test_an_owner_tmux_cannot_list_refuses_instead_of_reading_as_unowned(self):
        self.session("s-wanda", "%5", "Wanda", 1000)
        (self.tmp / "tmux-fails").touch()
        r = self.call("retire", "%5")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read the owner of %5", r.stderr)
        self.assertNotIn("send-keys", (self.tmp / "calls").read_text())

    def test_list_says_so_when_tmux_does_not_answer(self):
        (self.tmp / "tmux-fails").touch()
        r = self.call("list")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tmux", r.stderr)

    def test_a_stamp_that_fails_fails_the_claim(self):
        self.session("s-x", "%6", "Xavi", 1000)
        (self.tmp / "panes").write_text("%6\tmail:1.0\t-\tclaude\t/w/mail\t-\t-\n")
        r = self.call("stamp", "%6", "%1", script="boss-panes.py")
        self.assertEqual(r.returncode, 0)
        (self.tmp / "tmux-fails").touch()
        r = self.call("stamp", "%6", "%1", script="boss-panes.py")
        self.assertEqual(r.returncode, 1)
        r = self.call("stamp", "%6", script="boss-panes.py")
        self.assertEqual((r.returncode, "Traceback" in r.stderr), (2, False))

    def test_a_worker_that_runs_the_script_is_not_stamped_a_boss_but_a_boss_is(self):
        # self_register used to stamp the calling pane on every invocation, so a
        # worker that ran the script became a boss pane.
        self.session("s-lucas", "%1", "Lucas", 500)
        stamp_self = "set-option -p -t %1 @boss_pane %1"
        r = self.call("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(stamp_self, (self.tmp / "calls").read_text())
        (self.tmp / "calls").unlink()
        boss_store.register("s-lucas", cfg=self.tmp)
        r = self.call("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(stamp_self, (self.tmp / "calls").read_text())

    def test_a_pane_with_no_session_is_not_stamped_either(self):
        stamp_self = "set-option -p -t %1 @boss_pane %1"
        r = self.call("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(stamp_self, (self.tmp / "calls").read_text())

    def test_claim_stamps_through_the_fleet(self):
        self.session("s-x", "%6", "Xavi", 1000)
        self.call("claim", "%6")
        self.assertIn("set-option -p -t %6 @boss_pane %1", (self.tmp / "calls").read_text())


if __name__ == "__main__":
    unittest.main()
