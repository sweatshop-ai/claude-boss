#!/usr/bin/env python3
"""Tests for boss_store.py and bin/boss-marker — the boss marker, one rule.

Run: python3 skills/boss/test_boss_store.py

`pm/.boss-sessions/<session_id>` says a session is a boss, and its first line
names the track. Every hook reads it through boss_store; the boss writes it
through `boss-marker register`.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boss_store  # noqa: E402

MARKER = HERE.parent.parent / "bin" / "boss-marker"
SID = "11111111-1111-1111-1111-111111111111"


class Store(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.markers = self.cfg / "pm" / ".boss-sessions"

    def cli(self, *args, sid=SID):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), CLAUDE_CODE_SESSION_ID=sid)
        return subprocess.run([str(MARKER), *args], env=env, capture_output=True, text=True)

    def test_register_makes_a_boss_and_names_its_track(self):
        out = self.cli("register", "lead-engine")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(boss_store.is_boss(SID, self.cfg))
        self.assertEqual(boss_store.track_of(SID, self.cfg), "lead-engine")

    def test_register_without_a_track_is_a_boss_with_no_track_yet(self):
        self.cli("register")
        self.assertTrue(boss_store.is_boss(SID, self.cfg))
        self.assertEqual(boss_store.track_of(SID, self.cfg), "")

    def test_a_track_that_is_not_a_plain_name_is_refused(self):
        # The track becomes a file name under pm/.
        for bad in ("../etc", "Lead Engine", ".hidden", "a/b", "x" * 65):
            out = self.cli("register", bad)
            self.assertNotEqual(out.returncode, 0, bad)
        self.assertFalse(boss_store.is_boss(SID, self.cfg))

    def test_a_marker_written_by_hand_with_a_bad_track_has_no_track(self):
        self.markers.mkdir(parents=True)
        (self.markers / SID).write_text("../../settings\n")
        self.assertTrue(boss_store.is_boss(SID, self.cfg))
        self.assertEqual(boss_store.track_of(SID, self.cfg), "")

    def test_a_symlink_or_a_directory_is_not_a_marker(self):
        self.markers.mkdir(parents=True)
        (self.markers / SID).symlink_to(self.cfg / "elsewhere")
        (self.cfg / "elsewhere").write_text("lead-engine\n")
        self.assertFalse(boss_store.is_boss(SID, self.cfg))
        other = "22222222-2222-2222-2222-222222222222"
        (self.markers / other).mkdir()
        self.assertFalse(boss_store.is_boss(other, self.cfg))

    def test_a_session_id_that_is_not_one_is_never_a_boss(self):
        self.assertFalse(boss_store.is_boss("../x", self.cfg))
        self.assertFalse(boss_store.is_boss("", self.cfg))

    def test_register_needs_the_session_id(self):
        out = self.cli("register", "lead-engine", sid="")
        self.assertNotEqual(out.returncode, 0)


class FrontierCache(unittest.TestCase):
    def test_it_lives_under_the_pulse_state_keyed_by_track_and_source(self):
        a = boss_store.frontier_cache("demo", "gh:a/b#1", cfg="/c")
        self.assertEqual(a.parent, Path("/c/pm/.pulse"))
        self.assertRegex(a.name, r"^demo\.[0-9a-f]{10}\.frontier\.json$")
        self.assertNotEqual(a, boss_store.frontier_cache("demo", "gh:a/b#2", cfg="/c"))

    def test_an_empty_config_dir_is_the_home_one(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}):
            self.assertEqual(boss_store.frontier_cache("t", "s").parent, Path.home() / ".claude/pm/.pulse")


class StateFiles(unittest.TestCase):
    """Per-session state: one locked read-modify-write, safe against a crash."""

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.pulse = self.cfg / "pm" / ".pulse"

    def test_state_path_keeps_the_file_names_the_hooks_always_used(self):
        self.assertEqual(boss_store.state_path(SID, "guard", self.cfg),
                         self.pulse / (SID + ".guard.json"))
        self.assertEqual(boss_store.state_path(SID, "pulse", self.cfg),
                         self.pulse / (SID + ".json"))

    def test_a_kind_or_session_that_is_not_a_name_is_refused(self):
        with self.assertRaises(ValueError):
            boss_store.state_path(SID, "../x", self.cfg)
        with self.assertRaises(ValueError):
            boss_store.state_path("../x", "guard", self.cfg)

    def test_update_on_a_missing_file_starts_from_empty_and_writes_it(self):
        seen = []
        out = boss_store.update_state(SID, "guard", lambda st: seen.append(dict(st)) or st.update(n=1),
                                      cfg=self.cfg)
        self.assertEqual(seen, [{}])
        self.assertEqual(out, {"n": 1})
        self.assertEqual(json.loads(boss_store.state_path(SID, "guard", self.cfg).read_text()),
                         {"n": 1})

    def test_update_on_unreadable_json_starts_from_empty(self):
        self.pulse.mkdir(parents=True)
        boss_store.state_path(SID, "guard", self.cfg).write_text("{not json")
        out = boss_store.update_state(SID, "guard", lambda st: st.update(n=1), cfg=self.cfg)
        self.assertEqual(out, {"n": 1})

    def test_json_that_is_not_an_object_starts_from_empty(self):
        self.pulse.mkdir(parents=True)
        boss_store.state_path(SID, "guard", self.cfg).write_text("[1, 2]")
        out = boss_store.update_state(SID, "guard", lambda st: st.update(n=1), cfg=self.cfg)
        self.assertEqual(out, {"n": 1})

    def test_fn_may_return_a_new_dict_instead_of_changing_the_old(self):
        out = boss_store.update_state(SID, "guard", lambda st: {"n": 7}, cfg=self.cfg)
        self.assertEqual(out, {"n": 7})
        self.assertEqual(boss_store.read_state(SID, "guard", self.cfg), {"n": 7})

    def test_a_fn_that_raises_leaves_the_old_file_byte_identical(self):
        self.pulse.mkdir(parents=True)
        f = boss_store.state_path(SID, "guard", self.cfg)
        f.write_bytes(b'{"n":  3 }\n')

        def boom(st):
            st["n"] = 99
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            boss_store.update_state(SID, "guard", boom, cfg=self.cfg)
        self.assertEqual(f.read_bytes(), b'{"n":  3 }\n')
        self.assertEqual([p.name for p in self.pulse.iterdir() if p != f and not p.name.endswith(".lock")], [])

    def test_the_write_is_a_replace_in_the_same_directory(self):
        self.pulse.mkdir(parents=True)
        f = boss_store.state_path(SID, "guard", self.cfg)
        f.write_text("{}")
        before = os.stat(f).st_ino
        boss_store.update_state(SID, "guard", lambda st: st.update(n=1), cfg=self.cfg)
        self.assertNotEqual(os.stat(f).st_ino, before)
        self.assertEqual(sorted(p.name for p in self.pulse.iterdir() if p.suffix == ".tmp"), [])

    def test_an_unwritable_directory_still_returns_the_new_state(self):
        (self.cfg / "pm").mkdir()
        (self.cfg / "pm").chmod(0o500)
        try:
            if os.access(self.cfg / "pm", os.W_OK):
                self.skipTest("running as a user who can write anywhere")
            out = boss_store.update_state(SID, "guard", lambda st: st.update(n=1), cfg=self.cfg)
        finally:
            (self.cfg / "pm").chmod(0o700)
        self.assertEqual(out, {"n": 1})

    def test_the_lock_is_a_file_reap_can_never_pick(self):
        boss_store.update_state(SID, "guard", lambda st: st.update(n=1), cfg=self.cfg)
        locks = [p for p in self.pulse.iterdir() if p.name.endswith(".lock")]
        self.assertTrue(locks)
        self.assertFalse(boss_store.UUID.search(locks[0].name))
        self.assertEqual([p.name for p, _ in boss_store.reap_candidates(self.cfg)
                          if p.name.endswith(".lock")], [])

    def test_a_reaped_state_file_does_not_split_the_lock(self):
        # reap deletes the state file between two updates; the lock file is a
        # different, stable file, so both updates lock the same inode.
        boss_store.update_state(SID, "guard", lambda st: st.update(n=1), cfg=self.cfg)
        lock = [p for p in self.pulse.iterdir() if p.name.endswith(".lock")][0]
        ino = os.stat(lock).st_ino
        boss_store.state_path(SID, "guard", self.cfg).unlink()
        out = boss_store.update_state(SID, "guard", lambda st: st.update(n=st.get("n", 0) + 1),
                                      cfg=self.cfg)
        self.assertEqual(out, {"n": 1})
        self.assertEqual(os.stat(lock).st_ino, ino)

    def test_concurrent_updates_lose_none(self):
        code = ("import sys; sys.path.insert(0, %r); import boss_store\n"
                "for _ in range(25):\n"
                "    boss_store.update_state(%r, 'guard', lambda st: st.update(n=st.get('n', 0) + 1), cfg=%r)\n"
                % (str(HERE), SID, str(self.cfg)))
        procs = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(4)]
        for p in procs:
            self.assertEqual(p.wait(timeout=60), 0)
        self.assertEqual(boss_store.read_state(SID, "guard", self.cfg), {"n": 100})


OLD_SID = "aaaaaaaa-1111-2222-3333-444444444444"


def old_rule(cfg):
    """0.16.0's boss-reap candidates(), written out: both directories, regular
    files that are not symlinks, whose name holds a UUID anywhere."""
    import re
    uuid = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    out = set()
    for d in (cfg / "pm" / ".boss-sessions", cfg / "pm" / ".pulse"):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_symlink() or not p.is_file():
                continue
            m = uuid.search(p.name)
            if m:
                out.add((p, m.group(0).lower()))
    return out


class NoHookBuildsAStatePath(unittest.TestCase):
    def test_guard_pulse_and_reap_leave_the_pulse_directory_to_the_store(self):
        for name in ("boss-guard.py", "boss-pulse.py", "boss-reap.py"):
            code = (HERE / name).read_text(encoding="utf-8")
            self.assertNotIn('".pulse"', code, name)
            self.assertNotIn("'.pulse'", code, name)
            self.assertNotIn(".boss-sessions\"", code, name)


class ReapCandidates(unittest.TestCase):

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.markers = self.cfg / "pm" / ".boss-sessions"
        self.pulse = self.cfg / "pm" / ".pulse"
        self.markers.mkdir(parents=True)
        self.pulse.mkdir(parents=True)

    def test_todays_file_names_give_exactly_the_old_candidates(self):
        names = {
            self.markers: [OLD_SID, SID.upper(), "no-uuid-here", "marker-" + OLD_SID],
            self.pulse: ["%s.json", "%s.guard.json", "jev-%s.json", "jev-%s.lock",
                         "demo.%s.frontier.json", "jev.mode", "jev.log",
                         "jev.mode.bak-2026-09-20", "demo.0123456789.frontier.json"],
        }
        for d, ns in names.items():
            for n in ns:
                (d / (n % OLD_SID if "%s" in n else n)).write_text("{}")
        (self.pulse / ("d-" + OLD_SID)).mkdir()
        (self.pulse / ("link-" + OLD_SID)).symlink_to(self.cfg)
        self.assertEqual(set(boss_store.reap_candidates(self.cfg)), old_rule(self.cfg))

    def test_a_name_with_no_uuid_is_never_a_candidate(self):
        for d in (self.markers, self.pulse):
            (d / "jev.log").write_text("x")
            (d / "1234-not-a-uuid").write_text("x")
        self.assertEqual(list(boss_store.reap_candidates(self.cfg)), [])

    def test_a_uuid_inside_an_unrelated_name_is_still_a_candidate(self):
        # Today's rule is UUID.search, not fullmatch: "notes-<uuid>.txt" is picked.
        # Kept as it is (reported, not changed).
        f = self.pulse / ("notes-%s.txt" % OLD_SID)
        f.write_text("x")
        self.assertEqual(list(boss_store.reap_candidates(self.cfg)), [(f, OLD_SID)])

    def test_missing_directories_give_nothing(self):
        self.assertEqual(list(boss_store.reap_candidates(self.cfg / "nowhere")), [])


class TrackFiles(unittest.TestCase):
    """The two files of a track: named and read by the store, never interpreted."""

    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp())
        self.pm = self.cfg / "pm"
        self.pm.mkdir()

    def test_the_paths_are_named_by_the_track(self):
        self.assertEqual(boss_store.objective_path("demo", self.cfg), self.pm / "demo.goal.md")
        self.assertEqual(boss_store.tracker_path("demo", self.cfg), self.pm / "demo.md")

    def test_no_path_is_built_for_a_bad_track_name(self):
        for bad in ("", "../evil", "a/b", "A", ".hidden", "x" * 65, None):
            self.assertIsNone(boss_store.objective_path(bad, self.cfg), repr(bad))
            self.assertIsNone(boss_store.tracker_path(bad, self.cfg), repr(bad))
            self.assertIsNone(boss_store.read_objective(bad, self.cfg), repr(bad))
            self.assertIsNone(boss_store.read_tracker(bad, self.cfg), repr(bad))

    def test_reads_return_the_text_as_written(self):
        (self.pm / "demo.goal.md").write_text("_Status: OPEN_\n", encoding="utf-8")
        (self.pm / "demo.md").write_text("# T \u2014 caf\u00e9\n", encoding="utf-8")
        self.assertEqual(boss_store.read_objective("demo", self.cfg), "_Status: OPEN_\n")
        self.assertEqual(boss_store.read_tracker("demo", self.cfg), "# T \u2014 caf\u00e9\n")

    def test_an_empty_file_is_empty_text_not_missing(self):
        (self.pm / "demo.md").write_text("")
        self.assertEqual(boss_store.read_tracker("demo", self.cfg), "")

    def test_a_missing_file_is_none(self):
        self.assertIsNone(boss_store.read_objective("demo", self.cfg))
        self.assertIsNone(boss_store.read_tracker("demo", self.cfg))

    def test_an_unreadable_file_is_none(self):
        (self.pm / "demo.goal.md").mkdir()          # a directory: open() fails with OSError
        self.assertIsNone(boss_store.read_objective("demo", self.cfg))
        f = self.pm / "demo.md"
        f.write_text("x")
        f.chmod(0)
        try:
            if os.access(f, os.R_OK):
                self.skipTest("running as a user who reads mode 000")
            self.assertIsNone(boss_store.read_tracker("demo", self.cfg))
        finally:
            f.chmod(0o600)

    def test_a_symlink_is_followed_as_today(self):
        real = self.cfg / "elsewhere.md"
        real.write_text("linked")
        (self.pm / "demo.md").symlink_to(real)
        self.assertEqual(boss_store.read_tracker("demo", self.cfg), "linked")

    def test_the_directory_follows_the_environment_at_call_time(self):
        (self.pm / "demo.md").write_text("here")
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.cfg)
        try:
            self.assertEqual(boss_store.read_tracker("demo"), "here")
        finally:
            if old is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
