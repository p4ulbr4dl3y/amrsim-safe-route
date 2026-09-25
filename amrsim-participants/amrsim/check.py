"""amrsim check <team dir>: static rules for controllers (SPEC section 7).

VIOLATION (exit 1, the case scores 0): forbidden modules, interpreter frame
introspection, dependencies other than the standard library and numpy.
WARNING (exit 0, for the jury to read): constructs that the run-time sandbox
blocks or that deserve a human look.
This file is the only place in amrsim allowed to spell the forbidden names.
"""
import ast
import codecs
import re
import sys
from pathlib import Path

FORBIDDEN_MODULES = {
    "amrsim": "simulator internals",
    "gc": "garbage collector introspection",
    "inspect": "interpreter introspection",
    "ctypes": "raw memory access",
    "_ctypes": "raw memory access",
    "multiprocessing": "extra processes",
    "_multiprocessing": "extra processes",
    "threading": "threads",
    "_thread": "threads",
    "concurrent": "threads or processes",
}
FORBIDDEN_ATTRS = {
    "_getframe": "frame introspection", "_current_frames": "frame introspection",
    "tb_frame": "frame introspection", "f_back": "frame introspection",
    "f_locals": "frame introspection", "f_globals": "frame introspection",
    "gi_frame": "frame introspection", "cr_frame": "frame introspection",
    "ag_frame": "frame introspection", "cell_contents": "closure introspection",
    "addaudithook": "tampering with the sandbox",
    "currentframe": "frame introspection", "getouterframes": "frame introspection",
    "getinnerframes": "frame introspection", "getframeinfo": "frame introspection",
}
WARN_MODULES = {
    "subprocess": "process spawning (blocked at run time)",
    "socket": "network (blocked at run time)", "ssl": "network (blocked at run time)",
    "urllib": "network (blocked at run time)", "http": "network (blocked at run time)",
    "ftplib": "network", "smtplib": "network", "pty": "process spawning",
    "importlib": "dynamic import", "pickle": "code loading", "marshal": "code loading",
    "shelve": "code loading", "signal": "signal handling", "resource": "process limits",
}
WARN_CALLS = {"__import__": "dynamic import", "eval": "dynamic code", "exec": "dynamic code",
              "compile": "dynamic code", "globals": "namespace access", "vars": "namespace access"}
WARN_ATTRS = {"system": "os.system", "popen": "os.popen", "getppid": "parent process id",
              "execv": "exec", "execve": "exec", "spawnv": "spawn", "startfile": "startfile",
              "modules": "sys.modules access", "environ": "environment access",
              "argv": "argv access", "__closure__": "closure access", "__main__": "host module access"}
WARN_STRINGS = ("/proc", "amrsim", "hidden", ".jsonl", "sandbox", "__main__")
COMPILED = {".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib"}
DYNAMIC_CALLS = {"__import__", "import_module", "exec", "eval", "compile", "spec_from_file_location",
                 "run_path", "run_module", "load_source", "load_module"}
COOKIE = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


def _stdlib():
    names = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    names.add("__future__")
    return names


class _Scan(ast.NodeVisitor):
    def __init__(self, rel, local, out):
        self.rel = rel
        self.local = local
        self.out = out
        self.std = _stdlib()
        self.imports = []      # (level, module or None, [names]) for reachability
        self.dynamic = False   # dynamic import or exec with a computed argument

    def add(self, kind, node, msg):
        self.out.append((kind, "%s:%d" % (self.rel, getattr(node, "lineno", 0)), msg))

    def _module(self, node, name):
        top = name.split(".")[0]
        if top in FORBIDDEN_MODULES:
            self.add("VIOLATION", node, "import %s (%s is forbidden)" % (name, FORBIDDEN_MODULES[top]))
        elif top in WARN_MODULES:
            self.add("WARNING", node, "import %s: %s" % (name, WARN_MODULES[top]))
        elif top not in self.std and top != "numpy" and top not in self.local:
            self.add("VIOLATION", node, "import %s (only the standard library and numpy are allowed)" % name)

    def visit_Import(self, node):
        for a in node.names:
            self._module(node, a.name)
            self.imports.append((0, a.name, []))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        self.imports.append((node.level, node.module, [a.name for a in node.names]))
        if node.level == 0 and node.module:
            self._module(node, node.module)
            if node.module.split(".")[0] in ("sys", "os"):
                for a in node.names:
                    self._attr(node, a.name)
        self.generic_visit(node)

    def _attr(self, node, name):
        if name in FORBIDDEN_MODULES and isinstance(node, ast.Attribute):
            self.add("VIOLATION", node, ".%s (%s is forbidden, also via another module)" %
                     (name, FORBIDDEN_MODULES[name]))
        elif name in FORBIDDEN_ATTRS:
            self.add("VIOLATION", node, "%s (%s is forbidden)" % (name, FORBIDDEN_ATTRS[name]))
        elif name in WARN_ATTRS:
            self.add("WARNING", node, "%s: %s" % (name, WARN_ATTRS[name]))

    def visit_Attribute(self, node):
        self._attr(node, node.attr)
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in FORBIDDEN_ATTRS or node.id == "__main__":
            self._attr(node, node.id)
        self.generic_visit(node)

    def visit_Call(self, node):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
        if name in WARN_CALLS:
            self.add("WARNING", node, "%s(): %s" % (name, WARN_CALLS[name]))
        literal = bool(node.args) and isinstance(node.args[0], ast.Constant) and \
            isinstance(node.args[0].value, (str, bytes))
        if name in ("__import__", "import_module") and literal:
            self._module(node, node.args[0].value)
            self.imports.append((0, node.args[0].value, []))
        elif name in ("exec", "eval", "compile") and literal:
            try:
                sub = ast.parse(node.args[0].value, mode="exec")
            except (SyntaxError, ValueError):
                sub = None
            if sub is not None:
                for n in ast.walk(sub):
                    if hasattr(n, "lineno"):
                        n.lineno = node.lineno
                self.visit(sub)
        elif name in DYNAMIC_CALLS:
            self.dynamic = True
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            v = node.value
            if v in FORBIDDEN_ATTRS:
                self.add("VIOLATION", node, "string '%s' (%s is forbidden)" % (v, FORBIDDEN_ATTRS[v]))
            elif v.split(".")[0] in FORBIDDEN_MODULES and "." not in v.strip(".") and v == v.strip():
                self.add("WARNING", node, "string '%s' names a forbidden module" % v)
            for s in WARN_STRINGS:
                if s in v:
                    self.add("WARNING", node, "string mentions '%s'" % s)
                    break


def _is_venv(d):
    return (d / "pyvenv.cfg").is_file()


def _team_files(root):
    """All files of the submission except .git and real virtual environments."""
    out = []
    venvs = []
    stack = [root]
    while stack:
        d = stack.pop()
        for p in sorted(d.iterdir()):
            if p.is_dir():
                if p.name == ".git":
                    continue
                if _is_venv(p):
                    venvs.append(p)
                    continue
                stack.append(p)
            else:
                out.append(p)
    return sorted(out), venvs


def _modname(root, p):
    parts = list(p.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _local_names(pyfiles, root):
    names = set()
    for p in pyfiles:
        rel = p.relative_to(root).parts
        names.add(rel[0][:-3] if rel[0].endswith(".py") else rel[0])
    return names


def _has_controller_class(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "Controller":
            if n.bases:
                return True  # methods may be inherited; the host verifies at run time
            fns = {m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            return {"__init__", "step"} <= fns
        if isinstance(n, (ast.Import, ast.ImportFrom)) and \
                any((a.asname or a.name) == "Controller" for a in n.names):
            return True
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "Controller"
                                             for t in n.targets):
            return True
    return False


def _cookie_warning(raw):
    for line in raw.splitlines()[:2]:
        m = COOKIE.match(line)
        if m:
            enc = m.group(1).decode("ascii", "replace").lower().replace("_", "-")
            if enc not in ("utf-8", "utf8", "ascii", "us-ascii", "latin-1", "iso-8859-1", "cp1251",
                           "windows-1251", "utf-8-sig"):
                return enc
    return None


def _read_text_any(p):
    raw = p.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def check_dir(target):
    """Return (findings, fatal) for a team directory or a controller.py path."""
    target = Path(target)
    root = (target.parent if target.is_file() else target)
    main = target if target.is_file() else root / "controller.py"
    out = []
    if not root.is_dir():
        return [("ERROR", str(root), "directory not found")], True
    if not main.is_file():
        return [("ERROR", str(main), "controller.py not found")], True
    root = root.resolve()
    main = main.resolve()
    files, venvs = _team_files(root)
    for v in venvs:
        out.append(("WARNING", v.relative_to(root).as_posix(),
                    "virtual environment inside the submission is ignored"))
    pyfiles = [p for p in files if p.suffix == ".py"]
    local = _local_names(pyfiles, root)
    per_file = {}
    for p in files:
        rel = p.relative_to(root).as_posix()
        if p.suffix in COMPILED and "__pycache__" not in p.parts:
            per_file.setdefault(p, []).append(
                ("VIOLATION", rel, "compiled module (%s): ship Python source only" % p.suffix))
    scans = {}
    for p in pyfiles:
        rel = p.relative_to(root).as_posix()
        f = per_file.setdefault(p, [])
        raw = p.read_bytes()
        enc = _cookie_warning(raw)
        if enc:
            f.append(("WARNING", rel, "source declares coding '%s'" % enc))
        try:
            tree = ast.parse(raw, filename=rel)  # bytes: BOM and coding cookie as the interpreter does
        except (SyntaxError, ValueError, LookupError, UnicodeDecodeError) as e:
            f.append(("ERROR", rel, "cannot parse: %s" % e))
            continue
        if p == main and not _has_controller_class(tree):
            f.append(("ERROR", rel, "class Controller with __init__ and step not found"))
        sc = _Scan(rel, local, f)
        sc.visit(tree)
        scans[p] = sc
    reach = _reachable(root, main, pyfiles, scans)
    for p in sorted(per_file):
        for kind, where, msg in per_file[p]:
            if kind in ("VIOLATION", "ERROR") and p not in reach and p.suffix == ".py":
                out.append(("WARNING", where, msg + " (not imported by controller.py)"))
            else:
                out.append((kind, where, msg))
    req = root / "requirements.txt"
    if req.is_file():
        for ln in _read_text_any(req).splitlines():
            ln = ln.strip().lstrip("\ufeff").strip()
            if not ln or ln.startswith("#"):
                continue
            m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", ln)
            name = re.sub(r"[-_.]+", "-", m.group(1)).lower() if m else ""
            if name != "numpy" or "@" in ln or "://" in ln:
                out.append(("VIOLATION", "requirements.txt", "dependency '%s' (only numpy is allowed)" % ln))
    if not (root / "APPROACH.md").is_file():
        out.append(("WARNING", "APPROACH.md", "missing (required in the submission, SPEC 10)"))
    fatal = any(k in ("VIOLATION", "ERROR") for k, _, _ in out)
    return out, fatal


def _reachable(root, main, pyfiles, scans):
    """Files the controller can import. Dynamic imports make every file reachable."""
    by_name = {_modname(root, p): p for p in pyfiles}
    by_name["controller"] = main
    seen = {main}
    todo = [main]
    while todo:
        p = todo.pop()
        sc = scans.get(p)
        if sc is None:
            continue
        if sc.dynamic:
            return set(pyfiles)
        pkg = _modname(root, p)
        if p.name != "__init__.py":
            pkg = pkg.rpartition(".")[0]
        cands = []
        for level, mod, names in sc.imports:
            if level:
                base = pkg.split(".") if pkg else []
                base = base[:len(base) - (level - 1)] if level > 1 else base
                prefix = ".".join(base + ([mod] if mod else []))
            else:
                prefix = mod or ""
            parts = prefix.split(".") if prefix else []
            cands += [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
            cands += [(prefix + "." + n) if prefix else n for n in names]
        for c in cands:
            q = by_name.get(c)
            if q is not None and q not in seen:
                seen.add(q)
                todo.append(q)
    return seen
