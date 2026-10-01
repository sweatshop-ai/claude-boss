#!/usr/bin/env python3
"""Tests for policy.py, and for the prose that quotes it.

Run: python3 -m pytest skills/boss/test_policy.py
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import policy  # noqa: E402


def k(n):
    return "%dk" % (n // 1000)


class Flags(unittest.TestCase):
    def test_worker_bands(self):
        W = policy.WORKER
        self.assertEqual(policy.flag_for(policy.WORKER_SPLIT - 1, 0, W), [])
        self.assertEqual(policy.flag_for(policy.WORKER_SPLIT, 0, W), ["CTX-SPLIT"])
        self.assertEqual(policy.flag_for(policy.WORKER_OVER, 0, W), ["CTX-OVER"])

    def test_boss_bands(self):
        B = policy.BOSS
        self.assertEqual(policy.flag_for(policy.WORKER_OVER, 0, B), [])
        self.assertEqual(policy.flag_for(policy.BOSS_EVAL, 0, B), ["CTX-EVAL"])
        self.assertEqual(policy.flag_for(policy.BOSS_RESTART, 0, B), ["CTX-RESTART"])

    def test_cost_lines_come_first(self):
        self.assertEqual(policy.flag_for(0, policy.COST_HEAVY, policy.WORKER), ["heavy"])
        self.assertEqual(policy.flag_for(policy.WORKER_SPLIT, policy.COST_RECYCLE, policy.WORKER),
                         ["RECYCLE", "CTX-SPLIT"])

    def test_unknown_values_raise_nothing(self):
        self.assertEqual(policy.flag_for(None, None, policy.WORKER), [])

    def test_heavy_by_role(self):
        self.assertTrue(policy.heavy(policy.WORKER_SPLIT, 0))
        self.assertFalse(policy.heavy(policy.WORKER_SPLIT, 0, policy.BOSS))
        self.assertTrue(policy.heavy(0, policy.COST_RECYCLE, policy.BOSS))


class Rungs(unittest.TestCase):
    def test_schedule(self):
        want = {0: None, 4: None, 5: 5, 14: 5, 15: 15, 29: 15, 30: 30, 59: 30, 60: 60,
                119: 60, 120: 120, 239: 120, 240: 240, 1439: 1320, 1440: 1440, 5000: 1440}
        for m, r in want.items():
            self.assertEqual(policy.rung_for(m), r, m)

    def test_next(self):
        self.assertEqual([policy.next_rung(r) for r in (5, 15, 30, 60, 120, 1320)],
                         [15, 30, 60, 120, 240, 1440])

    def test_ladder_and_pulse_share_it(self):
        sys.path.insert(0, str(ROOT / "routines"))
        import boss_ladder_core
        self.assertIs(boss_ladder_core.rung_for, policy.rung_for)
        self.assertIs(boss_ladder_core.next_rung, policy.next_rung)
        self.assertNotIn("RUNGS =", (HERE / "boss-pulse.py").read_text(encoding="utf-8"))


# Every place the prose quotes a policy number, as the exact text it must
# contain. Change a number in policy.py and this names the files to update.
QUOTES = {
    "skills/boss/SKILL.md": [
        "At **%s** a worker shows `CTX-SPLIT`" % k(policy.WORKER_SPLIT),
        "At **%s** it shows\n`CTX-OVER`" % k(policy.WORKER_OVER),
        "fits in\n%s:" % k(policy.WORKER_SPLIT),
        "`list` also flags `heavy` at %s and `RECYCLE` at %s cost per turn"
        % (k(policy.COST_HEAVY), k(policy.COST_RECYCLE)),
        "You keep a %d–%dk\nband" % (policy.BOSS_EVAL // 1000, policy.BOSS_RESTART // 1000),
        "before you reach the %s line" % k(policy.BOSS_RESTART),
        "the %s split fire first" % k(policy.WORKER_SPLIT),
        "They show up below %s too" % k(policy.WORKER_SPLIT),
        "A worker crossing %s is asked" % k(policy.WORKER_SPLIT),
    ],
    "skills/team/SKILL.md": [
        "**above ~%s of context or ~%s cost-units per turn**" % (k(policy.WORKER_SPLIT), k(policy.COST_RECYCLE)),
        "A task bigger than ~%s gets split" % k(policy.WORKER_SPLIT),
        "past ~%s the split is overdue" % k(policy.WORKER_OVER),
    ],
    "skills/boss/references/models.md": [
        "the context lines (%s/%s\nfor workers, %s/%s for the boss) and the %s/%s cost-per-turn lines"
        % (k(policy.WORKER_SPLIT), k(policy.WORKER_OVER), k(policy.BOSS_EVAL), k(policy.BOSS_RESTART),
           k(policy.COST_HEAVY), k(policy.COST_RECYCLE)),
    ],
    "skills/boss/bin/boss-start": [
        "(workers use %s/%s)" % (k(policy.WORKER_SPLIT), k(policy.WORKER_OVER)),
        "below the %s" % k(policy.BOSS_RESTART),
    ],
    "skills/boss/references/escalation.md": [
        "**T+%d, T+%d, T+%d, then every %d**" % (policy.RUNGS[2], policy.RUNGS[3], policy.RUNGS[4], policy.RUNG_EVERY),
        "stop at %d h" % (policy.STOP_MIN // 60),
    ],
    "routines/boss-ladder.md": [
        "T+%d, T+%d, T+%d, T+%d, T+%d and every %d after" % (policy.RUNGS + (policy.RUNG_EVERY,)),
    ],
}


class ProseQuotesPolicy(unittest.TestCase):
    def test_every_quote_matches(self):
        missing = []
        for rel, quotes in QUOTES.items():
            text = (ROOT / rel).read_text(encoding="utf-8")
            text = "\n".join(line.lstrip("# ").rstrip() if rel.endswith("boss-start") else line
                             for line in text.splitlines())
            missing += ["%s: %r" % (rel, q) for q in quotes if q not in text]
        self.assertEqual(missing, [], "prose out of step with policy.py:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
