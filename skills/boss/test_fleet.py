#!/usr/bin/env python3
"""Tests for fleet.py: which tmux pane runs which Claude session, who owns it.

Run: python3 skills/boss/test_fleet.py

The rules are tested through the in-memory adapter; the tmux adapter is tested
against a stub `tmux` on PATH. No test reads or changes a real pane.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet  # noqa: E402


def rec(sid, pane, name="", started=1000, status="idle"):
    return {"sessionId": sid, "tmux": "boss:@1.%s" % pane, "name": name,
            "startedAt": started, "status": status, "pid": 1}


class WhichSessionRunsInAPane(unittest.TestCase):
    def test_a_pane_runs_the_session_whose_record_names_it(self):
        tmux = fleet.MemoryTmux([fleet.Pane("%5"), fleet.Pane("%6")])
        seats = fleet.view(tmux, [rec("s-wanda", "%5", "Wanda")])
        self.assertEqual([(s.pane.id, s.session and s.session["name"]) for s in seats],
                         [("%5", "Wanda"), ("%6", None)])

    def test_two_sessions_on_one_pane_the_oldest_wins_and_the_flag_explains(self):
        # A claude started from inside Wanda's pane inherits its TMUX_PANE.
        tmux = fleet.MemoryTmux([fleet.Pane("%5")])
        child = rec("s-casimir", "%5", "Casimir", started=1792943232302)
        own = rec("s-wanda", "%5", "Wanda", started=1792940000000)
        [seat] = fleet.view(tmux, [child, own])
        self.assertEqual(seat.session["name"], "Wanda")
        self.assertEqual(seat.flags(), ["shared-pane"])
        why = seat.explain()
        self.assertIn("2 live sessions", why)
        self.assertIn("Wanda", why)
        self.assertIn("Casimir (s-casimir", why)
        self.assertIn("oldest", why)

    def test_a_pane_with_one_session_has_no_flag_and_nothing_to_explain(self):
        [seat] = fleet.view(fleet.MemoryTmux([fleet.Pane("%5")]), [rec("s-wanda", "%5", "Wanda")])
        self.assertEqual((seat.flags(), seat.explain()), ([], ""))


class WhoOwnsAPane(unittest.TestCase):
    def test_a_boss_owns_the_panes_it_stamped_but_not_its_own(self):
        tmux = fleet.MemoryTmux([fleet.Pane("%1"), fleet.Pane("%5"), fleet.Pane("%6"),
                                 fleet.Pane("%7", owner="%9")])
        for pane in ("%1", "%5"):
            tmux.stamp(pane, "%1")
        seats = fleet.view(tmux, [])
        self.assertEqual([s.pane.id for s in fleet.owned(seats, "%1")], ["%5"])
        self.assertEqual([s.pane.id for s in fleet.owned(seats, "%9")], ["%7"])

    def test_no_boss_pane_owns_nothing(self):
        tmux = fleet.MemoryTmux([fleet.Pane("%5", owner="")])
        self.assertEqual(fleet.owned(fleet.view(tmux, []), ""), [])

    def test_a_session_is_found_by_its_id(self):
        tmux = fleet.MemoryTmux([fleet.Pane("%1"), fleet.Pane("%5")])
        seats = fleet.view(tmux, [rec("s-boss", "%1", "Lucas"), rec("s-wanda", "%5", "Wanda")])
        self.assertEqual(fleet.seat_of(seats, sid="s-boss").pane.id, "%1")
        self.assertEqual(fleet.seat_of(seats, pane="%5").session["name"], "Wanda")
        self.assertIsNone(fleet.seat_of(seats, sid="nobody"))

    def test_a_younger_session_on_a_shared_pane_is_found_too(self):
        tmux = fleet.MemoryTmux([fleet.Pane("%5")])
        seats = fleet.view(tmux, [rec("s-wanda", "%5", "Wanda", 1), rec("s-kid", "%5", "Kid", 2)])
        self.assertEqual(fleet.seat_of(seats, sid="s-kid").pane.id, "%5")


# Prints what list-panes would for the format it is given: a stub cannot
# expand #{...}, so it answers the one format fleet.Tmux sends.
STUB_TMUX = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_DIR/calls"
[[ -f "$STUB_DIR/fails" ]] && exit 1
[[ "$1" == list-panes ]] && cat "$STUB_DIR/panes"
exit 0
'''


class TheTmuxAdapter(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tmux").write_text(STUB_TMUX)
        os.chmod(self.dir / "tmux", 0o755)
        self.env = {"PATH": "%s:%s" % (self.dir, os.environ["PATH"]), "STUB_DIR": str(self.dir)}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def calls(self):
        return (self.dir / "calls").read_text().splitlines()

    def test_unset_options_read_as_empty_and_never_shift_a_field(self):
        (self.dir / "panes").write_text(
            "%1\tboss:0.0\t%1\tclaude\t/home/x\t-\n"
            "%5\tboss:0.1\t%1\tbash\t/home/y\tWanda\n"
            "%6\tmail:1.0\t-\tclaude\t/home/z\t-\n")
        panes = fleet.Tmux().panes()
        self.assertEqual(panes[1], fleet.Pane("%5", "boss:0.1", "%1", "bash", "/home/y", "Wanda"))
        self.assertEqual((panes[2].owner, panes[2].mirror, panes[2].coord), ("", "", "mail:1.0"))
        # every option is wrapped so tmux prints "-", never an empty field
        fmt = self.calls()[0]
        self.assertIn("#{?@boss_pane,#{@boss_pane},-}", fmt)
        self.assertIn("#{?@worker_name,#{@worker_name},-}", fmt)

    def test_a_server_with_no_panes_is_an_empty_fleet(self):
        (self.dir / "panes").write_text("")
        self.assertEqual(fleet.Tmux().panes(), [])

    def test_a_tmux_that_fails_is_not_an_empty_fleet(self):
        (self.dir / "fails").touch()
        with self.assertRaises(fleet.TmuxUnavailable):
            fleet.Tmux().panes()

    def test_a_stamp_sets_the_pane_option(self):
        fleet.Tmux().stamp("%5", "%1")
        self.assertEqual(self.calls(), ["set-option -p -t %5 @boss_pane %1"])


if __name__ == "__main__":
    unittest.main()
