"""Controller host: runs inside the isolated child process.

Started by amrsim.runner as `python -B -X utf8 host.py` with an empty temporary
working directory, an empty argv and a whitelisted environment. Protocol: one
JSON object per line on stdin (init, step, stop), one reply per line on the
original stdout. The controller's own prints go to stderr.

This file must not import the amrsim package: the child process never holds
simulator code or world truth.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _under(path, roots):
    for r in roots:
        if path == r or path.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


class Guard:
    """Audit hook: file access limited to allowed roots; no processes, network, ctypes.

    Not a security boundary against a determined attacker (see docs/DATA.md);
    it closes accidental and casual access to scenario files and the parent
    process, and records every attempt for the jury.
    """

    BLOCK_EXACT = {
        "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
        "os.forkpty", "os.startfile", "pty.spawn", "os.kill", "os.killpg", "os.symlink", "os.link",
        "urllib.Request", "sys.remote_exec", "webbrowser.open",
    }
    BLOCK_PREFIX = ("socket.", "ctypes.", "_winapi.", "winreg.", "sqlite3.", "ftplib.", "smtplib.",
                    "poplib.", "imaplib.", "nntplib.", "telnetlib.", "http.client.")
    # Only modules that open a channel out of the process. threading, inspect and the like are
    # forbidden by the static check (SPEC 7) but are pulled in by stdlib modules such as
    # dataclasses or pathlib on Python 3.10-3.12, so they are not blocked at run time.
    BLOCK_IMPORT = {"amrsim", "gc", "ctypes", "_ctypes", "multiprocessing", "_multiprocessing",
                    "subprocess", "_posixsubprocess", "socket", "_socket", "ssl", "http", "psutil",
                    "pty"}
    WRITE_MODES = set("wax+")

    def __init__(self, read_roots, write_roots, deny_roots, violations):
        self.read_roots = tuple(_norm(p) for p in read_roots if p)
        self.write_roots = tuple(_norm(p) for p in write_roots if p)
        self.deny_roots = tuple(_norm(p) for p in deny_roots if p)
        self.violations = violations
        # instance copies: class attributes and module globals can be rebound by user code
        self.block_exact = frozenset(self.BLOCK_EXACT)
        self.block_prefix = tuple(self.BLOCK_PREFIX)
        self.block_import = frozenset(self.BLOCK_IMPORT)
        self.write_modes = frozenset(self.WRITE_MODES)
        self.norm = _norm
        self.under = _under
        self.fsdecode = os.fsdecode
        self.wflags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def _deny(self, what, exc=PermissionError):
        if len(self.violations) < 100:
            self.violations.append(what[:200])
        raise exc("amrsim sandbox: %s is not allowed for controllers" % what)

    def _check_path(self, path, write):
        if isinstance(path, int):
            return
        try:
            p = self.norm(self.fsdecode(path))
        except (TypeError, ValueError):
            return
        roots = self.write_roots if write else self.read_roots + self.write_roots
        allow = max((len(r) for r in roots if self.under(p, (r,))), default=-1)
        deny = max((len(r) for r in self.deny_roots if self.under(p, (r,))), default=-1)
        if deny >= 0 and deny >= allow:  # the most specific root decides
            self._deny("access to %s" % p)
        if allow < 0:
            self._deny("%s %s" % ("write" if write else "read", p))

    def hook(self, event, args):
        if event == "open":
            path, mode, flags = args
            write = bool(set(mode) & self.write_modes) if isinstance(mode, str) else \
                bool((flags or 0) & self.wflags)
            if path is not None:
                self._check_path(path, write)
        elif event in ("os.listdir", "os.scandir"):
            path = args[0] if args and args[0] is not None else "."
            self._check_path(path, False)
        elif event in ("os.rename", "shutil.move"):
            self._check_path(args[0], True)
            self._check_path(args[1], True)
        elif event in ("shutil.copyfile", "shutil.copytree", "shutil.copymode", "shutil.copystat"):
            self._check_path(args[0], False)
            self._check_path(args[1], True)
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.truncate", "os.chmod",
                       "os.chown", "os.utime", "os.chflags", "os.lchflags"):
            if args:
                self._check_path(args[0], True)
        elif event == "import":
            top = str(args[0]).split(".")[0]
            if top in self.block_import:
                self._deny("import %s" % args[0], ImportError)
        elif event in self.block_exact or event.startswith(self.block_prefix):
            self._deny(event)



class Violations(list):
    reported = 0

    def new(self):
        v = self[self.reported:]
        self.reported = len(self)
        return list(v)


def _short_error(exc, ctrl_dir):
    import traceback
    where = ""
    # lookup_lines=False: reading source files here would trip the sandbox (host.py is denied)
    frames = traceback.StackSummary.extract(traceback.walk_tb(exc.__traceback__), lookup_lines=False)
    for fr in frames:
        if fr.filename and _norm(fr.filename).startswith(ctrl_dir):
            where = " (%s:%d in %s)" % (os.path.basename(fr.filename), fr.lineno, fr.name)
    msg = str(exc).replace("\n", " ")
    if len(msg) > 300:
        msg = msg[:300] + "..."
    return "%s: %s%s" % (type(exc).__name__, msg, where)


def _num(v, name):
    import numbers
    if isinstance(v, bool) or not isinstance(v, numbers.Real):  # numpy scalars are Real
        raise ValueError("step() returned %s=%r, expected a number" % (name, v))
    return float(v)


def _clean_cmd(out):
    if not isinstance(out, dict):
        raise ValueError("step() must return a dict, got %s" % type(out).__name__)
    if "v" not in out or "w" not in out:
        raise ValueError("step() result must contain 'v' and 'w'")
    cmd = {"v": _num(out["v"], "v"), "w": _num(out["w"], "w"),
           "status": str(out.get("status", "moving"))}
    pe = out.get("pose_est")
    if pe is not None:
        try:
            pe = [float(a) for a in pe]
        except (TypeError, ValueError, OverflowError):
            pe = None  # malformed estimate: scored as a large pose error, not a controller error
    cmd["pose_est"] = pe
    note = out.get("note", "")
    cmd["note"] = str(note)[:200] if note is not None else ""
    return cmd


def main():
    proto_in = os.fdopen(os.dup(0), "rb")
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)  # a controller reading stdin gets EOF instead of eating the protocol
    os.close(null)
    raw = proto_in.readline()
    proto = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)  # controller prints end up in stderr, not in the protocol

    def reply(obj):
        proto.write(json.dumps(obj, separators=(",", ":")).encode("ascii") + b"\n")

    try:
        init = json.loads(raw.decode("utf-8"))
    except ValueError:
        reply({"ok": False, "error": "host: bad init message"})
        return 2
    ctrl_path = init["controller"]
    ctrl_dir = _norm(os.path.dirname(ctrl_path))
    sys.argv = []
    sys.path[:] = [p for p in sys.path if p and _norm(p) != _norm(_HERE)]
    sys.path.insert(0, os.path.dirname(ctrl_path))
    try:
        import numpy  # noqa: F401  pre-import before the guard (numpy loads ctypes itself)
        import numpy.linalg  # noqa: F401
        import numpy.random  # noqa: F401
        import numpy.fft  # noqa: F401
    except ImportError as e:
        reply({"ok": False, "error": "numpy is not importable in the controller process: %s" % e})
        return 2
    import importlib.util
    import math  # noqa: F401
    import numbers  # noqa: F401  used by _num, import before the guard
    import traceback  # noqa: F401  used by _short_error, import before the guard
    import linecache
    # warnings attributed to host.py must read its source from the cache, not open it under the guard
    linecache.getlines(os.path.abspath(__file__))

    # bytecode of team modules is looked up (and never written) in the temp cwd, so a shipped
    # __pycache__ cannot run code that differs from the checked source
    sys.pycache_prefix = os.getcwd()
    py_roots = [p for p in sys.path[1:] if p and os.path.exists(p)]
    py_roots += [sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(numpy.__file__)]
    violations = Violations()
    # No Python reference to the Guard instance is kept: only the audit hook list holds it.
    sys.addaudithook(Guard([ctrl_dir] + py_roots, [os.getcwd()], init.get("deny", []) + [_HERE],
                           violations).hook)

    try:
        spec = importlib.util.spec_from_file_location("controller", ctrl_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["controller"] = mod
        spec.loader.exec_module(mod)
        if not hasattr(mod, "Controller"):
            raise AttributeError("controller.py has no class Controller")
        ctrl = mod.Controller(init["map"], init["config"], init["initial_pose"])
    except BaseException as e:  # report any failure of user code, including SystemExit
        if isinstance(e, KeyboardInterrupt):
            raise
        reply({"ok": False, "error": "init: " + _short_error(e, ctrl_dir),
               "sandbox": violations.new()})
        return 3
    del init
    reply({"ok": True, "sandbox": violations.new()})

    set_truth = getattr(ctrl, "set_truth", None)
    while True:
        line = proto_in.readline()
        if not line:
            return 0
        msg = json.loads(line.decode("utf-8"))
        if msg.get("type") != "step":
            return 0
        try:
            if "truth" in msg and callable(set_truth):
                set_truth(msg["truth"])
            cmd = _clean_cmd(ctrl.step(msg["obs"]))
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            reply({"ok": False, "error": _short_error(e, ctrl_dir), "sandbox": violations.new()})
            return 3
        r = {"ok": True, "cmd": cmd}
        v = violations.new()
        if v:
            r["sandbox"] = v
        reply(r)


if __name__ == "__main__":
    sys.exit(main())
