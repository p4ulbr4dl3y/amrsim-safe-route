#!/usr/bin/env python3
"""Backward-compatibility wrapper for AMR SafeRoute Operator Station (АРМ).

Redirects to arm/server.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from arm.server import main  # noqa: E402

if __name__ == "__main__":
    main()
