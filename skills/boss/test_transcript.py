#!/usr/bin/env python3
"""Tests for transcript.py, on JSONL fixtures written to a temporary directory.

Run: python3 -m pytest skills/boss/test_transcript.py
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import transcript  # noqa: E402


def turn(uuid, inp=0, cw=0, cr=0, out=0):
    return {"type": "assistant", "uuid": uuid, "message": {"content": [], "usage": {
        "input_tokens": inp, "cache_creation_input_tokens": cw,
        "cache_read_input_tokens": cr, "output_tokens": out}}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "t.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, records, extra=""):
        self.path.write_text("\n".join(json.dumps(d) for d in records) + "\n" + extra)


class Tail(Fixture):
    def test_missing_file_or_no_path_is_empty(self):
        self.assertEqual(transcript.tail(self.tmp / "absent.jsonl"), [])
        self.assertEqual(transcript.tail(None), [])

    def test_skips_blank_broken_and_non_object_lines(self):
        self.write([{"type": "user", "uuid": "u1"}], extra="\n{not json\n[1, 2]\n")
        self.assertEqual(transcript.tail(self.path), [{"type": "user", "uuid": "u1"}])

    def test_drops_the_line_cut_by_the_seek(self):
        self.write([{"type": "user", "uuid": "u%d" % i, "pad": "x" * 50} for i in range(20)])
        size = self.path.stat().st_size
        recs = transcript.tail(self.path, nbytes=size // 2)
        uuids = [d["uuid"] for d in recs]
        self.assertEqual(uuids[-1], "u19")
        self.assertLess(len(uuids), 20)
        # Every record returned is whole: the cut line is dropped, not misparsed.
        self.assertTrue(all(d["pad"] == "x" * 50 for d in recs))

    def test_whole_file_when_smaller_than_the_tail(self):
        self.write([{"type": "user", "uuid": "u1"}, {"type": "user", "uuid": "u2"}])
        self.assertEqual([d["uuid"] for d in transcript.tail(self.path)], ["u1", "u2"])


class Usage(unittest.TestCase):
    def test_no_usage_is_zero(self):
        self.assertEqual(transcript.usage([{"type": "user", "message": "text"}]), (0, 0, 0))

    def test_context_is_the_last_turn_input_side(self):
        recs = [turn("a1", inp=1, cw=2, cr=3, out=99), turn("a2", inp=10, cw=20, cr=300, out=7)]
        ctx, _, turns = transcript.usage(recs)
        self.assertEqual(ctx, 330)
        self.assertEqual(turns, 2)

    def test_cost_is_priced_and_averaged(self):
        recs = [turn("a1", inp=100, cw=100, cr=1000, out=10), turn("a2", out=20)]
        _, cost, _ = transcript.usage(recs)
        first = 100 * transcript.W_IN + 100 * transcript.W_CACHE_WRITE \
            + 1000 * transcript.W_CACHE_READ + 10 * transcript.W_OUT
        self.assertAlmostEqual(cost, (first + 20 * transcript.W_OUT) / 2)

    def test_cost_covers_only_the_band(self):
        recs = [turn("old", out=1000)] + [turn("a%d" % i, out=10) for i in range(3)]
        _, cost, turns = transcript.usage(recs, band=3)
        self.assertAlmostEqual(cost, 10 * transcript.W_OUT)
        self.assertEqual(turns, 4)


class Pin(unittest.TestCase):
    def test_ignores_records_idle_sessions_append(self):
        recs = [
            {"type": "user", "uuid": "u1", "message": {"content": "x"}},
            {"type": "assistant", "uuid": "a1", "message": {"content": []}},
            {"type": "system", "uuid": "s1", "subtype": "away_summary"},
            {"type": "ai-title", "aiTitle": "t"},
        ]
        self.assertEqual(transcript.pin(recs), "a1")

    def test_a_queued_command_moves_the_pin(self):
        recs = [
            {"type": "assistant", "uuid": "a1"},
            {"type": "attachment", "uuid": "q1", "attachment": {"type": "queued_command"}},
            {"type": "attachment", "uuid": "f1", "attachment": {"type": "file"}},
        ]
        self.assertEqual(transcript.pin(recs), "q1")

    def test_none_without_a_conversation_record(self):
        self.assertIsNone(transcript.pin([{"type": "system", "uuid": "s1"}]))


class FromDisk(Fixture):
    def test_pin_and_usage_read_through_tail(self):
        self.write([
            {"type": "user", "uuid": "u1", "message": {"content": "go"}},
            turn("a1", inp=5, cr=95, out=1),
            {"type": "system", "uuid": "s1", "subtype": "away_summary"},
        ])
        recs = transcript.tail(self.path)
        self.assertEqual(transcript.pin(recs), "a1")
        self.assertEqual(transcript.usage(recs)[0], 100)


if __name__ == "__main__":
    unittest.main()
