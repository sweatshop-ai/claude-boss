#!/usr/bin/env python3
"""routines/boss-workers-watch.sh against fake panes: DRY_RUN, a scratch state
dir and a throwaway CLAUDE_CONFIG_DIR, so nothing real is read or sent.

Run: python3 skills/boss/test_workers_watch.py
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "routines" / "boss-workers-watch.sh"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "watch"
LIFECYCLE = Path(__file__).resolve().parent / "boss-lifecycle.sh"

# A concierge's AskUserQuestion dialog: the options belong to the sender.
QUESTION = "Merge PR 46 now?\n❯ 1. Yes, merge\n  2. No, wait\n  3. Type something.\nEnter to select · ↑/↓ to navigate · Esc to cancel\n"
# A tool-permission dialog.
PERMISSION = "Bash command\n  git push\nDo you want to proceed?\n❯ 1. Yes\n  2. No\n"
# The trust prompt, as the current build renders it.
TRUST = "Quick safety check: Is this a project you trust?\n ❯ No, exit\n   Yes, I trust this folder\n Enter to confirm · Esc to cancel\n"
# A permission dialog whose header has scrolled out: options and footer remain.
PERMISSION_TAIL = "❯ 1. Yes\n  2. Yes, and always allow access\n  4. No\n Esc to cancel · Tab to amend\n"
# A full Bash dialog as the current build draws it, with the status lines below:
# the header sits 11 lines from the bottom.
PERMISSION_FULL = (
    " Bash command\n Tip: auto mode handles these prompts for you\n Create x.txt and confirm it exists\n"
    + "╌" * 20 + "\n touch /tmp/x.txt && ls -l /tmp/x.txt\n" + "╌" * 20 + "\n"
    " Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and always allow access to /tmp from this project\n"
    "   3. Yes, and switch to auto mode\n   4. No\n Esc to cancel · Tab to amend\n"
    "  Hilde │ Model: Haiku 5.5 | Ctx: 0\n  ⏸ manual mode on\n")
# The same dialog on a narrow pane: header and footer out of reach or wrapped.
PERMISSION_NARROW = "\n".join(["line"] * 6 + ["Do you want to", "proceed?"] + ["x"] * 12) + (
    "\n ❯ 1. Yes\n   2. Yes, and always\n   allow access to /tmp\n   4. No\n Esc to cancel · Tab to\n amend\n"
    "  Hilde │ Model\n  ⏸ manual mode on\n")
# A permission dialog whose option line has scrolled out of the capture.
PERMISSION_HEADER_ONLY = "Bash command\n  git push\nDo you want to proceed?\n"


class WatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-watch-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.caps = self.tmp / "caps"
        self.caps.mkdir()
        self.state = self.tmp / "state"
        self.env = dict(os.environ, DRY_RUN="1", CLAUDE_CONFIG_DIR=str(self.tmp / "cfg"),
                        WATCH_STATE_DIR=str(self.state), FAKE_CAP_DIR=str(self.caps),
                        FAKE_PANES=str(self.tmp / "panes"), BOSS_REAP=str(self.tmp / "none"))

    def run_watch(self, screen, role="-", runs=2):
        # Same TSV as the script's tmux format: id, index, command, path, role, name.
        shutil.rmtree(self.state, True)  # a subTest starts from no history
        (self.tmp / "panes").write_text("%%7\t1\tclaude\t/w/api\t%s\tWren\n" % role)
        (self.caps / "7.txt").write_text(screen)
        return [self.run_once() for _ in range(runs)]

    def run_once(self):
        r = subprocess.run(["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_a_workers_permission_prompt_alerts_on_the_second_run(self):
        first, second = self.run_watch(PERMISSION)
        self.assertNotIn("permission-prompt", first)
        self.assertIn("permission-prompt", second)

    def test_a_concierges_question_raises_no_alert(self):
        self.assertEqual("".join(self.run_watch(QUESTION, role="concierge", runs=3)), "")

    def test_a_concierges_question_has_no_false_recovery_when_answered(self):
        self.run_watch(QUESTION, role="concierge", runs=3)
        (self.caps / "7.txt").write_text("working\n")
        self.assertEqual(self.run_once(), "")

    def test_a_concierge_stuck_on_a_real_permission_prompt_still_alerts(self):
        _, second = self.run_watch(PERMISSION_HEADER_ONLY, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_concierge_stuck_on_the_trust_prompt_alerts(self):
        _, second = self.run_watch(TRUST, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_concierge_permission_dialog_with_its_header_scrolled_away_alerts(self):
        _, second = self.run_watch(PERMISSION_TAIL, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_concierge_question_worded_like_a_permission_header_raises_no_alert(self):
        # The question is on screen and old output above it quotes a dialog.
        screen = "Do you want to proceed with the release?\nTab to amend\n" + "old output\n" * 15 + QUESTION
        self.assertEqual("".join(self.run_watch(screen, role="concierge", runs=3)), "")

    def test_a_concierge_stuck_on_a_full_permission_dialog_alerts(self):
        _, second = self.run_watch(PERMISSION_FULL, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_concierge_stuck_on_a_narrow_pane_dialog_alerts(self):
        # Header more than 15 lines up and the footer wrapped: only the option line is left.
        _, second = self.run_watch(PERMISSION_NARROW, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_workers_question_style_dialog_still_alerts(self):
        # Only a concierge's own question is exempt; a worker has no AskUserQuestion.
        _, second = self.run_watch(QUESTION)
        self.assertIn("permission-prompt", second)

    # Renders captured from a real build (Claude Code 2.1.311) on a 40-row pane at
    # 74, 31 and 25 columns, with the prompt and paths invented. `ask` is an
    # AskUserQuestion worded like a permission dialog, with a "Yes, and always" option.
    def fixture(self, kind, width):
        return (FIXTURES / ("%s-%d.txt" % (kind, width))).read_text()

    def test_a_concierge_stuck_on_a_real_permission_dialog_alerts_at_every_width(self):
        for kind in ("bash", "edit"):
            for width in (74, 31, 25):
                with self.subTest(kind=kind, width=width):
                    _, second = self.run_watch(self.fixture(kind, width), role="concierge")
                    self.assertIn("permission-prompt", second)

    def test_a_concierge_stuck_on_a_real_permission_dialog_with_a_status_line_alerts(self):
        status = "  Hilde \u2502 Model: Haiku 5.5 | Ctx: 0\n  \u23f8 manual mode on\n"
        for kind in ("bash", "edit"):
            for width in (74, 31, 25):
                with self.subTest(kind=kind, width=width):
                    _, second = self.run_watch(self.fixture(kind, width) + status, role="concierge")
                    self.assertIn("permission-prompt", second)

    def test_a_real_question_worded_like_a_dialog_raises_no_alert_at_any_width(self):
        for width in (74, 31, 25):
            with self.subTest(width=width):
                self.assertEqual("".join(self.run_watch(self.fixture("ask", width), role="concierge", runs=3)), "")

    def test_a_real_question_without_option_descriptions_raises_no_alert(self):
        # Captured as the others are, with the descriptions omitted: the "Yes, and
        # always" option then sits 6 non-blank rows from the bottom and the header 7.
        self.assertEqual("".join(self.run_watch(self.fixture("askplain", 74), role="concierge", runs=3)), "")

    def test_a_permission_dialog_below_an_answered_question_still_alerts(self):
        # The question's footer is in the scrollback, not at the bottom.
        _, second = self.run_watch(self.fixture("askplain", 74) + PERMISSION_FULL, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_permission_dialog_whose_option_quotes_the_question_footer_still_alerts(self):
        screen = PERMISSION_FULL.replace("Esc to cancel", "Enter to select the file\n Esc to cancel")
        _, second = self.run_watch(screen, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_real_questions_footer_carries_no_tab_to_amend(self):
        for width in (74, 31, 25):
            with self.subTest(width=width):
                text = " ".join(self.fixture("ask", width).split())
                self.assertIn("Enter to select \u00b7 \u2191/\u2193 to navigate \u00b7 Esc to cancel", text)
                self.assertNotIn("Tab to amend", text)

    def test_a_real_permission_dialog_after_blank_rows_alerts(self):
        # A fresh pane leaves blank rows under the dialog; they are not part of the window.
        _, second = self.run_watch(self.fixture("edit", 25) + "\n" * 20, role="concierge")
        self.assertIn("permission-prompt", second)


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class ConciergeMarkCase(unittest.TestCase):
    """The pane mark itself: boss-lifecycle.sh sets @worker_role, the watchdog's own
    list-panes format reads it. Both run against a tmux server on a private
    socket, so no pane of this machine is touched; `claude` is a stub that draws
    a concierge's question."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="boss-mark-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "proj").mkdir()
        (self.tmp / "screen.txt").write_text(QUESTION)
        stub = self.tmp / "claude"
        stub.write_text('#!/bin/bash\ncat "%s"\nexec -a claude sleep 120\n' % (self.tmp / "screen.txt"))
        stub.chmod(0o755)
        # TMUX_TMPDIR keeps even a bare `tmux` off the real server's socket.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("TMUX")}
        self.env.update(TMUX_TMPDIR=str(self.tmp), CLAUDE_CONFIG_DIR=str(self.tmp / "cfg"),
                        BOSS_CLAUDE_CMD=str(stub), WATCH_STATE_DIR=str(self.tmp / "state"), DRY_RUN="1")
        self.addCleanup(subprocess.run, ["tmux", "kill-server"], env=self.env, capture_output=True)
        self.boss_pane = self.tmux("new-session", "-d", "-x", "100", "-y", "30", "-P", "-F", "#{pane_id}")
        self.tmux("set-option", "-g", "default-command", "bash --norc --noprofile")
        self.env["TMUX"] = self.tmux("display-message", "-p", "#{socket_path},#{pid},0")
        self.env["TMUX_PANE"] = self.boss_pane

    def bare_env(self):
        # A client of the private server by TMUX_TMPDIR alone, as the watchdog's timer runs.
        return {k: v for k, v in self.env.items() if k not in ("TMUX", "TMUX_PANE")}

    def tmux(self, *args):
        r = subprocess.run(["tmux", "-f", "/dev/null", *args], env=self.bare_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def watch(self):
        r = subprocess.run(["bash", str(SCRIPT)], env=self.bare_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_a_pane_marked_by_the_lifecycle_script_is_read_as_a_concierge_by_the_watchdog(self):
        r = subprocess.run(["bash", str(LIFECYCLE), "spawn", str(self.tmp / "proj"), "--concierge"],
                           env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr)
        pane = r.stdout.split()[0]
        self.assertIn("Merge PR 46 now?", self.tmux("capture-pane", "-p", "-t", pane))
        self.assertEqual("".join(self.watch() for _ in range(3)), "")
        # The same pane without the mark alerts, so the silence above came from the mark.
        self.tmux("set-option", "-pu", "-t", pane, "@worker_role")
        shutil.rmtree(self.tmp / "state", True)
        self.assertIn("permission-prompt", "".join(self.watch() for _ in range(2)))


if __name__ == "__main__":
    unittest.main()
