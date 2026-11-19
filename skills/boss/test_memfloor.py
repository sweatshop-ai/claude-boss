#!/usr/bin/env python3
"""Tests for memfloor.py: a spawn leaves at least the floor of MemAvailable free.

Run: python3 skills/boss/test_memfloor.py
"""
import subprocess
import sys
import tempfile
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

    def test_the_command_passes_with_room(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "meminfo"
            f.write_text("MemAvailable:   %d kB\n" % (20 * GB))
            r = subprocess.run([sys.executable, str(HERE / "memfloor.py"), "check", "--meminfo", str(f)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
