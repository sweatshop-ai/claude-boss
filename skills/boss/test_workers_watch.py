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

# A concierge's AskUserQuestion dialog: the options belong to the sender.
QUESTION = "Merge PR 46 now?\n❯ 1. Yes, merge\n  2. No, wait\n  3. Type something.\nEnter to select · Esc to cancel\n"
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
        screen = "Do you want to proceed with the release?\nTab to amend\n" + "\n" * 15 + QUESTION
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


if __name__ == "__main__":
    unittest.main()
