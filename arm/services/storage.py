"""Storage service for AMR scenarios, reports, and execution logs."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from arm.core import config
from arm.core.config import (
    BoundedCache,
    _safe_float,
    normalize_scenario_id,
)

# Module-level references for monkeypatching support
ROOT_DIR: Path = config.ROOT_DIR
OUT_DIR: Path = config.OUT_DIR
RESULTS_DIR: Path = config.RESULTS_DIR
SCENARIOS_DIR: Path = config.SCENARIOS_DIR
TEAM_SCENARIOS_DIR: Path = config.TEAM_SCENARIOS_DIR
BACKEND_SCENARIOS_DIR: Path = config.BACKEND_SCENARIOS_DIR
_TICKS_CACHE: BoundedCache = config._TICKS_CACHE
_REPORT_CACHE: BoundedCache = config._REPORT_CACHE


def get_scenario_file(scenario_id: str | None) -> Path | None:
    norm_id = normalize_scenario_id(scenario_id)

    if not scenario_id:
        for base in [SCENARIOS_DIR, TEAM_SCENARIOS_DIR, BACKEND_SCENARIOS_DIR]:
            if not base.exists():
                continue
            candidate = base / f"{norm_id}.json"
            if candidate.exists():
                return candidate
            candidate = base / norm_id
            if candidate.exists() and candidate.is_file():
                return candidate
            for f in base.glob("*.json"):
                if f.stem == norm_id or f.stem.startswith(f"{norm_id}_"):
                    return f
        return None

    # Проверка прямого пути к файлу при наличии
    raw_p = Path(scenario_id)
    if raw_p.is_file() and raw_p.exists():
        return raw_p
    rel_p = ROOT_DIR / scenario_id
    if rel_p.is_file() and rel_p.exists():
        return rel_p

    # Перенаправление backend/ в team/ при наличии
    if str(scenario_id).startswith("backend/"):
        mapped = ROOT_DIR / ("team/" + str(scenario_id)[len("backend/") :])
        if mapped.is_file() and mapped.exists():
            return mapped

    # Поиск в каталогах стандартных, командных сценариев и сценариев бэкенда
    for base in [SCENARIOS_DIR, TEAM_SCENARIOS_DIR, BACKEND_SCENARIOS_DIR]:
        if not base.exists():
            continue
        candidate = base / f"{norm_id}.json"
        if candidate.exists():
            return candidate
        if scenario_id:
            candidate2 = base / f"{scenario_id}.json"
            if candidate2.exists():
                return candidate2
        candidate = base / norm_id
        if candidate.exists() and candidate.is_file():
            return candidate
        for f in base.glob("*.json"):
            if (
                f.stem == norm_id
                or f.stem.lower() == norm_id.lower()
                or (scenario_id and f.stem.lower() == str(scenario_id).lower())
                or f.stem.startswith(f"{norm_id}_")
            ):
                return f
    return None


def save_scenario(data: dict[str, Any], scenario_id: str | None = None) -> tuple[str, Path]:
    """Сохраняет сценарий на диск в scenarios/<id>.json."""
    raw_content = data
    if isinstance(data, dict):
        if "scenario" in data and isinstance(data["scenario"], dict):
            raw_content = data["scenario"]
        elif "data" in data and isinstance(data["data"], dict):
            raw_content = data["data"]

    # Определение идентификатора сценария
    sc_id = scenario_id or (data.get("id") if isinstance(data, dict) else None)
    if not sc_id and isinstance(raw_content, dict):
        sc_id = raw_content.get("id") or raw_content.get("name")
    if not sc_id:
        sc_id = "custom_scenario"

    sc_id = str(sc_id).strip()
    if sc_id.endswith(".json"):
        sc_id = sc_id[:-5]

    # Нормализация имени файла: замена недопустимых символов
    safe_name = "".join(c if (c.isalnum() or c in ("_", "-")) else "_" for c in sc_id).strip("_")
    if not safe_name:
        safe_name = "custom_scenario"

    target_dir = ROOT_DIR / "scenarios"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{safe_name}.json"

    # Гарантируем обязательные поля amr-1.0 при сохранении
    if isinstance(raw_content, dict):
        if "schema" not in raw_content:
            raw_content["schema"] = "amr-1.0"
        if "name" not in raw_content:
            raw_content["name"] = safe_name

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(raw_content, f, ensure_ascii=False, indent=2)

    return safe_name, target_path


def get_scenario_report(scenario_id: str) -> dict[str, Any] | None:
    norm_id = normalize_scenario_id(scenario_id)
    if norm_id in _REPORT_CACHE:
        return _REPORT_CACHE[norm_id]

    candidates = [
        OUT_DIR / f"{norm_id}.json",
        RESULTS_DIR / f"team_dreamteam_4_0_{norm_id}.json",
        RESULTS_DIR / "seed_packet" / f"{norm_id}_7.json",
        RESULTS_DIR / f"baseline_{norm_id}.json",
        RESULTS_DIR / "own_scenarios" / f"{norm_id}.json",
        RESULTS_DIR / "table_runs" / "reports" / f"team_dreamteam_4_0__{norm_id}__s7.json",
        RESULTS_DIR / "table_runs" / "reports" / f"team__{norm_id}__s7.json",
        OUT_DIR / "table_runs" / "reports" / f"team_dreamteam_4_0__{norm_id}__s7.json",
        OUT_DIR / "table_runs" / "reports" / f"team__{norm_id}__s7.json",
        ROOT_DIR / "amrsim-participants" / "samples" / f"{norm_id}.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        return None
                    _REPORT_CACHE[norm_id] = data
                    return data
            except Exception:
                pass
    return None


def get_scenario_log_path(scenario_id: str) -> Path | None:
    norm_id = normalize_scenario_id(scenario_id)
    candidates = [
        OUT_DIR / f"{norm_id}.jsonl",
        OUT_DIR / f"team_{norm_id}.jsonl",
        OUT_DIR / f"team_dreamteam_4_0_{norm_id}.jsonl",
        OUT_DIR / "table_runs" / "logs" / f"team_dreamteam_4_0__{norm_id}__s7.jsonl",
        OUT_DIR / "table_runs" / "logs" / f"team__{norm_id}__s7.jsonl",
        RESULTS_DIR / "table_runs" / "logs" / f"team_dreamteam_4_0__{norm_id}__s7.jsonl",
        # Собственные сценарии: логи в сдаче, чтобы подпись миссии бралась из своего лога
        ROOT_DIR / "results" / "own_scenarios" / "logs" / f"{norm_id}.jsonl",
        ROOT_DIR / "amrsim-participants" / "samples" / f"{norm_id}.jsonl",
    ]
    for p in candidates:
        if p.exists():
            return p
    if norm_id in ("01e_clear_easy", "02e_gnss_shadow_easy"):
        base_id = "01_clear" if "01" in norm_id else "02_gnss_shadow"
        res = get_scenario_log_path(base_id)
        if res:
            return res

    # Неизвестный сценарий: лог не подставляется
    if get_scenario_file(norm_id) is None:
        return None

    # Использование образцов логов для известных сценариев, если лог еще не сформирован
    for sample_name in ("01_clear.jsonl", "04_busy_yard.jsonl"):
        sample_path = ROOT_DIR / "amrsim-participants" / "samples" / sample_name
        if sample_path.exists():
            return sample_path
    return None


def load_scenario_json(scenario_id: str) -> dict[str, Any] | None:
    sc_file = get_scenario_file(scenario_id)
    if sc_file and sc_file.exists():
        try:
            with open(sc_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def parse_ticks_log(scenario_id: str, max_samples: int = 1200) -> dict[str, Any]:
    norm_id = normalize_scenario_id(scenario_id)
    if norm_id in _TICKS_CACHE:
        return _TICKS_CACHE[norm_id]

    log_path = get_scenario_log_path(norm_id)
    if not log_path or not log_path.exists():
        return {"header": None, "ticks": [], "totalTicks": 0, "duration": 0.0}

    header = None
    raw_ticks = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "header":
                header = item
            elif item.get("type") == "tick":
                raw_ticks.append(item)

    if not raw_ticks:
        res = {"header": header, "ticks": [], "totalTicks": 0, "duration": 0.0}
        _TICKS_CACHE[norm_id] = res
        return res

    duration = _safe_float(raw_ticks[-1].get("t"), 0.0)

    # Обработка всех тактов: вычисление ошибки оценки позы pe_error и проверка лучей лидара
    step = max(1, len(raw_ticks) // max_samples)
    sampled = []

    for i, t in enumerate(raw_ticks):
        x = _safe_float(t.get("x"), 0.0)
        y = _safe_float(t.get("y"), 0.0)
        pe = t.get("pe")

        if pe and isinstance(pe, (list, tuple)) and len(pe) >= 2:
            pe_0 = _safe_float(pe[0], 0.0)
            pe_1 = _safe_float(pe[1], 0.0)
            t["pe_error"] = round(math.sqrt((pe_0 - x) ** 2 + (pe_1 - y) ** 2), 4)
        else:
            t["pe_error"] = 0.0

        hum_val = _safe_float(t.get("hum"), 999.0) if t.get("hum") is not None else 999.0
        obj_val = _safe_float(t.get("obj"), 999.0) if t.get("obj") is not None else 999.0

        has_event = bool(
            t.get("nt")
            or t.get("coll")
            or t.get("cont")
            or (t.get("hum") is not None and hum_val < 3.2)
            or (t.get("obj") is not None and obj_val < 1.0)
        )

        if i % step == 0 or has_event or i == len(raw_ticks) - 1:
            # Генерация лучей лидара (относительные углы лучей в СК робота, 0 = вперед)
            obj_dist = _safe_float(t.get("obj"), 5.0)
            lidar = [
                {
                    "angle": (a - 4) * 0.15,
                    "dist": min(20.0, max(1.5, obj_dist + (a % 3) * 0.6)),
                }
                for a in range(9)
            ]
            t["lidarRays"] = lidar
            sampled.append(t)

    res = {
        "header": header,
        "ticks": sampled,
        "raw_ticks": raw_ticks,
        "totalTicks": len(raw_ticks),
        "duration": duration,
    }
    _TICKS_CACHE[norm_id] = res
    return res
