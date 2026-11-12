"""R25: the Sandbox fails a test that installed a stub and never looked at its call log."""
import subprocess
import unittest
from unittest import mock

import hermetic
from hermetic import Sandbox, short_id


class Fresh(unittest.TestCase):
    def fresh(self):
        """A Sandbox that is not registered for cleanup, so a test can see what cleanup raises."""
        sb = Sandbox()
        self.addCleanup(sb.reap)
        return sb


class UnreadStub(Fresh):
    def test_a_stub_nobody_read_fails_the_cleanup(self):
        sb = self.fresh()
        sb.stub("codex")
        with self.assertRaises(AssertionError) as caught:
            sb.cleanup()
        self.assertIn("codex", str(caught.exception))
        self.assertFalse(sb.root.exists())          # the directory is gone even when it raises

    def test_reading_the_call_log_satisfies_the_check(self):
        sb = self.fresh()
        sb.stub("codex")
        self.assertEqual(sb.calls_of("codex"), [])
        sb.cleanup()

    def test_expect_unused_passes_for_a_stub_that_was_never_called_and_counts_as_read(self):
        sb = self.fresh()
        sb.stub("gh")
        sb.expect_unused("gh")
        sb.cleanup()

    def test_expect_unused_fails_when_the_stub_was_called(self):
        sb = self.fresh()
        sb.stub("gh")
        subprocess.run([str(sb.stubs / "gh"), "pr", "view"], env=sb.env, stdin=subprocess.DEVNULL, check=True)
        with self.assertRaises(AssertionError):
            sb.expect_unused("gh")
        sb.calls_of("gh")
        sb.cleanup()

    def test_each_stub_is_checked_on_its_own(self):
        sb = self.fresh()
        sb.stub("codex")
        sb.stub("claude")
        sb.calls_of("codex")
        with self.assertRaises(AssertionError) as caught:
            sb.cleanup()
        self.assertIn("claude", str(caught.exception))
        self.assertNotIn("codex", str(caught.exception))

    def test_a_sandbox_with_no_stubs_passes(self):
        self.fresh().cleanup()

    def test_a_stub_that_is_not_one_of_the_four_is_not_checked(self):
        sb = self.fresh()
        sb.stub("sleepy")
        sb.cleanup()

    def test_a_stub_written_twice_needs_one_read(self):
        sb = self.fresh()
        sb.stub("codex")
        sb.stub_script("codex", "exit 0")
        sb.calls_of("codex")
        sb.cleanup()

    def test_cleanup_called_twice_raises_once(self):
        sb = self.fresh()
        sb.stub("tmux")
        with self.assertRaises(AssertionError):
            sb.cleanup()
        sb.cleanup()


class Baseline(Fresh):
    """The ratchet: tests that predate the rule are listed; the list may only shrink."""

    def listed(self):
        return mock.patch.object(hermetic, "BASELINE", {short_id(self)})

    def test_a_new_test_outside_the_baseline_fails(self):
        with mock.patch.object(hermetic, "BASELINE", set()):
            sb = self.fresh()
            sb.stub("codex")
            with self.assertRaises(AssertionError):
                sb.cleanup()

    def test_a_listed_test_may_leave_a_stub_unread(self):
        with self.listed():
            sb = self.fresh()
            sb.stub("codex")
            sb.cleanup()

    def test_a_listed_test_that_now_reads_everything_must_come_off_the_list(self):
        with self.listed():
            sb = self.fresh()
            sb.stub("codex")
            sb.calls_of("codex")
            with self.assertRaises(AssertionError) as caught:
                sb.cleanup()
            self.assertIn("unread_stub_baseline.txt", str(caught.exception))

    def test_a_listed_test_with_two_sandboxes_stays_listed_while_one_is_unread(self):
        with self.listed():
            first, second = self.fresh(), self.fresh()
            first.stub("codex")
            first.calls_of("codex")
            second.stub("gh")
            second.cleanup()
            first.cleanup()

    def test_the_checked_in_baseline_holds_only_test_ids(self):
        for entry in hermetic.load_baseline():
            self.assertRegex(entry, r"^test_\w+\.\w+\.test_\w+$")

    def test_a_test_that_forgets_to_clean_up_is_still_checked(self):
        class Forgetful(unittest.TestCase):
            def runTest(inner):
                sb = Sandbox()
                inner.addCleanup(sb.reap)       # reaps, but never calls sb.cleanup
                sb.stub("codex")

        with mock.patch.object(hermetic, "BASELINE", set()):
            result = unittest.TestResult()
            Forgetful().run(result)
        self.assertEqual(len(result.errors) + len(result.failures), 1)
        self.assertIn("codex", (result.errors + result.failures)[0][1])


if __name__ == "__main__":
    unittest.main()
