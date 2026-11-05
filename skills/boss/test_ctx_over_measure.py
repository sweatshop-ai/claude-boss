"""routines/ctx_over_measure.py on a synthetic transcript: no real text anywhere."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "routines"))
import ctx_over_measure as m  # noqa: E402


def asst(i, ctx):
    return dict(type="assistant", message=dict(id="m%d" % i, usage=dict(
        input_tokens=1, cache_read_input_tokens=ctx, cache_creation_input_tokens=0, output_tokens=10)))


def user(text):
    return dict(type="user", message=dict(content=text))


def write(d, recs, name="s.jsonl"):
    p = Path(d) / name
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return p


DISPATCH = user('<cross-session-message from="uds:/x.sock">Boss dispatch from B, track `t`')


class Measure(unittest.TestCase):
    def test_worker_needs_the_dispatch_as_a_message(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(m.is_worker(write(d, [DISPATCH], "a.jsonl")))
            quoted = dict(type="user", message=dict(content=[dict(type="tool_result", content="Boss dispatch from B")]))
            self.assertFalse(m.is_worker(write(d, [quoted], "b.jsonl")))
            self.assertFalse(m.is_worker(write(d, [user("hello")], "c.jsonl")))

    def test_ask_after_crossing(self):
        recs = [DISPATCH] + [asst(i, 100_000 + i * 20_000) for i in range(10)]    # crosses 250k at turn 8
        recs += [user('<cross-session-message from="uds:/x.sock">you are at 280k, stop at the next boundary')]
        recs += [asst(10 + i, 290_000) for i in range(5)]
        with tempfile.TemporaryDirectory() as d:
            r = m.scan(write(d, recs))
        self.assertEqual((r["split_at"], r["over_at"]), (3, 8))
        self.assertTrue(r["asked_after"])
        self.assertEqual(r["turns_after_ask"], 5)
        self.assertTrue(r["ended_after_ask"])
        self.assertEqual(r["left_at_cross"], 7)

    def test_ask_before_the_crossing_is_not_after(self):
        recs = [DISPATCH] + [asst(i, 100_000 + i * 20_000) for i in range(8)]     # turn 7 is 240k, turn 8 would cross
        recs += [user('<cross-session-message from="uds:/x.sock">stop at the next boundary')]
        recs += [asst(8 + i, 260_000) for i in range(3)]
        with tempfile.TemporaryDirectory() as d:
            r = m.scan(write(d, recs))
        self.assertEqual(r["over_at"], 8)
        self.assertFalse(r["asked_after"])
        self.assertTrue(r["asked_between"])

    def test_ordinary_messages_are_not_asks(self):
        for tx in ("what is the current status of CI", "stop at the first failure", "see CTX-SPLIT in the list"):
            self.assertIsNone(m.ASK.search(tx), tx)
        for tx in ("you are at 267k", "stop at the current state", "(CTX-OVER)", "how much is left?", "how many turns are left"):
            self.assertTrue(m.ASK.search(tx), tx)

    def test_never_asked(self):
        recs = [DISPATCH] + [asst(i, 260_000) for i in range(4)]
        with tempfile.TemporaryDirectory() as d:
            r = m.scan(write(d, recs))
        self.assertFalse(r["asked_after"])
        self.assertGreater(r["cost_over"], 0)


if __name__ == "__main__":
    unittest.main()
