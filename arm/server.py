#!/usr/bin/env python3
"""AMR SafeRoute Operator Station (АРМ Оператора) Server-Driven UI API Backend.

Serves real simulation logs, reports, scenarios, and provides Server-Driven UI endpoints
for the AMR SafeRoute operator dashboard without external dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import types
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path for direct script execution
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from arm.core import config, runner  # noqa: E402
from arm.core.config import (  # noqa: E402
    _REPORT_CACHE,
    _SIM_LOCK,
    BACKEND_SCENARIOS_DIR,
    CATEGORY_NAMES,
    FRONTEND_DIST,
    OUT_DIR,
    POINT_LABELS,
    RESULTS_DIR,
    ROOT_DIR,
    RULE_EXPLANATIONS,
    SCENARIO_META,
    SCENARIOS_DIR,
    TEAM_SCENARIOS_DIR,
    BoundedCache,
    _safe_dict,
    _safe_float,
    format_time,
    normalize_scenario_id,
)
from arm.core.runner import (  # noqa: E402
    format_simulation_logs,
    resolve_python_command,
    run_simulation,
)
from arm.services import storage, view_models  # noqa: E402
from arm.services.storage import (  # noqa: E402
    _TICKS_CACHE,
    get_scenario_file,
    get_scenario_log_path,
    get_scenario_report,
    load_scenario_json,
    parse_ticks_log,
)
from arm.services.view_models import (  # noqa: E402
    build_analytics_view_model,
    build_dashboard_view_model,
    build_episodes_view_model,
    build_missions_view_model,
    build_replay_missions,
    build_replay_view_model,
    compute_step_distribution,
    extract_map_data,
)
from arm.transport import handler  # noqa: E402
from arm.transport.handler import (  # noqa: E402
    AMRServerHandler,
    generate_episodes_csv,
)

__all__ = [
    "AMRServerHandler",
    "BACKEND_SCENARIOS_DIR",
    "BoundedCache",
    "CATEGORY_NAMES",
    "FRONTEND_DIST",
    "HTTPStatus",
    "OUT_DIR",
    "POINT_LABELS",
    "Path",
    "RESULTS_DIR",
    "ROOT_DIR",
    "RULE_EXPLANATIONS",
    "SCENARIO_META",
    "SCENARIOS_DIR",
    "SimpleHTTPRequestHandler",
    "TEAM_SCENARIOS_DIR",
    "ThreadingHTTPServer",
    "_REPORT_CACHE",
    "_SIM_LOCK",
    "_TICKS_CACHE",
    "_safe_dict",
    "_safe_float",
    "argparse",
    "build_analytics_view_model",
    "build_dashboard_view_model",
    "build_episodes_view_model",
    "build_missions_view_model",
    "build_replay_missions",
    "build_replay_view_model",
    "compute_step_distribution",
    "extract_map_data",
    "format_simulation_logs",
    "format_time",
    "generate_episodes_csv",
    "get_scenario_file",
    "get_scenario_log_path",
    "get_scenario_report",
    "json",
    "load_scenario_json",
    "main",
    "math",
    "normalize_scenario_id",
    "os",
    "parse_ticks_log",
    "resolve_python_command",
    "run_simulation",
    "shutil",
    "subprocess",
    "sys",
    "threading",
]


class _ServerFacade(types.ModuleType):
    """Facade module proxy that propagates monkeypatched attributes to internal modules."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for mod in (config, storage, runner, view_models, handler):
            if hasattr(mod, name):
                setattr(mod, name, value)


_current_mod = sys.modules.get(__name__)
if _current_mod is not None:
    _current_mod.__class__ = _ServerFacade


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AMR SafeRoute Operator Station SDUI API Server"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)"
    )
    args = parser.parse_args()

    # Установка рабочего каталога для статических файлов SimpleHTTPRequestHandler
    if FRONTEND_DIST.exists():
        os.chdir(str(FRONTEND_DIST))
    else:
        os.chdir(str(ROOT_DIR))

    server = ThreadingHTTPServer((args.host, args.port), AMRServerHandler)
    print(
        f"Сервер API АРМ Безопасный маршрут (SDUI) запущен: http://{args.host}:{args.port}"
    )
    print("Конечные точки интерфейса:")
    print("  GET  /docs (Swagger UI документация)")
    print("  GET  /api/openapi.json (OpenAPI 3.0 спецификация)")
    print("  GET  /api/scenarios")
    print("  GET  /api/ui/dashboard?scenario=<id>")
    print("  GET  /api/ui/replay?scenario=<id>&seed=<seed>")
    print("  GET  /api/ui/episodes?scenario=<id>")
    print("  GET  /api/ui/missions?scenario=<id>")
    print("  GET  /api/ui/analytics?scenario=<id>")
    print("  POST /api/run")
    print("  GET  /api/export/csv?scenario=<id>")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
        server.server_close()


if __name__ == "__main__":
    main()
