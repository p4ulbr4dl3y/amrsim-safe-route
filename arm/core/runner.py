"""Simulation runner and subprocess manager for AMR SafeRoute."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from arm.core import config
from arm.core.config import (
    BoundedCache,
    _safe_dict,
    normalize_scenario_id,
)
from arm.services import storage

ROOT_DIR: Path = config.ROOT_DIR
OUT_DIR: Path = config.OUT_DIR
_SIM_LOCK = config._SIM_LOCK
_REPORT_CACHE: BoundedCache = config._REPORT_CACHE
_TICKS_CACHE: BoundedCache = config._TICKS_CACHE


def resolve_python_command() -> list[str]:
    """Команда запуска интерпретатора Python >= 3.10 для симулятора amrsim.

    Системный ``python3`` может быть младше 3.10 (например, 3.9 в macOS), из-за
    чего запуск задания из вкладки Runner падал с ``exitCode 2`` и сообщением
    ``amrsim requires Python 3.10 or newer``. Предпочитаем интерпретатор
    проектного окружения ``uv`` (``uv run --project <корень>``), которое
    собирается из ``pyproject.toml`` с ``requires-python = ">=3.10"`` и
    зависимостью ``numpy``. Если ``uv`` нет, ищем системный интерпретатор >= 3.10
    с установленным ``numpy``; иначе поднимаем понятную ошибку.
    """
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--project", str(ROOT_DIR), "python"]

    probe_code = (
        "import sys, importlib.util\n"
        "raise SystemExit(0 if sys.version_info >= (3, 10) "
        "and importlib.util.find_spec('numpy') else 1)\n"
    )

    candidates: list[str] = [sys.executable]
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
        exe = shutil.which(name)
        if exe and exe not in candidates:
            candidates.append(exe)

    for exe in candidates:
        try:
            probe = subprocess.run(
                [exe, "-c", probe_code],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            continue
        if probe.returncode == 0:
            return [exe]

    raise RuntimeError(
        "Не найден интерпретатор Python >= 3.10 с numpy для запуска amrsim. "
        "Установите uv (https://docs.astral.sh/uv/), он поднимет окружение из "
        "pyproject.toml, либо поставьте Python 3.10+ и `pip install numpy`, затем "
        "повторите запуск."
    )


def run_simulation(
    scenario_id: str,
    controller_path: str = "team_dreamteam_4_0/controller.py",
    seed: int = 7,
    cheat: bool = False,
    scenario_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _SIM_LOCK:
        if scenario_data and isinstance(scenario_data, dict):
            saved_id, _ = storage.save_scenario(scenario_data, scenario_id=scenario_id)
            scenario_id = saved_id

        norm_id = normalize_scenario_id(scenario_id)
        scen_file = storage.get_scenario_file(norm_id) or storage.get_scenario_file(scenario_id)
        if not scen_file:
            raise FileNotFoundError(f"Scenario not found: {scenario_id}")

        report_path = OUT_DIR / f"{norm_id}.json"
        log_path = OUT_DIR / f"{norm_id}.jsonl"

        if controller_path.startswith("team/"):
            controller_path = "team_dreamteam_4_0/" + controller_path[len("team/") :]
        elif controller_path.startswith("backend/"):
            controller_path = "team_dreamteam_4_0/" + controller_path[len("backend/") :]

        env = os.environ.copy()
        amrsim_part_dir = str((ROOT_DIR / "amrsim-participants").resolve())
        curr_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{amrsim_part_dir}{os.pathsep}{curr_pp}" if curr_pp else amrsim_part_dir
        )

        cmd = [
            *resolve_python_command(),
            "-m",
            "amrsim",
            "run",
            str(scen_file),
            "--controller",
            str(ROOT_DIR / controller_path),
            "--seed",
            str(seed),
            "--report",
            str(report_path),
            "--log",
            str(log_path),
        ]
        if cheat:
            cmd.append("--cheat")

        proc = subprocess.run(
            cmd, cwd=str(ROOT_DIR), env=env, capture_output=True, text=True
        )

        # Сброс кэша для данного сценария
        _REPORT_CACHE.pop(norm_id, None)
        _TICKS_CACHE.pop(norm_id, None)

        report_data = None
        if report_path.exists():
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    report_data = json.load(f)
                    _REPORT_CACHE[norm_id] = report_data
            except Exception:
                pass

        return {
            "exitCode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "reportPath": str(report_path),
            "logPath": str(log_path),
            "report": report_data,
            "score": (
                _safe_dict(report_data.get("score")).get("total")
                if isinstance(report_data, dict)
                else None
            ),
        }


def format_simulation_logs(
    scenario: str, controller: str, seed: int, res: dict[str, Any]
) -> list[str]:
    logs = [
        f"$ python -m amrsim run {scenario}.json --controller {controller} --seed {seed}",
        f"[INFO] Initializing simulation for scenario {scenario}...",
    ]
    if res.get("stdout"):
        logs.extend(res["stdout"].splitlines())
    if res.get("stderr"):
        logs.extend(res["stderr"].splitlines())
    logs.append(f"[SUCCESS] Simulation finished with exit code {res['exitCode']}")
    if res.get("score") is not None:
        logs.append(f"[SCORE] Final score: {res['score']:.2f} / 100")
    return logs
