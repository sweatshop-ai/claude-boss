#!/usr/bin/env python3
"""Tests for routines/boss_efficiency_core.py and boss-efficiency.sh.

Run: python3 -m pytest skills/boss/test_boss_efficiency.py

Every fixture is synthetic: invented track names and sockets, written into a
throwaway CLAUDE_CONFIG_DIR. Nothing here reads a real transcript.
"""
import datetime as dt
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent.parent
sys.path.insert(0, str(PLUGIN / "routines"))
import boss_efficiency_core as core  # noqa: E402

BODY = PLUGIN / "routines" / "boss-efficiency.sh"
NOW = dt.datetime(2026, 6, 15, 12, 0).timestamp()
DAY = 86400


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


class Cfg:
    """A throwaway config dir and the helpers that write transcripts into it."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        self.n = 0
        (self.dir / "pm" / ".boss-sessions").mkdir(parents=True)
        (self.dir / "projects" / "p").mkdir(parents=True)

    def goal(self, track):
        (self.dir / "pm" / (track + ".goal.md")).write_text("goal\n")

    def boss(self, track, sock_msgs, at, asks=0, cost=1000, **kw):
        """A boss session on `track`. sock_msgs: [(T, sock, text)] it receives."""
        sid = "boss%d" % self.n; self.n += 1
        (self.dir / "pm" / ".boss-sessions" / sid).write_text(track + "\n")
        self.session(sid, at, sock_msgs, cost, asks=asks, **kw)
        return sid

    def worker(self, at, sock_msgs, cost=1000, bash=None, **kw):
        sid = "wrk%d" % self.n; self.n += 1
        self.session(sid, at, sock_msgs, cost, bash=bash, **kw)
        return sid

    def session(self, sid, at, sock_msgs, cost, asks=0, bash=None, name=None, until=None, sends=(), cmds=(), listing=(), refused=0):
        """`name`: the start name the hook records. `until`: a last record at that time.
        `sends`: [(T, to)] SendMessage calls. `cmds`: [(T, command)] or [(T, command, False)] Bash calls and
        their result (success unless False). `listing`: [(T, text)] a ListAgents result the session got."""
        recs = []
        if name:
            recs.append(dict(type="attachment", timestamp=iso(at), attachment=dict(
                type="hook_additional_context", content=["Your name in this session is %s. Other Claude Code "
                                                         "sessions on this machine see you as it." % name])))
        for i, (T, to) in enumerate(sends):
            recs.append(dict(type="assistant", timestamp=iso(T), message=dict(id="s%d%s" % (i, sid), usage={}, content=[
                dict(type="tool_use", id="send%d%s" % (i, sid), name="SendMessage", input=dict(to=to, message="go"))])))
        for i, (T, cmd, *ok) in enumerate(cmds):
            recs.append(dict(type="assistant", timestamp=iso(T), message=dict(id="c%d%s" % (i, sid), usage={}, content=[
                dict(type="tool_use", id="cmd%d%s" % (i, sid), name="Bash", input=dict(command=cmd))])))
            recs.append(dict(type="user", timestamp=iso(T + 1), message=dict(content=[
                dict(type="tool_result", tool_use_id="cmd%d%s" % (i, sid), content="ok" if not ok or ok[0] else "Exit code 1",
                     is_error=bool(ok and not ok[0]))])))
        for i, (T, text) in enumerate(listing):
            recs.append(dict(type="assistant", timestamp=iso(T), message=dict(id="l%d%s" % (i, sid), usage={}, content=[
                dict(type="tool_use", id="ls%d%s" % (i, sid), name="ListAgents", input={})])))
            recs.append(dict(type="user", timestamp=iso(T + 1), message=dict(content=[
                dict(type="tool_result", tool_use_id="ls%d%s" % (i, sid), content=text)])))
        if until:
            recs.append(dict(type="assistant", timestamp=iso(until), message=dict(id="end" + sid, usage={}, content=[])))
        for T, sock, text in sock_msgs:
            recs.append(dict(type="user", timestamp=iso(T), message=dict(
                content='<cross-session-message from="%s" from-name="x">\n%s\n</cross-session-message>' % (sock, text))))
        t = at
        recs.append(dict(type="assistant", timestamp=iso(t), message=dict(
            id="m%s" % sid, usage=dict(input_tokens=cost, output_tokens=0), content=[])))
        for i in range(asks + refused):
            t += 60
            recs.append(dict(type="assistant", timestamp=iso(t), message=dict(id="a%d%s" % (i, sid), usage={}, content=[
                dict(type="tool_use", id="q%d%s" % (i, sid), name="AskUserQuestion", input={})])))
            recs.append(dict(type="user", timestamp=iso(t + 30), message=dict(content=[
                dict(type="tool_result", tool_use_id="q%d%s" % (i, sid), content="ok" if i < asks else "An open question stops your turn. Send it to your concierge Pia",
                     is_error=i >= asks)])))
        if bash:
            t += 60
            recs.append(dict(type="assistant", timestamp=iso(t), message=dict(id="b" + sid, usage={}, content=[
                dict(type="tool_use", id="t" + sid, name="Bash", input=dict(command=bash))])))
            recs.append(dict(type="user", timestamp=iso(t + 600), message=dict(content=[
                dict(type="tool_result", tool_use_id="t" + sid, content="ok")])))
        recs.sort(key=lambda r: r["timestamp"])
        with open(self.dir / "projects" / "p" / (sid + ".jsonl"), "w") as f:
            for r in recs: f.write(json.dumps(r) + "\n")



def week(cfg, end=NOW):
    cfg = Path(cfg) if not isinstance(cfg, Path) else cfg
    sessions = [core.scan_session(p, ["alpha-x", "beta-y"]) for p in (cfg / "projects").glob("*/*.jsonl")]
    sessions = [s for s in sessions if s]
    socks = core.resolve_sockets(sessions)
    idx = core.Index(sessions, core.markers(cfg), socks)
    return idx, core.measure_window(idx, end - 7 * DAY, end), socks


def seed(c, sock="uds:/run/cc-socks/1.sock", track="alpha-x", at=NOW - DAY, cost=1000, worker_cost=5000, wording=None):
    """One boss and one worker on `track`, the worker dispatched twice by `sock`."""
    w = wording or "Boss dispatch from Anton, track `%s`. Go."
    c.goal(track)
    c.worker(at, [(at, sock, w % track), (at + 120, sock, w % track)], cost=worker_cost, bash="echo hi")
    c.boss(track, [(at + 300, "uds:/run/cc-socks/worker.sock", "done")], at, cost=cost)


class Attribution(unittest.TestCase):
    def test_worker_is_found_through_the_boss_socket_whatever_the_wording(self):
        c = Cfg()
        sock = "uds:/run/cc-socks/1.sock"
        c.worker(NOW - DAY, [(NOW - DAY, sock, "Boss dispatch from Anton, track `alpha-x`. Go."),
                             (NOW - DAY + 100, sock, "Boss dispatch from Anton, track `alpha-x`. Go."),
                             (NOW - DAY + 200, sock, "Please carry on with the ticket, thanks")], cost=7000)
        c.boss("alpha-x", [], NOW - DAY, cost=1000)
        idx, wk, socks = week(c.dir)
        self.assertEqual(socks[sock], "alpha-x")
        # the third message has no dispatch wording at all; the socket still places it
        self.assertEqual(len(idx.workers["alpha-x"]), 3)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 7000)

    def test_a_boss_with_a_new_name_and_socket_is_picked_up(self):
        c = Cfg()
        seed(c, sock="uds:/run/cc-socks/OLD.sock", track="alpha-x")
        seed(c, sock="uds:/run/cc-socks/NEW.sock", track="beta-y", at=NOW - 2 * DAY)
        _, wk, socks = week(c.dir)
        self.assertEqual(socks["uds:/run/cc-socks/NEW.sock"], "beta-y")
        self.assertEqual(set(wk["tracks"]), {"alpha-x", "beta-y"})

    def test_one_track_whose_boss_moves_to_a_new_socket_keeps_its_workers(self):
        c = Cfg()
        old, new = "uds:/run/cc-socks/OLD.sock", "uds:/run/cc-socks/NEW.sock"
        seed(c, sock=old, at=NOW - 3 * DAY)
        seed(c, sock=new, at=NOW - DAY)
        _, wk, socks = week(c.dir)
        self.assertEqual((socks[old], socks[new]), ("alpha-x", "alpha-x"))
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 10000)

    def test_a_saved_tie_survives_a_quiet_week_and_votes_replace_it(self):
        quiet = Cfg()
        sessions = [core.scan_session(p, ["alpha-x"]) for p in (quiet.dir / "projects").glob("*/*.jsonl")]
        self.assertEqual(core.resolve_sockets(sessions, {"uds:/q.sock": "alpha-x"}), {"uds:/q.sock": "alpha-x"})
        c = Cfg()
        seed(c, sock="uds:/q.sock", track="beta-y")
        sessions = [core.scan_session(p, ["alpha-x", "beta-y"]) for p in (c.dir / "projects").glob("*/*.jsonl")]
        self.assertEqual(core.resolve_sockets(sessions, {"uds:/q.sock": "alpha-x"})["uds:/q.sock"], "beta-y")

    def test_the_last_message_of_a_session_is_counted(self):
        c = Cfg()
        sock = "uds:/run/cc-socks/1.sock"
        w = "Boss dispatch from A, track `alpha-x`."
        c.goal("alpha-x")
        c.worker(NOW - DAY, [(NOW - DAY, sock, w), (NOW - DAY + 10, sock, w)], cost=100)
        # the session now ends on its own last assistant message, with no result after it
        path = next(p for p in (c.dir / "projects" / "p").glob("wrk*.jsonl"))
        with open(path, "a") as f:
            f.write(json.dumps(dict(type="assistant", timestamp=iso(NOW - DAY + 1800), message=dict(
                id="last", usage=dict(input_tokens=900000, output_tokens=0), content=[]))) + "\n")
        c.boss("alpha-x", [], NOW - DAY)
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 900100)

    def test_malformed_lines_are_skipped_not_fatal(self):
        c = Cfg()
        seed(c)
        path = next(p for p in (c.dir / "projects" / "p").glob("wrk*.jsonl"))
        with open(path, "a") as f:
            for bad in ('[1, 2]', '{"type": "assistant", "timestamp": "bogus"}',
                        '{"type": "assistant", "timestamp": "%s", "message": "str"}' % iso(NOW - 3600),
                        '{"type": "assistant", "timestamp": "%s", "message": {"content": ["x"]}}' % iso(NOW - 3000)):
                f.write(bad + "\n")
        rec = core.scan_session(path, ["alpha-x"])
        self.assertGreaterEqual(rec["skipped"], 3)
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 5000)

    def test_malformed_subagent_lines_are_skipped_not_fatal(self):
        c = Cfg()
        seed(c)
        path = next(p for p in (c.dir / "projects" / "p").glob("wrk*.jsonl"))
        sub = path.with_suffix("") / "subagents"
        sub.mkdir(parents=True)
        good = dict(type="assistant", timestamp=iso(NOW - 3600),
                    message=dict(id="m1", usage=dict(input_tokens="oops", output_tokens=5)))
        (sub / "a.jsonl").write_text("\n".join(["null", "5", '{"type": "assistant", "timestamp": "bogus"}',
                                                json.dumps(good)]) + "\n")
        rec = core.scan_session(path, ["alpha-x"])
        self.assertGreaterEqual(rec["skipped"], 3)
        self.assertEqual(len(rec["subs"]), 1)
        self.assertEqual(rec["subs"][0]["cost"], 25)       # "oops" input counts 0; 5 output tokens at weight 5

    def test_tokens_outside_the_window_are_not_counted(self):
        c = Cfg()
        seed(c, at=NOW - 20 * DAY)
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"], {})


class AttributionByName(unittest.TestCase):
    def test_a_worker_the_boss_wrote_to_by_name_counts_without_a_dispatch(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira")])
        idx, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 7000)

    def test_a_worker_that_wrote_to_the_boss_counts_by_the_name_it_started_with(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [(NOW - DAY + 600, "uds:/run/cc-socks/m.sock", "done")], NOW - DAY)
        path = next(p for p in (c.dir / "projects" / "p").glob("boss*.jsonl"))
        text = path.read_text().replace('from-name=\\"x\\"', 'from-name=\\"Mira\\"')
        path.write_text(text)
        idx, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 7000)
        self.assertEqual(wk["coverage"], dict(messages=1, outside=0, share=0.0))

    def test_a_reused_name_matches_only_the_session_alive_at_the_message(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 3 * DAY, [], cost=900, name="Mira", until=NOW - 3 * DAY + 3600)
        c.worker(NOW - DAY, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 7000)

    def test_a_name_reused_inside_the_slack_counts_only_one_session(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY - 3600, [], cost=900, name="Mira", until=NOW - DAY + 30)
        c.worker(NOW - DAY + 60, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY - 3600, sends=[(NOW - DAY + 45, "Mira")], until=NOW - DAY + 3600)
        idx, _, _ = week(c.dir)
        self.assertEqual(len({s["sid"] for s, _, _ in idx.workers["alpha-x"]}), 1)

    def test_a_recipient_with_a_session_ref_still_matches_the_name(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira [ab12]")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 7000)

    def twins(self, to, listing=None):
        """Two live workers named Mira; the older one (cost 900) knows its ref when `listing` is given."""
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], cost=900, name="Mira", until=NOW - DAY + 3600,
                 listing=[(NOW - DAY + 5, listing)] if listing else ())
        c.worker(NOW - DAY + 30, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, to)], until=NOW - DAY + 3600)
        _, wk, _ = week(c.dir)
        return wk["tracks"].get("alpha-x", {"tokens": {"build": 0}})["tokens"]["build"]

    def test_a_ref_picks_the_session_that_holds_it_among_two_live_ones(self):
        mine = "This session is Mira [ab12cd] \u2014 the name other sessions use to message it.\n\nPeer sessions (1):"
        self.assertEqual(self.twins("Mira [ab12cd]", mine), 900)

    def test_a_ref_that_cannot_decide_between_two_live_ones_attributes_none(self):
        self.assertEqual(self.twins("Mira [ab12cd]"), 0)

    def test_a_ref_held_by_the_other_session_is_not_attributed_to_this_one(self):
        mine = "This session is Mira [ab12cd] \u2014 the name other sessions use to message it.\n\nPeer sessions (1):"
        self.assertEqual(self.twins("Mira [ffffff]", mine), 0)

    def test_a_ref_send_keeps_the_session_alive_when_the_other_is_only_inside_the_slack(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY - 3600, [], cost=900, name="Mira", until=NOW - DAY + 30)
        c.worker(NOW - DAY + 60, [], cost=7000, name="Mira", until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY - 3600, sends=[(NOW - DAY + 100, "Mira [ab12cd]")], until=NOW - DAY + 3600)
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 7000)

    def test_a_lone_session_that_holds_another_ref_is_not_attributed(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], cost=7000, name="Mira", until=NOW - DAY + 3600,
                 listing=[(NOW - DAY + 5, "This session is Mira [ab12cd] \u2014 x")])
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira [ffffff]")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 0)

    def test_a_session_dispatched_by_socket_is_not_counted_twice(self):
        c = Cfg()
        sock = "uds:/run/cc-socks/1.sock"
        w = "Boss dispatch from A, track `alpha-x`."
        c.goal("alpha-x")
        c.worker(NOW - DAY, [(NOW - DAY, sock, w), (NOW - DAY + 120, sock, w)], cost=5000, name="Mira",
                 until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 5000)

    def test_a_name_in_another_tracks_window_goes_to_that_track(self):
        c = Cfg()
        c.goal("alpha-x"); c.goal("beta-y")
        c.worker(NOW - DAY, [], cost=7000, name="Mira", until=NOW - DAY + 7200)
        c.boss("beta-y", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["beta-y"]["tokens"]["build"], 7000)
        self.assertNotIn("alpha-x", wk["tracks"])

    def test_a_session_without_a_recorded_name_is_not_guessed(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], cost=7000, until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Mira")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["tracks"]["alpha-x"]["tokens"]["build"], 0)


class FinishedTrack(unittest.TestCase):
    def finished(self, status="met", commit=True):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 2 * DAY, [], cost=7000, name="Mira", until=NOW - 2 * DAY + 3600,
                 cmds=[(NOW - 2 * DAY + 1800, "git commit -m 'Ticket 3 done'")] if commit else [])
        c.boss("alpha-x", [], NOW - 2 * DAY, sends=[(NOW - 2 * DAY + 60, "Mira")], until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 7200, "boss-goal status alpha-x %s 'all ticked'" % status)])
        return week(c.dir)

    def test_the_track_ends_at_the_goal_mark_not_at_the_last_boss_record(self):
        idx, wk, _ = self.finished()
        self.assertAlmostEqual(idx.cut["alpha-x"], NOW - 2 * DAY + 7200 + core.CUT_GRACE_S, delta=1)
        self.assertAlmostEqual(wk["tracks"]["alpha-x"]["wall_s"], 7200 + core.CUT_GRACE_S, delta=1)

    def test_a_done_commit_after_the_mark_moves_the_end_later(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 2 * DAY, [], name="Mira", until=NOW - 2 * DAY + 20000,
                 cmds=[(NOW - 2 * DAY + 9000, "git commit -m 'Ticket 9 done'")])
        c.boss("alpha-x", [], NOW - 2 * DAY, sends=[(NOW - 2 * DAY + 60, "Mira")], until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 7200, "boss-goal status alpha-x met 'x'")])
        idx, _, _ = week(c.dir)
        self.assertAlmostEqual(idx.cut["alpha-x"], NOW - 2 * DAY + 9000 + core.CUT_GRACE_S, delta=1)

    def test_a_failed_met_command_does_not_cut_the_track(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 2 * DAY, [], name="Mira", until=NOW - 2 * DAY + 20000)
        c.boss("alpha-x", [], NOW - 2 * DAY, sends=[(NOW - 2 * DAY + 60, "Mira")], until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 7200, "boss-goal status alpha-x met", False)])
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_a_succeeding_met_command_cuts_the_track(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 2 * DAY, [], name="Mira", until=NOW - 2 * DAY + 20000)
        c.boss("alpha-x", [], NOW - 2 * DAY, sends=[(NOW - 2 * DAY + 60, "Mira")], until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 7000, "boss-goal status alpha-x met", False),
                     (NOW - 2 * DAY + 7200, "boss-goal status alpha-x met 'all ticked'")])
        idx, _, _ = week(c.dir)
        self.assertAlmostEqual(idx.cut["alpha-x"], NOW - 2 * DAY + 7200 + core.CUT_GRACE_S, delta=1)

    def test_a_track_not_marked_met_runs_to_the_end_of_its_boss(self):
        idx, wk, _ = self.finished(status="open")
        self.assertNotIn("alpha-x", idx.cut)
        self.assertGreater(wk["tracks"]["alpha-x"]["wall_s"], DAY * 0.9)

    def test_a_reopened_track_is_not_cut(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - 2 * DAY, until=NOW - DAY, cmds=[
            (NOW - 2 * DAY + 100, "boss-goal status alpha-x met 'x'"),
            (NOW - 2 * DAY + 200, "boss-goal status alpha-x open 'more'")])
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_a_grep_for_the_command_is_not_a_mark(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - 2 * DAY, until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 100, "grep 'boss-goal status alpha-x met' notes.md")])
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_a_search_or_quoted_text_is_not_a_mark_or_a_done_commit(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 2 * DAY, [], cost=7000, name="Mira", until=NOW - 2 * DAY + 3600,
                 cmds=[(NOW - 2 * DAY + 1800, "echo \"git commit -m 'Ticket 3 done'\"")])
        c.boss("alpha-x", [], NOW - 2 * DAY, sends=[(NOW - 2 * DAY + 60, "Mira")], until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 100, "git grep 'boss-goal status alpha-x met'"),
                     (NOW - 2 * DAY + 200, "echo 'boss-goal status alpha-x met x'")])
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_a_comment_line_is_not_a_mark(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - 2 * DAY, until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 100, "git status\n# boss-goal status alpha-x met x")])
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_an_inline_comment_or_heredoc_body_is_not_a_mark(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - 2 * DAY, until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 100, "git status # boss-goal status alpha-x met x"),
                     (NOW - 2 * DAY + 200, "cat <<'EOF'\nboss-goal status alpha-x met x\nEOF")])
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_a_mark_after_a_heredoc_in_the_same_command_counts(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - 2 * DAY, until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 100, "cat <<'EOF'\nnote\nEOF\nboss-goal status alpha-x met x")])
        idx, _, _ = week(c.dir)
        self.assertIn("alpha-x", idx.cut)

    def test_a_real_mark_after_a_search_in_the_same_command_still_counts(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - 2 * DAY, until=NOW - DAY,
               cmds=[(NOW - 2 * DAY + 100, "grep 'boss-goal status alpha-x met' n; boss-goal status alpha-x met 'x'")])
        idx, _, _ = week(c.dir)
        self.assertIn("alpha-x", idx.cut)

    def test_a_workers_mark_does_not_cut_the_track(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - 2 * DAY, [], cost=7000, name="Mira", until=NOW - 2 * DAY + 3600,
                 cmds=[(NOW - 2 * DAY + 100, "boss-goal status alpha-x met 'x'")])
        c.boss("alpha-x", [], NOW - 2 * DAY, sends=[(NOW - 2 * DAY + 60, "Mira")], until=NOW - DAY)
        idx, _, _ = week(c.dir)
        self.assertNotIn("alpha-x", idx.cut)

    def test_a_worker_message_after_the_end_is_not_outside_activity(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [(NOW - DAY, "uds:/run/cc-socks/z.sock", "late")], NOW - 2 * DAY, until=NOW - DAY + 1,
               cmds=[(NOW - 2 * DAY + 100, "boss-goal status alpha-x met 'x'")])
        _, wk, _ = week(c.dir)
        self.assertEqual(wk["coverage"]["messages"], 0)


class Coverage(unittest.TestCase):
    def test_a_worker_message_with_no_tracked_worker_is_counted_outside(self):
        c = Cfg()
        seed(c)
        # a worker nobody dispatched through the socket speaks to the boss a day later
        c.boss("alpha-x", [(NOW - 12 * 3600, "uds:/run/cc-socks/ghost.sock", "ping")], NOW - 13 * 3600)
        _, wk, _ = week(c.dir)
        cov = wk["coverage"]
        self.assertEqual((cov["messages"], cov["outside"]), (2, 1))
        self.assertAlmostEqual(cov["share"], 0.5)

    def test_per_track_coverage_is_callable(self):
        c = Cfg()
        seed(c)
        idx, _, _ = week(c.dir)
        self.assertEqual(core.coverage(idx, "alpha-x", NOW - 7 * DAY, NOW), dict(messages=1, outside=0))


class CoverageMerge(unittest.TestCase):
    def test_a_long_early_stretch_still_covers_after_many_short_ones(self):
        long_seg = (1000, 90000, "llm")
        shorts = [(2000 + 10 * i, 2005 + 10 * i, "tools") for i in range(200)]
        s = dict(segs=[long_seg] + shorts)
        idx = core.Index([], {}, {})
        idx.workers["alpha-x"] = [(s, 0, 100000)]
        idx.worker_msgs["alpha-x"] = [50000, 150000]
        self.assertEqual(core.coverage(idx, "alpha-x", 0, 200000), dict(messages=2, outside=1))


class Measures(unittest.TestCase):
    def test_asks_per_day_and_ci_waits(self):
        c = Cfg()
        sock = "uds:/run/cc-socks/1.sock"
        c.worker(NOW - DAY, [(NOW - DAY, sock, "Boss dispatch from A, track `alpha-x`."),
                             (NOW - DAY + 5, sock, "Boss dispatch from A, track `alpha-x`.")],
                 bash="gh run watch 123")
        c.boss("alpha-x", [], NOW - DAY, asks=7)
        idx, _, _ = week(c.dir)
        m = core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW)
        self.assertEqual(m["asks"], 7)
        self.assertEqual(m["asks_per_day"], 1.0)
        self.assertEqual(m["ci_waits"], 1)
        self.assertGreaterEqual(m["ci_s"], 590)


class ConciergeQuestions(unittest.TestCase):
    """The concierge asks the owner for the boss; it is a worker session, not a boss."""

    def test_a_concierge_that_asks_three_questions_counts_three(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [(NOW - DAY + 20, "uds:/run/cc-socks/boss.sock", "ASK q1: which?")], name="Pia", asks=3, until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Pia")], until=NOW - DAY + 3600)
        idx, _, _ = week(c.dir)
        self.assertEqual(core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW)["asks"], 3)

    def test_a_question_the_boss_asked_itself_counts_once_beside_the_concierge(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [(NOW - DAY + 20, "uds:/run/cc-socks/boss.sock", "ASK q1: which?")], name="Pia", asks=3, until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, asks=2, sends=[(NOW - DAY + 30, "Pia")], until=NOW - DAY + 3600)
        idx, _, _ = week(c.dir)
        m = core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW)
        self.assertEqual(m["asks"], 5)

    def test_a_question_the_guard_refused_is_not_counted_again_when_the_concierge_asks_it(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [(NOW - DAY + 20, "uds:/run/cc-socks/boss.sock", "ASK q1: which?")], name="Pia", asks=1, until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, refused=1, sends=[(NOW - DAY + 30, "Pia")], until=NOW - DAY + 3600)
        idx, _, _ = week(c.dir)
        self.assertEqual(core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW)["asks"], 1)

    def test_a_question_the_owner_dismissed_still_counts(self):
        c = Cfg()
        c.goal("alpha-x")
        c.boss("alpha-x", [], NOW - DAY, asks=1, until=NOW - DAY + 3600)
        p = c.dir / "projects" / "p"
        f = next(p.glob("boss*.jsonl"))
        lines = [json.loads(l) for l in f.read_text().splitlines()]
        for r in lines:
            for b in (r.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result": b["is_error"] = True; b["content"] = "rejected"
        f.write_text("".join(json.dumps(r) + "\n" for r in lines))
        idx, _, _ = week(c.dir)
        self.assertEqual(core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW)["asks"], 1)

    def test_a_named_session_that_is_not_the_concierge_is_not_an_asker(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [], name="Tove", asks=4, until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 30, "Tove")], until=NOW - DAY + 3600)
        idx, _, _ = week(c.dir)
        self.assertEqual(core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW)["asks"], 0)

    def test_a_concierge_question_outside_the_window_is_not_counted(self):
        c = Cfg()
        c.goal("alpha-x")
        c.worker(NOW - DAY, [(NOW - DAY + 20, "uds:/run/cc-socks/boss.sock", "ASK q1: which?")], name="Pia", asks=3, until=NOW - DAY + 3600)
        c.boss("alpha-x", [], NOW - DAY, sends=[(NOW - DAY + 60, "Pia")], until=NOW - DAY + 3600)
        idx, _, _ = week(c.dir)
        self.assertEqual(core.measure_track(idx, "alpha-x", NOW - 7 * DAY, NOW - DAY + 50)["asks"], 0)


class Verdict(unittest.TestCase):
    def track(self, tokens, build=1.0, ci=0.0, asks=0, msgs=10, outside=0):
        t = int(tokens)
        return dict(budget_share=0.1, total_tokens=t, asks=asks,
                    tokens=dict(build=int(t * build), fix=int(t * (1 - build)), sub_rev=0, sub_oth=0, boss=0),
                    worker_s=dict(ci=ci * 1000, llm=(1 - ci) * 1000), coverage=dict(messages=msgs, outside=outside))

    def fake(self, tracks, start=7 * DAY, msgs=10, outside=0):
        return dict(start=start, end=start + 7 * DAY, tracks=tracks, total_tokens=sum(t["total_tokens"] for t in tracks.values()),
                    coverage=dict(messages=msgs, outside=outside, share=outside / msgs if msgs else None))

    def pair(self, before, after):
        prev = self.fake(before, start=0)
        return core.judge(self.fake(after), prev)

    def test_a_track_that_changes_how_it_spends_is_flagged(self):
        fails, flags = self.pair({"alpha-x": self.track(200e6, build=0.8)}, {"alpha-x": self.track(200e6, build=0.5)})
        self.assertEqual(fails, [])
        self.assertEqual(len(flags), 1, flags)
        self.assertIn("alpha-x: build 50% against 80%", flags[0])

    def test_ci_wait_share_and_questions_are_phases_too(self):
        _, flags = self.pair({"alpha-x": self.track(200e6, ci=0.1, asks=1)}, {"alpha-x": self.track(200e6, ci=0.4, asks=8)})
        self.assertIn("ci wait 40% against 10%", flags[0])
        self.assertIn("questions 4.0 against 0.5 per 100 M tokens", flags[0])

    def test_the_fleet_share_doubling_alone_never_speaks(self):
        before = {"alpha-x": self.track(200e6), "beta-y": self.track(800e6)}
        after = {"alpha-x": self.track(400e6), "beta-y": self.track(600e6)}
        self.assertEqual(self.pair(before, after), ([], []))

    def test_a_track_below_the_floor_in_either_week_is_not_compared(self):
        small, big = self.track(20e6, build=0.9), self.track(200e6, build=0.2)
        self.assertEqual(self.pair({"alpha-x": small}, {"alpha-x": big}), ([], []))
        self.assertEqual(self.pair({"alpha-x": big}, {"alpha-x": small}), ([], []))

    def test_a_track_new_this_week_or_a_gap_in_the_weeks_is_not_compared(self):
        big = self.track(200e6, build=0.2)
        self.assertEqual(self.pair({}, {"alpha-x": big}), ([], []))
        gap = self.fake({"alpha-x": self.track(200e6, build=0.9)}, start=0)
        self.assertEqual(core.judge(self.fake({"alpha-x": big}, start=21 * DAY), gap), ([], []))

    def test_an_anomaly_on_a_low_coverage_track_says_so(self):
        _, flags = self.pair({"alpha-x": self.track(200e6, build=0.9)},
                             {"alpha-x": self.track(200e6, build=0.5, msgs=30, outside=12)})
        self.assertIn("low coverage: 12 of 30", flags[0])
        _, flags = self.pair({"alpha-x": self.track(200e6, build=0.9)}, {"alpha-x": self.track(200e6, build=0.5, msgs=30, outside=1)})
        self.assertNotIn("low coverage", flags[0])

    def test_the_week_before_is_the_one_nearest_even_after_a_late_or_manual_run(self):
        mon = self.fake({}, start=0)
        late = dict(self.fake({}, start=9 * 3600), end=7 * DAY + 9 * 3600)         # ran Tuesday morning
        extra = dict(self.fake({}, start=2 * DAY), end=9 * DAY)                    # a manual run on Wednesday
        week = self.fake({}, start=7 * DAY)
        week["end"] = 14 * DAY
        self.assertIs(core.pick_previous([mon, extra], week), mon)
        self.assertIs(core.pick_previous([late], week), late)

    def test_no_sessions_and_no_messages_are_failures_never_a_pass(self):
        fails, _ = core.judge(self.fake({}, msgs=0), None)
        self.assertEqual(len(fails), 2)
        fails, _ = core.judge(self.fake({"alpha-x": self.track(1e6)}, msgs=0), None)
        self.assertEqual(len(fails), 1)

    def test_a_week_with_no_socket_ties_fails_instead_of_becoming_a_baseline(self):
        week = self.fake({"alpha-x": self.track(1e6)}, msgs=100, outside=95)
        fails, _ = core.judge(week, None)
        self.assertEqual(len(fails), 1)
        self.assertIn("socket lookup", fails[0])

    def test_the_uncovered_failure_has_a_floor_and_a_boundary_at_90_percent(self):
        def fails(msgs, outside):
            return core.judge(self.fake({"alpha-x": self.track(1e6)}, msgs=msgs, outside=outside), None)[0]
        self.assertEqual(fails(10, 9), [])                   # exactly 90%: healthy side
        self.assertEqual(len(fails(100, 91)), 1)             # just over
        self.assertEqual(fails(3, 3), [])                    # all outside, but too few messages to say
        self.assertEqual(len(fails(core.MIN_MESSAGES, core.MIN_MESSAGES)), 1)

    def test_busy_week_coverage_is_in_the_report_not_a_trigger(self):
        week = self.fake({"alpha-x": self.track(200e6, msgs=100, outside=35)}, msgs=100, outside=35)
        week["tracks"]["alpha-x"].update(wall_s=3600, states={k: 0 for k in core.STATES}, asks_per_day=0, ci_waits=0, ci_s=0)
        self.assertEqual(core.judge(week, None), ([], []))
        self.assertIn("35/100", core.render(week, "x", [], []))


class UnsentAlert(unittest.TestCase):
    """An alert Slack did not take is kept and sent with the next run; the week stays a baseline."""

    def week(self, end, build):
        m = dict(budget_share=0.1, total_tokens=200_000_000, asks=0, wall_s=3600, asks_per_day=0, ci_waits=0, ci_s=0,
                 states={k: 0 for k in core.STATES}, tokens=dict.fromkeys(core.PHASES, 0),
                 worker_s=dict(ci=0, llm=1000), coverage=dict(messages=10, outside=0))
        m["tokens"].update(build=int(2e8 * build), fix=int(2e8 * (1 - build)))
        return dict(start=end - 7 * DAY, end=end, tracks={"alpha-x": m}, total_tokens=200_000_000,
                    coverage=dict(messages=10, outside=0, share=0.0))

    def run_week(self, c, end, build, sends):
        """core.run for one window; `sends` holds the Slack answers in turn. Returns (rc, texts it tried)."""
        tried = []

        def fake_alert(text, dry):
            tried.append(text)
            return sends.pop(0)
        old = core.measure_window, core.alert
        core.measure_window = lambda idx, start, end_: self.week(end_, build)
        core.alert = fake_alert
        try:
            rc, _ = core.run(c.dir, end, 1, False)
        finally:
            core.measure_window, core.alert = old
        return rc, tried

    def state(self, c):
        return json.loads((c.dir / "routines" / "state" / "boss-efficiency.json").read_text())

    def test_a_flagged_week_whose_alert_failed_is_sent_with_the_next_run(self):
        c = Cfg()
        c.goal("alpha-x")
        self.assertEqual(self.run_week(c, NOW, 0.8, []), (0, []))
        rc, tried = self.run_week(c, NOW + 7 * DAY, 0.5, [False])                # Slack is down
        self.assertEqual((rc, len(tried)), (2, 1))
        self.assertIn("build 50% against 80%", tried[0])
        self.assertEqual(len(self.state(c)["unsent"]), 1)
        rc, tried = self.run_week(c, NOW + 14 * DAY, 0.5, [True, True])           # the change persists, Slack is back
        self.assertEqual(rc, 0)
        self.assertEqual(len(tried), 1, tried)                                    # the old one; 0.5 against 0.5 says nothing new
        self.assertIn("build 50% against 80%", tried[0])
        self.assertEqual(self.state(c)["unsent"], [])

    def test_a_rerun_of_the_week_that_gets_through_drops_its_unsent_entry(self):
        c = Cfg()
        c.goal("alpha-x")
        self.run_week(c, NOW, 0.8, [])
        self.run_week(c, NOW + 7 * DAY, 0.5, [False])
        rc, tried = self.run_week(c, NOW + 7 * DAY, 0.5, [True, True])           # the same week again
        self.assertEqual(self.state(c)["unsent"], [])
        self.assertEqual(self.run_week(c, NOW + 14 * DAY, 0.5, [])[1], [])        # nothing left to repeat

    def test_an_unsent_alert_keeps_failing_the_run_until_it_goes_out(self):
        c = Cfg()
        c.goal("alpha-x")
        self.run_week(c, NOW, 0.8, [])
        self.run_week(c, NOW + 7 * DAY, 0.5, [False])
        rc, _ = self.run_week(c, NOW + 14 * DAY, 0.5, [False])
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.state(c)["unsent"]), 1)

    def test_a_delivered_alert_leaves_nothing_to_resend(self):
        c = Cfg()
        c.goal("alpha-x")
        self.run_week(c, NOW, 0.8, [])
        self.assertEqual(self.run_week(c, NOW + 7 * DAY, 0.5, [True])[0], 0)
        self.assertEqual(self.state(c).get("unsent", []), [])


class MissedRun(unittest.TestCase):
    """The body alerts when it cannot run the week at all, and fails visibly when Slack is out too."""

    def setUp(self):
        self.c = Cfg()
        self.got = []
        got = self.got

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok": true}')

            def log_message(self, *a): pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.slack = Path(tempfile.mkdtemp()) / "slack.env"
        self.slack.write_text("SLACK_BOT_TOKEN=tok\nSLACK_CHANNEL_ID=C1\n")

    def env(self, **kw):
        e = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.c.dir), DRY_RUN="", BOSS_SLACK_ENV=str(self.slack),
                 BOSS_SLACK_API="http://127.0.0.1:%d/" % self.srv.server_port, BOSS_EFFICIENCY_LOCK_WAIT="1")
        e.update(kw)
        return e

    def log(self):
        return (self.c.dir / "routines" / "logs" / "boss-efficiency.log").read_text()

    def hold_lock(self):
        import fcntl
        held = open(self.c.dir / "pm" / ".boss-efficiency-transcripts.lock", "w")
        fcntl.flock(held, fcntl.LOCK_EX)
        self.addCleanup(held.close)

    def slow_nice(self):
        """A `nice` that outlasts the cap, so the body's `timeout` kills it."""
        d = Path(tempfile.mkdtemp())
        (d / "nice").write_text("#!/bin/sh\nexec sleep 30\n")
        (d / "nice").chmod(0o755)
        return dict(PATH="%s:%s" % (d, os.environ["PATH"]), BOSS_EFFICIENCY_TIMEOUT="1")

    def test_a_lock_that_is_never_free_sends_an_alert_and_still_fails(self):
        self.hold_lock()
        r = subprocess.run([str(BODY)], env=self.env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(len(self.got), 1, self.got)
        self.assertIn("lock", urllib.parse.unquote_plus(self.got[0]))
        self.assertNotIn("ALERT NOT SENT", self.log())

    def test_a_scan_killed_by_the_cap_sends_an_alert_and_still_fails(self):
        r = subprocess.run([str(BODY)], env=self.env(**self.slow_nice()), capture_output=True, text=True)
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertEqual(len(self.got), 1, self.got)
        self.assertIn("timed out", urllib.parse.unquote_plus(self.got[0]))

    def test_a_scan_that_ignores_the_first_signal_is_alerted_too(self):
        d = Path(tempfile.mkdtemp())
        (d / "nice").write_text("#!/bin/sh\ntrap '' TERM\nsleep 30\n")
        (d / "nice").chmod(0o755)
        r = subprocess.run([str(BODY)], env=self.env(PATH="%s:%s" % (d, os.environ["PATH"]), BOSS_EFFICIENCY_TIMEOUT="1",
                                                     BOSS_EFFICIENCY_KILL="1"), capture_output=True, text=True)
        self.assertEqual(r.returncode, 137, r.stdout + r.stderr)
        self.assertEqual(len(self.got), 1, self.got)
        self.assertIn("timed out", urllib.parse.unquote_plus(self.got[0]))

    def test_with_slack_unreachable_the_miss_is_logged_and_the_exit_is_distinct(self):
        self.hold_lock()
        r = subprocess.run([str(BODY)], env=self.env(BOSS_SLACK_ENV="/nonexistent/slack.env"), capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("ALERT NOT SENT", self.log())
        r = subprocess.run([str(BODY)], env=self.env(BOSS_SLACK_ENV="/nonexistent/slack.env", **self.slow_nice()),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_a_dry_run_alerts_nobody(self):
        self.hold_lock()
        r = subprocess.run([str(BODY)], env=self.env(DRY_RUN="1"), capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.got, [])
        self.assertIn("would alert", r.stdout)


class Usage(unittest.TestCase):
    def test_only_finite_numbers_of_zero_or_more_count(self):
        bad = dict(input_tokens=float("nan"), cache_read_input_tokens=float("inf"),
                   cache_creation_input_tokens=-5, output_tokens=True)
        self.assertEqual(core.usage(bad), dict(i=0, cw=0, cr=0, o=0))
        self.assertEqual(core.usage(dict(output_tokens=7, input_tokens=2.5)), dict(i=2.5, cw=0, cr=0, o=7))
        self.assertEqual(core.cost(core.usage(dict(output_tokens=10 ** 400))), 0)     # too big for a float: no OverflowError


class Alert(unittest.TestCase):
    def test_export_and_quoted_credentials_are_read(self):
        import http.server
        import threading
        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got.append((self.headers["Authorization"], self.rfile.read(int(self.headers["Content-Length"])).decode()))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok": true}')

            def log_message(self, *a): pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        envf = Path(tempfile.mkdtemp()) / "slack.env"
        envf.write_text('export SLACK_BOT_TOKEN="tok"\nSLACK_CHANNEL_ID=C1\n')
        old = {k: os.environ.get(k) for k in ("BOSS_SLACK_ENV", "BOSS_SLACK_API")}
        os.environ.update(BOSS_SLACK_ENV=str(envf), BOSS_SLACK_API="http://127.0.0.1:%d/" % srv.server_port)
        try:
            self.assertTrue(core.alert("alpha-x: build 50% against 80%", dry=False))
        finally:
            for k, v in old.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
        self.assertEqual(got[0][0], "Bearer tok")
        self.assertIn("channel=C1", got[0][1])
        self.assertNotIn("blocked", got[0][1])

    def test_a_missing_credentials_file_is_reported_not_raised(self):
        old = os.environ.get("BOSS_SLACK_ENV")
        os.environ["BOSS_SLACK_ENV"] = "/nonexistent/slack.env"
        try:
            self.assertFalse(core.alert("numbers", dry=False))
        finally:
            if old is None: del os.environ["BOSS_SLACK_ENV"]
            else: os.environ["BOSS_SLACK_ENV"] = old

    def test_the_alert_text_is_numbers_and_track_names(self):
        c = Cfg()
        seed(c)
        c.session("txt", NOW - DAY, [(NOW - DAY, "uds:/s.sock", "SECRET client text")], 1000)
        r = subprocess.run([sys.executable, str(PLUGIN / "routines" / "boss_efficiency_core.py"), "--end", dt.datetime.fromtimestamp(NOW).isoformat()],
                           env=dict(os.environ, CLAUDE_CONFIG_DIR=str(c.dir), DRY_RUN="1"), capture_output=True, text=True)
        self.assertNotIn("SECRET", r.stdout + r.stderr)


class Run(unittest.TestCase):
    def env(self, c, **kw):
        e = dict(os.environ, CLAUDE_CONFIG_DIR=str(c.dir), DRY_RUN="", BOSS_SLACK_ENV="/nonexistent/slack.env")
        e.update(kw)
        return e

    def test_an_empty_config_fails_with_exit_2_and_says_so(self):
        c = Cfg()
        r = subprocess.run([sys.executable, str(PLUGIN / "routines" / "boss_efficiency_core.py")],
                           env=self.env(c), capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_outputs_land_under_the_config_dir_and_not_in_the_plugin(self):
        c = Cfg()
        seed(c)
        before = {p for p in (PLUGIN / "routines").rglob("*") if "__pycache__" not in str(p)}
        r = subprocess.run([sys.executable, str(PLUGIN / "routines" / "boss_efficiency_core.py"),
                            "--end", dt.datetime.fromtimestamp(NOW).isoformat()],
                           env=self.env(c), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((c.dir / "routines" / "state" / "boss-efficiency.json").exists())
        self.assertTrue(list((c.dir / "routines" / "reports").glob("boss-efficiency-*.md")))
        after = {p for p in (PLUGIN / "routines").rglob("*") if "__pycache__" not in str(p)}
        self.assertEqual(before, after)

    def test_it_refuses_to_write_inside_the_plugin(self):
        with self.assertRaises(SystemExit):
            core.write_outputs(PLUGIN, "x", {}, "", {})

    def test_the_body_waits_on_the_transcripts_lock_and_fails_when_it_cannot_take_it(self):
        import fcntl
        c = Cfg()
        with open(c.dir / "pm" / ".boss-efficiency-transcripts.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            r = subprocess.run([str(BODY)], env=self.env(c, BOSS_EFFICIENCY_LOCK_WAIT="1", DRY_RUN="1"),
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("run skipped", r.stdout)
        self.assertIn("nice -n 19", BODY.read_text())
        self.assertIn("ionice -c2 -n7", BODY.read_text())

    def test_a_dry_run_of_the_body_makes_no_directory_and_no_log(self):
        c = Cfg()
        seed(c)
        r = subprocess.run([str(BODY), "--end", dt.datetime.fromtimestamp(NOW).isoformat()],
                           env=self.env(c, DRY_RUN="1"), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((c.dir / "routines").exists())

    def test_a_rerun_of_one_week_replaces_it_in_history(self):
        c = Cfg()
        seed(c)
        for end in (NOW, NOW + 3600):                         # the same calendar week, two runs
            core.run(c.dir, end, 1, False)
        weeks = json.loads((c.dir / "routines" / "state" / "boss-efficiency.json").read_text())["weeks"]
        self.assertEqual(len(weeks), 1)

    def test_uninstall_removes_the_timer_too(self):
        text = (PLUGIN / "uninstall.sh").read_text()
        self.assertIn("disable --now boss-ladder.timer boss-workers-watch.timer boss-efficiency.timer", text)
        self.assertIn("boss-efficiency.{service,timer}", text)

    def test_only_dry_run_1_is_a_dry_run_in_the_body_and_the_core(self):
        self.assertIn('if [ "${DRY_RUN:-}" != 1 ]; then', BODY.read_text())
        self.assertIn('os.environ.get("DRY_RUN") == "1"', (PLUGIN / "routines" / "boss_efficiency_core.py").read_text())

    def test_the_routine_calls_no_model(self):
        for f in (BODY, PLUGIN / "routines" / "boss_efficiency_core.py"):
            text = f.read_text()
            self.assertNotIn("claude -p", text)
            self.assertNotIn("anthropic", text.lower())

    def test_sessions_with_no_worker_message_fail_the_run(self):
        c = Cfg()
        c.boss("alpha-x", [], NOW - DAY)
        c.goal("alpha-x")
        rec = c.dir / "alert"
        rec.write_text("x")
        r = subprocess.run([sys.executable, str(PLUGIN / "routines" / "boss_efficiency_core.py"), "--end", dt.datetime.fromtimestamp(NOW).isoformat()],
                           env=self.env(c, BOSS_SLACK_ENV=str(rec)), capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
