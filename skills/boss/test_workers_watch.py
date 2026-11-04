"""routines/boss-workers-watch.sh against fake panes: DRY_RUN, a scratch state
dir and a throwaway CLAUDE_CONFIG_DIR, so nothing real is read or sent."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "routines" / "boss-workers-watch.sh"

# A concierge's AskUserQuestion dialog: the options belong to the sender.
QUESTION = "Merge PR 46 now?\n❯ 1. Yes, merge\n  2. No, wait\n  3. Type something.\nEnter to select · Esc to cancel\n"
# A tool-permission dialog.
PERMISSION = "Bash command\n  git push\nDo you want to proceed?\n❯ 1. Yes\n  2. No\n"
# A permission dialog whose option line has scrolled out of the capture.
PERMISSION_HEADER_ONLY = "Bash command\n  git push\nDo you want to proceed?\n"


class Watch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.caps = self.tmp / "caps"
        self.caps.mkdir()
        self.state = self.tmp / "state"
        self.env = dict(os.environ, DRY_RUN="1", CLAUDE_CONFIG_DIR=str(self.tmp / "cfg"),
                        WATCH_STATE_DIR=str(self.state), FAKE_CAP_DIR=str(self.caps),
                        FAKE_PANES=str(self.tmp / "panes"), BOSS_REAP=str(self.tmp / "none"))

    def run_watch(self, screen, role="-", runs=2):
        # Same TSV as the script's tmux format: id, index, command, path, name, role.
        (self.tmp / "panes").write_text("%%7\t1\tclaude\t/w/api\t%s\tWren\n" % role)
        (self.caps / "7.txt").write_text(screen)
        out = []
        for _ in range(runs):
            r = subprocess.run(["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out.append(r.stdout)
        return out

    def test_a_workers_permission_prompt_alerts_on_the_second_run(self):
        first, second = self.run_watch(PERMISSION)
        self.assertNotIn("permission-prompt", first)
        self.assertIn("permission-prompt", second)

    def test_a_concierges_question_raises_no_alert(self):
        self.assertEqual("".join(self.run_watch(QUESTION, role="concierge", runs=3)), "")

    def test_a_concierges_question_has_no_false_recovery_when_answered(self):
        self.run_watch(QUESTION, role="concierge", runs=3)
        (self.caps / "7.txt").write_text("working\n")
        r = subprocess.run(["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.stdout, "")

    def test_a_concierge_stuck_on_a_real_permission_prompt_still_alerts(self):
        _, second = self.run_watch(PERMISSION_HEADER_ONLY, role="concierge")
        self.assertIn("permission-prompt", second)

    def test_a_workers_question_style_dialog_still_alerts(self):
        # Only a concierge's own question is exempt; a worker has no AskUserQuestion.
        _, second = self.run_watch(QUESTION)
        self.assertIn("permission-prompt", second)


if __name__ == "__main__":
    unittest.main()
