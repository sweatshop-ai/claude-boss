#!/usr/bin/env python3
"""Tests for boss-guard.py, the PreToolUse guard on boss sessions.

Run: python3 skills/boss/test_boss_guard.py

Every test runs the hook the way the harness does — as a process, JSON on
stdin — against a throwaway CLAUDE_CONFIG_DIR. Nothing here touches the real
~/.claude/pm.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "boss-guard.py"


class GuardCase(unittest.TestCase):
    """A boss session registered in a scratch config dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="boss-guard-test-")
        self.cfg = Path(self.tmp)
        self.markers = self.cfg / "pm" / ".boss-sessions"
        self.markers.mkdir(parents=True)
        self.sid = "11111111-2222-3333-4444-555555555555"
        (self.markers / self.sid).write_text("demo\n", encoding="utf-8")
        # `~/.claude/pm` in a command resolves under the scratch dir, and it exists
        (self.cfg / ".claude" / "pm").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fire(self, command="rm -rf build", tool="Bash", sid=None, tool_input=None):
        """One PreToolUse call. Returns the additionalContext, or '' if silent."""
        if tool_input is None:
            tool_input = ({"command": command} if tool == "Bash"
                          else {"file_path": command})
        payload = {
            "session_id": sid or self.sid,
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
        }
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), HOME=str(self.cfg))
        res = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        if not out:
            return ""
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def log_lines(self):
        f = self.cfg / "pm" / "boss-guard.log"
        if not f.exists():
            return []
        return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


class Deduplication(GuardCase):
    """2,589 firings over 14 days repeated one 330-character sentence."""

    def test_full_text_once_then_never_again(self):
        first = self.fire("rm -rf build")
        self.assertIn("is implementation work", first)
        self.assertIn("Dispatch it to a worker", first)

        second = self.fire("rm -rf dist")
        self.assertNotIn("Dispatch it to a worker", second,
                         "the full sentence repeated on the second firing")

    def test_every_firing_is_still_logged(self):
        for i in range(5):
            self.fire("touch f%d" % i)
        self.assertEqual(len(self.log_lines()), 5,
                         "the log is the evidence base and must stay complete")

    def test_a_runaway_is_still_visible(self):
        """Silence after one nudge hides a boss doing 725 of these."""
        said = [bool(self.fire("touch f%d" % i)) for i in range(1, 40)]
        # firings 2, 4, 8, 16, 32 speak; the rest are silent.
        spoke = [i + 1 for i, v in enumerate(said) if v]
        self.assertEqual(spoke, [1, 2, 4, 8, 16, 32])

    def test_the_repeat_is_a_count_not_the_sentence(self):
        self.fire("touch a")
        second = self.fire("touch b")
        self.assertNotIn("Dispatch it to a worker", second)
        self.assertIn("2nd", second)
        self.assertLess(len(second), 160, "the repeat must stay short")


class Scope(GuardCase):
    """What the guard must go on doing, dedup or not."""

    def test_each_session_gets_its_own_first_warning(self):
        other = "99999999-8888-7777-6666-555555555555"
        (self.markers / other).write_text("other\n", encoding="utf-8")
        self.fire("touch a")
        self.assertIn("Dispatch it to a worker", self.fire("touch b", sid=other),
                      "a second boss inherited the first one's counter")

    def test_a_session_with_no_marker_is_left_alone(self):
        self.assertEqual(self.fire("rm -rf /", sid="not-a-boss"), "")
        self.assertEqual(self.log_lines(), [])

    def test_allowed_commands_never_spend_the_budget(self):
        for _ in range(4):
            self.assertEqual(self.fire("gh pr list"), "")
        self.assertIn("Dispatch it to a worker", self.fire("touch x"),
                      "coordination calls consumed the one full warning")


class Precision(GuardCase):
    """1,227 of the 2,589 logged firings named a coordination tool.

    The guard was scolding the boss for running the boss's own commands.
    """

    def test_the_bosss_own_tools_are_coordination(self):
        for cmd in ("boss-goal next demo",
                    "${CLAUDE_PLUGIN_ROOT}/skills/boss/bin/boss-goal status demo",
                    "boss-start demo",
                    "/opt/whatever/claude-team/hooks/team-line abc --did x --n 0"):
            self.assertEqual(self.fire(cmd), "", "scolded for `%s`" % cmd)

    def test_a_cd_prefix_does_not_hide_an_allowed_command(self):
        self.assertEqual(self.fire("cd ${CLAUDE_PLUGIN_ROOT}/skills/boss/bin && ./boss-tracker list"), "")

    def test_a_variable_prefix_does_not_hide_an_allowed_command(self):
        self.assertEqual(self.fire("B=${CLAUDE_PLUGIN_ROOT}/skills/boss/bin; $B/boss-goal next demo"), "")

    def test_the_prefix_strip_does_not_wave_through_real_work(self):
        self.assertNotEqual("", self.fire("cd /repo && npm run build"))
        self.assertNotEqual("", self.fire("FOO=1 python3 train.py"))


class ExportPrefix(GuardCase):
    """A boss puts the plugin on its PATH first; 138 flagged calls in 14 days
    began with `export`, and the sessions' own lifecycle calls were among them."""

    def test_an_export_prefix_does_not_hide_an_allowed_command(self):
        for cmd in ('export PATH="/plugin/skills/boss:$PATH"; boss-lifecycle.sh list --mine',
                    'export PATH=/plugin/bin:$PATH && boss-goal next demo'):
            self.assertEqual(self.fire(cmd), "", "scolded for `%s`" % cmd)

    def test_an_export_prefix_does_not_wave_through_real_work(self):
        self.assertNotEqual("", self.fire('export PATH="/x:$PATH"; npm run build'))


class BashWritesToPm(GuardCase):
    """The tracker is the boss's own, by Edit or by shell. An Edit under pm/ was
    never flagged; the same line appended with `printf >>` was."""

    def test_appending_a_line_to_its_own_state_is_coordination(self):
        for cmd in ('echo "- 08:0xZ Hassan: PR 101 merged" >> ~/.claude/pm/action-list.md',
                    "printf '%s\\n' \"- a; b && c\" >> /home/x/.claude/pm/demo.md",
                    'cd /repo && echo done > ~/.claude/pm/demo.state',
                    "cat >> ~/.claude/pm/demo.md <<'EOF'\n- rm -rf build; it's fine\nEOF"):
            self.assertEqual(self.fire(cmd), "", "scolded for `%s`" % cmd)
        self.assertEqual(self.log_lines(), [])

    def test_a_write_to_the_config_dirs_own_pm_counts(self):
        self.assertEqual(self.fire('echo x >> %s/pm/demo.md' % self.cfg), "")

    def test_the_compound_calls_bosses_really_make_are_coordination(self):
        """Measured on 22 boss sessions: the bare write was 5 calls in 4,968.
        The tracker line arrives with its timestamp and the team-line call."""
        for cmd in ('cd ~/.claude/pm; S=$(date -u +%H:%MZ); echo "- $S Kasper: merged" >> action-list.md; '
                    "/x/hooks/team-line abc --did 'done; next' --n 0",
                    "printf '%s\\n' \"- 17:0xZ Farid\" >> ~/.claude/pm/a.md; /x/team-line abc --n 0 < /dev/null",
                    "cd ~/.claude/pm && printf '%s\\n' \"- x\" | /x/bin/boss-tracker append demo | tail -1",
                    "cd ~/.claude/pm && sed -i 's/a/b/' action-list.md",
                    "cd ~/.claude/pm && S=$(date -u +%H:%MZ) && cat >> a.md <<EOF\n- $S done\nEOF",
                    "cat >> ~/.claude/pm/a.md <<'EOF'\n- the $(literal) text\nEOF"):
            self.assertEqual(self.fire(cmd), "", "scolded for `%s`" % cmd)
        self.assertEqual(self.log_lines(), [])

    def test_real_work_beside_a_tracker_line_is_still_flagged(self):
        for cmd in ('cd ~/.claude/pm; echo x >> a.md; cd /repo && npm run build',
                    'cd /repo && echo x >> a.md',
                    "cd /repo && sed -i 's/a/b/' src/app.ts",
                    "cd /repo && python3 - <<'EOF'\nopen('a','w').write('x')\nEOF",
                    "cd ~/.claude/pm && python3 - <<'EOF'\nopen('/repo/src/app.ts','w').write('x')\nEOF",
                    "cd ~/.claude/pm && python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['make'])\nEOF",
                    "S=$(rm -rf build); echo x >> ~/.claude/pm/a.md",
                    'echo a || rm -rf build',
                    'echo a & rm -rf build',
                    '(echo a) ; rm -rf build'):
            before = len(self.log_lines())
            self.fire(cmd)
            self.assertEqual(len(self.log_lines()), before + 1, "not logged: `%s`" % cmd)

    def test_only_a_pure_write_counts(self):
        for cmd in ('echo x >> ~/.claude/pm/a.md; rm -rf build',
                    'echo x >> ~/.claude/pm/a.md && npm run build',
                    'npm run build >> ~/.claude/pm/build.log',
                    'echo x >> ~/.claude/pm/a.md\nrm -rf build',
                    'echo $(rm -rf build) >> ~/.claude/pm/a.md',
                    'echo `rm -rf build` >> ~/.claude/pm/a.md',
                    'echo x >> /repo/src/app.ts',
                    'echo x >> ~/.claude/pm/a.md >> /repo/src/app.ts',
                    'echo x | tee /repo/src/app.ts',
                    "cat >> ~/.claude/pm/a.md <<'EOF'\nbody\nEOF\nrm -rf build",
                    'echo "unterminated >> ~/.claude/pm/a.md'):
            before = len(self.log_lines())
            self.fire(cmd)
            self.assertEqual(len(self.log_lines()), before + 1, "not logged: `%s`" % cmd)


class ClassifierGaps(GuardCase):
    """Codex's six examples on the classifier. It warns and logs; it is no boundary.
    Where the text cannot be read with certainty the call counts as work."""

    def assertLogged(self, cmd):
        before = len(self.log_lines())
        self.fire(cmd)
        self.assertEqual(len(self.log_lines()), before + 1, "not logged: `%s`" % cmd)

    def assertQuiet(self, cmd):
        self.assertEqual(self.fire(cmd), "", "scolded for `%s`" % cmd)

    def test_a_sed_program_other_than_a_plain_substitution_is_work(self):
        for cmd in ("sed -i 'w /repo/src/app.ts' ~/.claude/pm/a.md",
                    "sed -i '1e rm -rf build' ~/.claude/pm/a.md",
                    "sed -i 's/a/b/w /repo/src/app.ts' ~/.claude/pm/a.md",
                    "sed -i 's/a/b/e' ~/.claude/pm/a.md"):
            self.assertLogged(cmd)

    def test_a_plain_substitution_is_still_coordination(self):
        self.assertQuiet("sed -i 's/a/b/g' ~/.claude/pm/a.md")
        self.assertQuiet("sed -i 's|a|b|' ~/.claude/pm/a.md")

    def test_a_heredoc_marker_in_a_comment_hides_nothing(self):
        self.assertLogged("echo x >> ~/.claude/pm/a.md # <<EOF\nnpm test\nEOF")
        self.assertLogged("echo '<<EOF' >> ~/.claude/pm/a.md\nnpm test\nEOF")

    def test_cat_reading_a_real_file_into_the_tracker_is_work(self):
        self.assertLogged("cat /repo/src/app.ts >> ~/.claude/pm/a.md")
        self.assertLogged("cat < /repo/src/app.ts >> ~/.claude/pm/a.md")
        self.assertQuiet("cat ~/.claude/pm/b.md >> ~/.claude/pm/a.md")

    def test_a_filter_after_a_pipe_takes_no_file_operands(self):
        self.assertLogged("echo x | head /repo/src/app.ts")
        self.assertLogged("echo x | head < /repo/src/app.ts")
        self.assertQuiet("cd ~/.claude/pm && printf '%s\\n' x | /x/bin/boss-tracker append demo | head -n 5")
        self.assertQuiet("echo x | cut -d , -f 2 | wc -l")
        self.assertLogged("echo x | wc -c /repo/src/app.ts")      # -c takes a value for head, tail and cut, not wc
        self.assertQuiet("echo x | head -c 5 | wc -c")

    def test_a_cd_that_fails_does_not_own_the_cwd(self):
        self.assertLogged("cd ~/.claude/pm/missing; echo x > src/app.ts")
        self.assertQuiet("cd ~/.claude/pm; echo x > a.md")
        self.assertLogged("cd ~/.claude/pm/missing && true; echo x > src/app.ts")

    def test_a_heredoc_with_the_redirect_after_the_marker_is_a_heredoc(self):
        self.assertQuiet("cat <<EOF >> ~/.claude/pm/a.md\n- rm -rf build; ok\nEOF")
        self.assertQuiet("cat <<'EOF' >> ~/.claude/pm/a.md\n- $(literal)\nEOF")
        self.assertLogged("cat <<EOF >> ~/.claude/pm/a.md\nbody\nEOF\nnpm test")
        self.assertLogged("cat <<EOF | sh\nnpm test\nEOF")
        self.assertLogged("cat <<EOF >> ~/.claude/pm/a.md; npm test\nbody\nEOF")


class StillFlagged(GuardCase):
    """Opus's bug hunt on PR 43: each of these passed unlogged on some version
    of the statement-by-statement check. An unlogged call costs more than a
    noisy one, since the log is the evidence."""

    def test_each_is_logged(self):
        for cmd in (
                # a prefix joined by && must not carry a call past the check of its statements
                'export PATH=/plugin/bin:$PATH && gh pr checkout 5 && npm test',
                'export PATH=/plugin/bin:$PATH; boss-goal next demo; cd /repo && npm run build',
                'export V=$(./build.sh); gh release create $V',
                'V=$(./build.sh) && gh release create $V',
                # a script's reach cannot be read from its text
                "cd ~/.claude/pm && python3 - <<'EOF'\nimport os\nopen(os.path.expanduser('~/x/a.ts'),'w')\nEOF",
                "cd ~/.claude/pm && python3 - <<'EOF'\nfrom pathlib import Path\n(Path.home()/'x').write_text('x')\nEOF",
                "cd ~/.claude/pm && python3 - <<'EOF'\nopen('../../x/a.ts','w')\nEOF",
                # an unquoted heredoc runs its substitutions
                'cat >> ~/.claude/pm/a.md <<EOF\n- $(npm test 2>&1 | tail -1)\nEOF',
                'cat >> ~/.claude/pm/a.md <<EOF\n`rm -rf build`\nEOF',
                # a herestring is no heredoc
                'echo a <<<EOF\nrm -rf build\nEOF',
                # redirects, wherever they sit
                'echo x | tail -1 > /repo/src/app.ts',
                'echo x >> ~/.claude/pm/a.md; date > /repo/src/app.ts',
                'echo x >> /repo/src/app.ts >> ~/.claude/pm/a.md',
                # after the first statement, a tool's name must be the whole name
                'echo x >> ~/.claude/pm/a.md; gh-deploy.sh',
                'echo x >> ~/.claude/pm/a.md; date.py --build',
                # sed: one own file, nothing else
                'sed -i s/a/b/ /repo/src/app.ts ~/.claude/pm/a.md',
                'sed -i s/a/b/ /repo/src/app.ts > ~/.claude/pm/log',
                'sed -i s/a/b/ ~/.claude/pm/a.md /repo/x',
                # only a plain date is a stamp
                'S=$(date; rm -rf build); echo x >> ~/.claude/pm/a.md',
                'S=$(date-build.sh); echo x >> ~/.claude/pm/a.md',
                'S=$(date -u; npm run build); echo x >> ~/.claude/pm/a.md',
                'S=$(date -u\nnpm run build\n); echo x >> ~/.claude/pm/a.md',
                'cat >> ~/.claude/pm/a.md <<EOF\n- $(date\nnpm test\n)\nEOF',
                # a redirect with no target must not crash the hook
                'echo x >',
                # paths
                'echo x >> ~/.claude/pm/../../x/app.ts',
                'echo x > %s/pm-other/a' % self.cfg,
                'cd ~/.claude/pm/../../x && sed -i s/a/b/ app.ts',
                'cd ~/.claude/pm && echo x >> sub/../../../x/app.ts',
                'cd ~/.claude/pm && echo x >> /repo/src/app.ts',
                'cd ~/.claude/pm; F=/repo/app.ts; echo x >> a$F',
                'cd ~/.claude/pm; cd /repo; echo x >> a.md',
                # reads and lone statements are not writes to own state
                'cat /repo/src/app.ts',
                'tail -1 /repo/src/app.ts',
                'echo x >> ~/.claude/pm/a.md; tail /repo/src/app.ts',
                'cd /repo',
                'echo a || echo b'):
            before = len(self.log_lines())
            self.fire(cmd)
            self.assertEqual(len(self.log_lines()), before + 1, "not logged: `%s`" % cmd)

    def test_a_huge_command_is_flagged_without_parsing(self):
        """Quoted text of 1 MB took 28 s to split; the hook's timeout is 5 s."""
        started = time.monotonic()
        self.fire('echo "%s" >> ~/.claude/pm/a.md' % ("x" * 1_000_000))
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(len(self.log_lines()), 1)


class AgentTeams(GuardCase):
    """A named Agent call in a boss starts an agent-teams teammate.

    With CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 the harness launches it without
    asking: no pane, no stamp, invisible to `list --mine`, the pulse and the
    workers watch, and it dies with the boss. Rare and costly, so every one is
    named out loud; the power-of-two throttle is for the cheap, frequent kind.
    """

    def spawn(self, **extra):
        ti = {"description": "x", "prompt": "do the thing"}
        ti.update(extra)
        return self.fire(tool="Agent", tool_input=ti)

    def test_a_named_agent_call_is_called_a_teammate(self):
        said = self.spawn(name="reviewer")
        self.assertIn("agent-teams teammate", said)
        self.assertIn("reviewer", said)

    def test_it_speaks_off_the_power_of_two_counts(self):
        for i in range(4):
            self.fire("touch f%d" % i)
        self.assertIn("agent-teams teammate", self.spawn(name="fifth"),
                      "a teammate spawn on call 5 went unsaid")

    def test_every_spawn_speaks(self):
        for i in range(3):
            self.assertIn("agent-teams teammate", self.spawn(name="t%d" % i))

    def test_spawns_are_logged(self):
        self.spawn(name="reviewer")
        self.assertEqual([l["tool"] for l in self.log_lines()], ["Agent"])

    def test_an_unnamed_agent_call_is_counted_like_the_rest(self):
        self.assertIn("Dispatch it to a worker", self.spawn())
        self.assertIn("2nd", self.spawn())
        self.assertEqual(self.spawn(), "", "the 3rd ordinary call should be silent")

    def test_a_named_fork_or_isolated_call_is_not_a_teammate(self):
        """The harness runs these as subagents even with a name."""
        self.assertNotIn("agent-teams teammate",
                         self.spawn(name="f", subagent_type="fork"))
        self.assertNotIn("agent-teams teammate",
                         self.spawn(name="w", isolation="worktree"))

    def test_a_session_with_no_marker_is_left_alone(self):
        self.assertEqual(self.fire(tool="Agent", sid="not-a-boss",
                                   tool_input={"name": "x", "prompt": "y"}), "")


class QuestionsGoThroughTheConcierge(GuardCase):
    """An open AskUserQuestion stops the boss's turn. Measured 2026-11-04: in 420
    of 421 questions held over two minutes the boss did nothing until the owner
    answered, while 762 worker messages queued. With a concierge the question
    is held by another session and the boss keeps dispatching."""

    def setUp(self):
        super().setUp()
        self.kids = []
        self.bindir = self.cfg / "bin"
        self.bindir.mkdir()
        (self.bindir / "tmux").write_text(
            '#!/usr/bin/env bash\n[[ -f "$STUB_DIR/tmux-fails" ]] && exit 1\n'
            '[[ "$1" == list-panes ]] && cat "$STUB_DIR/panes"\nexit 0\n')
        os.chmod(self.bindir / "tmux", 0o755)
        (self.cfg / "sessions").mkdir()
        self.session(self.sid, "%1", "Petra")

    def tearDown(self):
        for k in self.kids:
            k.kill()
            k.wait()
        super().tearDown()

    def session(self, sid, pane, name):
        kid = subprocess.Popen(["sleep", "60"])
        self.kids.append(kid)
        stat = Path("/proc/%d/stat" % kid.pid).read_text()
        (self.cfg / "sessions" / ("%d.json" % kid.pid)).write_text(json.dumps(
            {"pid": kid.pid, "sessionId": sid, "name": name, "status": "idle",
             "startedAt": 1000, "tmux": "boss:@1.%s" % pane, "entrypoint": "sdk-cli",
             "cwd": str(self.cfg), "procStart": stat[stat.rindex(")") + 2:].split()[19]}))

    def panes(self, *rows):
        (self.cfg / "panes").write_text("".join(r + "\n" for r in rows))

    def ask(self, question="Which org?"):
        payload = {"session_id": self.sid, "hook_event_name": "PreToolUse",
                   "tool_name": "AskUserQuestion",
                   "tool_input": {"questions": [{"question": question}]}}
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.cfg), STUB_DIR=str(self.cfg),
                   PATH="%s:%s" % (self.bindir, os.environ["PATH"]))
        res = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout.strip()
        return json.loads(out)["hookSpecificOutput"] if out else {}

    BOSS = "%1\tboss:0.0\t%1\tclaude\t/w\t-\t-"

    def test_a_live_concierge_takes_the_question_away_from_the_boss(self):
        self.session("c-sid", "%6", "Odile")
        self.panes(self.BOSS, "%6\tboss:0.1\t%1\tclaude\t/w\tOdile\tconcierge")
        out = self.ask()
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("Odile", out["permissionDecisionReason"])
        self.assertIn("SendMessage", out["permissionDecisionReason"])

    def test_a_question_for_the_owners_consent_stays_with_the_boss(self):
        # A peer message is never consent, so an answer relayed by the concierge
        # cannot release a gated action. Only a question in the boss's own turn can.
        self.session("c-sid", "%6", "Odile")
        self.panes(self.BOSS, "%6\tboss:0.1\t%1\tclaude\t/w\tOdile\tconcierge")
        self.assertEqual(self.ask("CONSENT: delete the old key? It cannot be undone."), {})

    def test_no_concierge_the_boss_asks_itself(self):
        self.panes(self.BOSS)
        self.assertEqual(self.ask(), {})

    def test_a_concierge_that_died_never_silences_the_boss(self):
        self.panes(self.BOSS, "%6\tboss:0.1\t%1\tbash\t/w\tOdile\tconcierge")
        self.assertEqual(self.ask(), {})

    def test_tmux_that_does_not_answer_never_silences_the_boss(self):
        (self.cfg / "tmux-fails").touch()
        self.assertEqual(self.ask(), {})

    def test_a_session_that_is_no_boss_is_left_alone(self):
        self.session("c-sid", "%6", "Odile")
        self.panes(self.BOSS, "%6\tboss:0.1\t%1\tclaude\t/w\tOdile\tconcierge")
        (self.markers / self.sid).unlink()
        self.assertEqual(self.ask(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
