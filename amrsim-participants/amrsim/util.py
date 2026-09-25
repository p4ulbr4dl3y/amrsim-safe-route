"""Small shared helpers: errors, hashing, JSON io."""
import hashlib
import json
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent


class AmrsimError(Exception):
    """Expected failure with a short user-facing message and an exit code."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def package_hash():
    """sha256 over amrsim/*.py (sorted by name), first 16 hex chars."""
    h = hashlib.sha256()
    for p in sorted(PKG_DIR.glob("*.py")):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def read_json(path):
    p = Path(path)
    if not p.is_file():
        raise AmrsimError("file not found: %s" % p)
    try:
        text = p.read_text(encoding="utf-8-sig")  # tolerate a BOM from Windows editors
    except UnicodeDecodeError:
        raise AmrsimError("not UTF-8 text: %s (save the file as UTF-8)" % p)
    except OSError as e:
        raise AmrsimError("cannot read %s: %s" % (p, e.strerror))
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AmrsimError("not valid JSON: %s (line %d: %s)" % (p, e.lineno, e.msg))


def write_json(path, obj):
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")
    except OSError as e:
        raise AmrsimError("cannot write %s: %s" % (p, e.strerror))


def check_writable(path):
    """Fail early (before a long run) if an output file cannot be created."""
    if path is None:
        return
    p = Path(path)
    if p.is_dir():
        raise AmrsimError("cannot write %s: is a directory" % p)
    existed = p.exists()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8"):
            pass
    except OSError as e:
        raise AmrsimError("cannot write %s: %s" % (p, e.strerror or e))
    if not existed:
        p.unlink()
