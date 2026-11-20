#!/usr/bin/env python3
"""Tests for memfloor.py: a spawn leaves at least the floor of MemAvailable free.

Run: python3 skills/boss/test_memfloor.py
"""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import memfloor  # noqa: E402
import policy  # noqa: E402

GB = 1024 * 1024  # kB


class Cost(unittest.TestCase):
    def test_a_worker_costs_the_mean_of_the_boss_workers(self):
        self.assertEqual(memfloor.worker_cost_kb([2 * GB, 4 * GB]), 3 * GB)

    def test_a_cheap_or_unknown_worker_costs_at_least_half_a_gb(self):
        self.assertEqual(memfloor.worker_cost_kb([]), GB // 2)
        self.assertEqual(memfloor.worker_cost_kb([100_000]), GB // 2)


class Refusal(unittest.TestCase):
    def test_room_above_the_floor_is_no_refusal(self):
        self.assertIsNone(memfloor.refusal(12 * GB, [GB]))

    def test_exactly_the_floor_left_is_allowed(self):
        self.assertIsNone(memfloor.refusal(9 * GB, [GB]))

    def test_under_the_floor_after_the_spawn_is_refused_with_the_numbers(self):
        msg = memfloor.refusal(int(8.5 * GB), [GB])
        self.assertIn("8.5 GB free", msg)
        self.assertIn("1.0 GB", msg)
        self.assertIn("%d GB floor" % policy.MEMORY_FLOOR_GB, msg)


class Reading(unittest.TestCase):
    def test_mem_available_is_read_from_the_meminfo_text(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "meminfo"
            f.write_text("MemTotal:  32000000 kB\nMemAvailable:   9000000 kB\n")
            self.assertEqual(memfloor.mem_available_kb(str(f)), 9_000_000)

    def test_the_command_refuses_with_exit_1_and_says_why(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "meminfo"
            f.write_text("MemAvailable:   %d kB\n" % (8 * GB))
            r = subprocess.run([sys.executable, str(HERE / "memfloor.py"), "check", "--meminfo", str(f)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("8.0 GB free", r.stderr)

    def test_an_unreadable_meminfo_refuses_without_a_traceback(self):
        r = subprocess.run([sys.executable, str(HERE / "memfloor.py"), "check", "--meminfo", "/nonexistent"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read MemAvailable", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_the_command_passes_with_room(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "meminfo"
            f.write_text("MemAvailable:   %d kB\n" % (20 * GB))
            r = subprocess.run([sys.executable, str(HERE / "memfloor.py"), "check", "--meminfo", str(f)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class Settling(unittest.TestCase):
    def test_settle_waits_until_the_worker_has_grown_to_its_cost(self):
        sizes = iter([10, 50, 200, 200])
        slept = []
        self.assertTrue(memfloor.settle(200, 30, lambda: next(sizes), sleep=slept.append))
        self.assertEqual(len(slept), 2)

    def test_settle_gives_up_after_the_timeout(self):
        now = [0.0]
        def sleep(s):
            now[0] += s
        self.assertFalse(memfloor.settle(200, 3, lambda: 1, poll=1, clock=lambda: now[0], sleep=sleep))
        self.assertEqual(now[0], 3)

    def test_settle_ends_once_the_tree_is_up_and_has_stopped_growing(self):
        sizes = iter([0, 10, 50, 120] + [120] * 40)
        slept = []
        self.assertTrue(memfloor.settle(10 ** 9, 30, lambda: next(sizes), sleep=slept.append))
        self.assertLess(len(slept), 12)     # the timeout would be 60 polls

    def test_settle_does_not_end_on_a_tree_that_is_not_up(self):
        now = [0.0]
        def sleep(s):
            now[0] += s
        self.assertFalse(memfloor.settle(10 ** 9, 5, lambda: 0, clock=lambda: now[0], sleep=sleep))
        self.assertEqual(now[0], 5)

    def test_settle_on_a_real_long_lived_tree_ends_well_before_the_timeout(self):
        tree = subprocess.Popen(["sh", "-c", "sleep 60 & wait"])
        self.addCleanup(lambda: (subprocess.run(["pkill", "-P", str(tree.pid)]), tree.kill(), tree.wait()))
        time.sleep(0.3)
        t0 = time.monotonic()
        self.assertTrue(memfloor.settle(10 ** 9, 30, lambda: memfloor.tree_rss_kb(str(tree.pid))))
        self.assertLess(time.monotonic() - t0, 10)


if __name__ == "__main__":
    unittest.main()

