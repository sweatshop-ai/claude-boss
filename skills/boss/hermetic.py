"""A sealed sandbox for running skills/boss/bin/boss-run in tests.

Not a test file: tests import it (`from hermetic import Sandbox`).

boss-run calls `codex` and `claude` and then runs the approved command through
`bash -lc`. A test that let any of that resolve to the real binaries would spend
money, touch the network, or run something on this machine. So the sandbox builds
the child's environment from scratch: PATH is a stubs directory followed by a
tools directory holding symlinks to a short whitelist of real binaries. `codex`,
`claude`, `gh` and `tmux` exist only as the stubs a test writes; if a test writes
none, they do not exist at all.

Every stub logs its argv and its stdin under calls/ before doing anything else,
so a test can see exactly how the reviewer was called.
"""
import json
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOSS_RUN = HERE / "bin" / "boss-run"

# The real binaries a boss-run needs, and nothing else.
TOOLS = ("bash sh env jq date mkdir mktemp cat grep sed tr head tail rm timeout "
         "dirname sleep touch wc python3 sort cut").split()
# Names that must never resolve to a real binary inside the sandbox.
FORBIDDEN = ("codex", "claude", "gh", "tmux")

Call = namedtuple("Call", "argv stdin")


class Sandbox:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="boss-run-sb-")).resolve()
        self.stubs = self.root / "stubs"
        self.tools = self.root / "tools"
        self.calls = self.root / "calls"
        self.cfg = self.root / "cfg"
        self.home = self.root / "home"
        self.work = self.root / "work"
        self.tmp = self.root / "tmp"
        self.side = self.root / "side"
        for d in (self.stubs, self.tools, self.calls, self.cfg, self.home,
                  self.work, self.tmp, self.side):
            d.mkdir()
        try:
            for name in TOOLS:
                real = shutil.which(name)
                if real is None:
                    raise RuntimeError("sandbox needs the real %r on PATH" % name)
                (self.tools / name).symlink_to(os.path.abspath(real))
            self._bash = os.path.abspath(shutil.which("bash"))
            self.env = {
                "PATH": "%s:%s" % (self.stubs, self.tools),
                "HOME": str(self.home),
                "CLAUDE_CONFIG_DIR": str(self.cfg),
                "TMPDIR": str(self.tmp),
                "CLAUDE_CODE_SESSION_ID": "sess-test",
                "LC_ALL": "C.UTF-8",
            }
            self.guard()
        except BaseException:
            self.cleanup()
            raise

    # ------------------------------------------------------------- the seal ----
    def guard(self):
        """Raise unless the real codex, claude, gh and tmux are out of reach."""
        path = self.env["PATH"]
        if path.split(os.pathsep)[0] != str(self.stubs):
            raise AssertionError("stubs is not first on PATH: %s" % path)
        for name in FORBIDDEN:
            found = shutil.which(name, path=path)
            if found is not None and Path(found).parent != self.stubs:
                raise AssertionError("%s resolves outside the sandbox: %s" % (name, found))

    # ------------------------------------------------------------------ stubs ----
    def stub(self, name, *, answer=None, out="", err="", rc=0, hang=False, child=False):
        """Write stubs/<name>, a bash script that logs its call, then behaves.

        answer  the reviewer's reply: written to the file after `-o` for codex,
                printed on stdout for everything else
        out/err noise on stdout/stderr, to prove diagnostics never leak
        rc      exit status
        hang    sleep 300 after logging
        child   start `sleep 300 &`, record its pid in <root>/child.pid, then wait
        """
        files = {}
        for key, text in (("answer", answer), ("out", out), ("err", err)):
            if text:
                path = self.side / ("%s.%s" % (name, key))
                path.write_text(text if key == "answer" else text + "\n", encoding="utf-8")
                files[key] = shlex.quote(str(path))
        lines = [
            "#!" + self._bash,
            "R=" + shlex.quote(str(self.root)),
            'ID="$(date +%%s%%N)-%s"' % name,
            'if [ "$#" -gt 0 ]; then printf \'%s\\0\' "$@" > "$R/calls/$ID.argv"; '
            'else : > "$R/calls/$ID.argv"; fi',
            'cat > "$R/calls/$ID.stdin"',
        ]
        if child:
            lines.append('sleep 300 & echo $! > "$R/child.pid"')
        if hang:
            lines.append("sleep 300")
        elif child:
            lines.append("wait")
        if "out" in files:
            lines.append("cat %s" % files["out"])
        if "err" in files:
            lines.append("cat %s >&2" % files["err"])
        if "answer" in files:
            if name == "codex":
                lines += ['prev=""; dest=""',
                          'for a in "$@"; do [ "$prev" = "-o" ] && dest=$a; prev=$a; done',
                          '[ -n "$dest" ] && cat %s > "$dest"' % files["answer"]]
            else:
                lines.append("cat %s" % files["answer"])
        lines.append("exit %d" % rc)
        path = self.stubs / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)
        self.guard()
        return path

    def calls_of(self, name):
        """Every call the stub `name` received, oldest first."""
        found = []
        for argv_file in sorted(self.calls.glob("*-%s.argv" % name)):
            raw = argv_file.read_bytes().decode("utf-8", "surrogateescape")
            argv = raw.split("\0")[:-1] if raw else []
            stdin_file = argv_file.with_suffix(".stdin")
            stdin = (stdin_file.read_bytes().decode("utf-8", "surrogateescape")
                     if stdin_file.exists() else "")
            found.append(Call(argv, stdin))
        return found

    # --------------------------------------------------------------- running ----
    def boss_run(self, *args, stdin="", timeout=60, extra_env=None):
        env = dict(self.env)
        extra = dict(extra_env or {})
        if "PATH" in extra:
            raise AssertionError("a test may not replace the sandbox PATH")
        env.update(extra)
        proc = subprocess.Popen(
            [str(BOSS_RUN), *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=str(self.work), text=True,
            encoding="utf-8", errors="replace", start_new_session=True)
        try:
            out, err = proc.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            self.reap()
            proc.communicate()
            raise
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def log_lines(self):
        """The parsed lines of cfg/pm/boss-run.log, oldest first ([] if absent)."""
        path = self.cfg / "pm" / "boss-run.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    # ---------------------------------------------------------------- cleanup ----
    def reap(self):
        """SIGKILL every process that carries this sandbox's environment.

        `timeout` puts its command in a group of its own, so a hung stub and its
        children are out of reach of the process group boss_run killed.
        """
        marker = ("CLAUDE_CONFIG_DIR=%s" % self.cfg).encode()
        me = os.getpid()
        for entry in os.listdir("/proc"):
            if not entry.isdigit() or int(entry) == me:
                continue
            try:
                environ = Path("/proc/%s/environ" % entry).read_bytes()
            except OSError:
                continue
            if marker in environ.split(b"\0"):
                try:
                    os.kill(int(entry), signal.SIGKILL)
                except OSError:
                    pass

    def cleanup(self):
        self.reap()
        shutil.rmtree(self.root, ignore_errors=True)
