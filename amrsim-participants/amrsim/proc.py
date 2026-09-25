"""Parent side of controller isolation: one child process per run.

The child runs amrsim/host.py with an empty temporary working directory, an
empty argv and a whitelisted environment. It receives the map (without
patches), the platform config and the initial pose, then one obs per tick.
Scenario name, seed, events and world truth never cross the pipe.
"""
import collections
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HOST = Path(__file__).resolve().parent / "host.py"

# Variables the child may inherit (anything else, including AMRSIM_*, is dropped).
ENV_KEEP = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "HOME",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONHOME",
            "PYTHONUSERBASE")
STDERR_CAP = 50 * 1024 * 1024   # a controller that prints more than this is stopped
STDERR_KEEP = 16 * 1024         # tail kept for the report


class ControllerError(Exception):
    """Controller failed: message is short and meant for the report."""


class WallLimit(Exception):
    """Real-time budget for the scenario is exhausted."""


def child_env(workdir):
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                "TMPDIR": workdir, "TEMP": workdir, "TMP": workdir})
    # numpy must be importable exactly as in the parent (it may come from PYTHONPATH);
    # only its own site directory is passed, not the parent's whole PYTHONPATH.
    try:
        import numpy
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(numpy.__file__)))
    except ImportError:
        pass
    return env


class ControllerProcess:
    def __init__(self, controller_path, map_, config, initial_pose, deadline, deny=()):
        self.path = Path(controller_path).resolve()
        if not self.path.is_file():
            raise ControllerError("controller file not found: %s" % controller_path)
        self.deadline = deadline
        self.workdir = tempfile.mkdtemp(prefix="amrsim_ctl_")
        self.q = queue.Queue()
        self.sandbox = []
        self.step_times = []
        self.proc = None
        self.err_tail = collections.deque()
        self.err_kept = 0
        self.err_total = 0
        self.err_overflow = False
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-B", "-X", "utf8", str(HOST)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.workdir, env=child_env(self.workdir), close_fds=True)
        except OSError as e:
            self.close()
            raise ControllerError("cannot start controller process: %s" % e)
        try:
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.err_reader = threading.Thread(target=self._drain_err, daemon=True)
            self.err_reader.start()
            init = {"type": "init", "controller": str(self.path), "map": map_, "config": config,
                    "initial_pose": list(initial_pose), "deny": [str(Path(d).resolve()) for d in deny]}
            rep = self._call(init, "init")
            if not rep.get("ok"):
                raise ControllerError(rep.get("error", "controller init failed"))
        except BaseException as e:
            e.stderr_tail = self.close()  # never leave the child or temp dirs behind
            raise

    def _read(self):
        out = self.proc.stdout
        for line in iter(out.readline, b""):
            self.q.put(line)
        self.q.put(None)

    def _drain_err(self):
        err = self.proc.stderr
        while True:
            chunk = err.read1(65536) if hasattr(err, "read1") else err.read(4096)
            if not chunk:
                return
            self.err_total += len(chunk)
            self.err_tail.append(chunk)
            self.err_kept += len(chunk)
            while self.err_kept > STDERR_KEEP and len(self.err_tail) > 1:
                self.err_kept -= len(self.err_tail.popleft())
            if self.err_total > STDERR_CAP and not self.err_overflow:
                self.err_overflow = True
                try:
                    self.proc.kill()
                except OSError:
                    pass

    def _send(self, msg):
        data = json.dumps(msg, separators=(",", ":")).encode("ascii") + b"\n"
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise ControllerError(self._died("while sending"))

    def _call(self, msg, what):
        self._send(msg)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise WallLimit()
        try:
            line = self.q.get(timeout=min(remaining, threading.TIMEOUT_MAX))
        except queue.Empty:
            raise WallLimit()
        if line is None:
            raise ControllerError(self._died("during " + what))
        try:
            rep = json.loads(line.decode("utf-8"))
        except ValueError:
            raise ControllerError("controller process wrote a non-protocol line to stdout")
        if not isinstance(rep, dict):
            raise ControllerError("controller process wrote a non-protocol line to stdout")
        self.sandbox.extend(rep.get("sandbox") or [])
        return rep

    def _died(self, when):
        if self.err_overflow:
            return "controller wrote more than %d MB to stdout/stderr and was stopped" % (STDERR_CAP // 2 ** 20)
        code = self.proc.poll()
        if code is None:
            try:
                code = self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                code = "running"
        tail = " | ".join(ln.strip() for ln in self.stderr_tail(3).splitlines() if ln.strip())
        if len(tail) > 300:
            tail = "..." + tail[-300:]
        return "controller process exited %s (code %s)%s" % (when, code, (": " + tail) if tail else "")

    def step(self, obs, truth=None):
        msg = {"type": "step", "obs": obs}
        if truth is not None:
            msg["truth"] = truth
        t0 = time.perf_counter()
        rep = self._call(msg, "step")
        self.step_times.append(time.perf_counter() - t0)
        if not rep.get("ok"):
            raise ControllerError(rep.get("error", "controller step failed"))
        return rep["cmd"]

    def stderr_tail(self, n=20):
        data = b"".join(list(self.err_tail))
        lines = data.decode("utf-8", "replace").splitlines()
        if self.err_total > len(data) and lines:
            lines = lines[1:]  # first line may be cut in the middle
        return "\n".join(lines[-n:]).strip()

    def close(self):
        """Stop the child (graceful, then kill), always reap it, remove the temp dir."""
        try:
            if self.proc is not None:
                if self.proc.poll() is None:
                    try:
                        self.proc.stdin.write(b'{"type":"stop"}\n')
                        self.proc.stdin.flush()
                    except (BrokenPipeError, OSError, ValueError):
                        pass
                    try:
                        self.proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait()
                for s in (self.proc.stdin, self.proc.stdout):
                    try:
                        s.close()
                    except (OSError, ValueError):
                        pass
                er = getattr(self, "err_reader", None)
                if er is not None:
                    er.join(timeout=2)
            return self.stderr_tail()
        finally:
            shutil.rmtree(self.workdir, ignore_errors=True)
