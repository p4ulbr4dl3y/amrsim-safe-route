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

    # Автоматическая генерация и сохранение кастомных карт custom_map_WxH
    if scenario_id:
        import re

        sc_str = str(scenario_id).strip()
        sc_norm = sc_str[:-5] if sc_str.lower().endswith(".json") else sc_str
        m = re.match(r"^custom_map_(\d+)x(\d+)$", sc_norm, re.IGNORECASE)
        if m:
            w = max(20, min(500, int(m.group(1))))
            h = max(20, min(500, int(m.group(2))))
            center_y = h / 2.0
            lane_w = 10.0
            auto_scen = {
                "schema": "amr-1.0",
                "name": sc_norm,
                "description": f"Пользовательская карта {w}x{h}м с базовым проездом.",
                "dt": 0.1,
                "duration_s": 300.0,
                "hidden": False,
                "provide_detections": False,
                "weather": {"snow": False},
                "events": [],
                "start": {"x": 15.0, "y": center_y, "theta": 0.0},
                "missions": [
                    {
                        "id": "m1",
                        "from": "dock_start",
                        "to": "dock_end",
                        "deadline_s": 180.0,
                        "reference_length_m": max(10.0, w - 30.0),
                        "reference_path": [[15.0, center_y], [max(20.0, w - 15.0), center_y]],
                    }
                ],
                "map": {
                    "frame": "x east, y north, meters; heading radians from +x counterclockwise",
                    "bounds": [0, 0, w, h],
                    "drivable": [
                        [
                            [10.0, center_y - lane_w / 2.0],
                            [max(20.0, w - 10.0), center_y - lane_w / 2.0],
                            [max(20.0, w - 10.0), center_y + lane_w / 2.0],
                            [10.0, center_y + lane_w / 2.0],
                        ]
                    ],
                    "buildings": [],
                    "points": {
                        "dock_start": {
                            "x": 15.0,
                            "y": center_y,
                            "heading": 0.0,
                            "tol": 0.5,
                            "label": "Стартовый док",
                        },
                        "dock_end": {
                            "x": max(20.0, w - 15.0),
                            "y": center_y,
                            "heading": 0.0,
                            "tol": 0.5,
                            "label": "Целевой док",
                        },
                    },
                    "zones": [],
                    "gates": [],
                    "crossing": [],
                },
                "map_patches": [],
                "pedestrians": [],
            }
            _, target_p = save_scenario(auto_scen, scenario_id=sc_norm)
            return target_p

        # Если запрошен сценарий вида <base>_custom, используем базовый сценарий как основу
        if sc_norm.endswith("_custom"):
            base_id = sc_norm[:-7]
            base_file = get_scenario_file(base_id)
            if base_file and base_file.exists():
                try:
                    with open(base_file, "r", encoding="utf-8") as f:
                        base_json = json.load(f)
                    base_json["name"] = sc_norm
                    _, target_p = save_scenario(base_json, scenario_id=sc_norm)
                    return target_p
                except Exception:
                    pass

        # Если сценарий начинается с custom_, создаем стандартную карту 120x100
        if sc_norm.startswith("custom_"):
            return get_scenario_file("custom_map_120x100")

    return None


def heal_scenario_drivable_microgaps(
    drivable_polys: list[Any], max_gap: float = 0.35
) -> list[Any]:
    """Устраняет микрозазоры (< 0.35 м) между смежными прямоугольными полигонами дорог."""
    if not drivable_polys or len(drivable_polys) < 2:
        return drivable_polys
    res = [[[float(pt[0]), float(pt[1])] for pt in p] for p in drivable_polys]
    n = len(res)
    for i in range(n):
        p1 = res[i]
        if len(p1) != 4:
            continue
        xs1 = [pt[0] for pt in p1]
        ys1 = [pt[1] for pt in p1]
        minx1, maxx1 = min(xs1), max(xs1)
        miny1, maxy1 = min(ys1), max(ys1)
        for j in range(i + 1, n):
            p2 = res[j]
            if len(p2) != 4:
                continue
            xs2 = [pt[0] for pt in p2]
            ys2 = [pt[1] for pt in p2]
            minx2, maxx2 = min(xs2), max(xs2)
            miny2, maxy2 = min(ys2), max(ys2)

            x_ov = min(maxx1, maxx2) - max(minx1, minx2)
            if x_ov > 0.5:
                if 0.0 < miny2 - maxy1 <= max_gap:
                    mid = round((maxy1 + miny2) / 2.0, 4)
                    for pt in p1:
                        if abs(pt[1] - maxy1) < 1e-4:
                            pt[1] = mid
                    for pt in p2:
                        if abs(pt[1] - miny2) < 1e-4:
                            pt[1] = mid
                elif 0.0 < miny1 - maxy2 <= max_gap:
                    mid = round((maxy2 + miny1) / 2.0, 4)
                    for pt in p2:
                        if abs(pt[1] - maxy2) < 1e-4:
                            pt[1] = mid
                    for pt in p1:
                        if abs(pt[1] - miny1) < 1e-4:
                            pt[1] = mid

            y_ov = min(maxy1, maxy2) - max(miny1, miny2)
            if y_ov > 0.5:
                if 0.0 < minx2 - maxx1 <= max_gap:
                    mid = round((maxx1 + minx2) / 2.0, 4)
                    for pt in p1:
                        if abs(pt[0] - maxx1) < 1e-4:
                            pt[0] = mid
                    for pt in p2:
                        if abs(pt[0] - minx2) < 1e-4:
                            pt[0] = mid
                elif 0.0 < minx1 - maxx2 <= max_gap:
                    mid = round((maxx2 + minx1) / 2.0, 4)
                    for pt in p2:
                        if abs(pt[0] - maxx2) < 1e-4:
                            pt[0] = mid
                    for pt in p1:
                        if abs(pt[0] - minx1) < 1e-4:
                            pt[0] = mid
    return res


def sync_scenario_missions_with_points(scenario_dict: dict[str, Any]) -> None:
    """Синхронизирует опорный маршрут миссий с текущими координатами доков points."""
    map_data = scenario_dict.get("map")
    if not isinstance(map_data, dict):
        return
    points = map_data.get("points")
    if not isinstance(points, dict):
        return
    missions = scenario_dict.get("missions")
    if not isinstance(missions, list):
        return

    for m in missions:
        if not isinstance(m, dict):
            continue
        to_id = m.get("to")
        from_id = m.get("from")
        to_pt = points.get(to_id) if to_id else None
        from_pt = points.get(from_id) if from_id else None

        to_xy = [float(to_pt["x"]), float(to_pt["y"])] if (to_pt and "x" in to_pt and "y" in to_pt) else None
        from_xy = [float(from_pt["x"]), float(from_pt["y"])] if (from_pt and "x" in from_pt and "y" in from_pt) else None

        ref_path = m.get("reference_path")
        if not isinstance(ref_path, list) or len(ref_path) == 0:
            if from_xy and to_xy:
                m["reference_path"] = [from_xy, to_xy]
        else:
            new_path = [[float(p[0]), float(p[1])] for p in ref_path if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(new_path) >= 1 and to_xy:
                last_p = new_path[-1]
                if math.hypot(last_p[0] - to_xy[0], last_p[1] - to_xy[1]) > 0.1:
                    if len(new_path) <= 2:
                        new_path[-1] = to_xy
                    else:
                        new_path.append(to_xy)
            if len(new_path) >= 1 and from_xy:
                first_p = new_path[0]
                if math.hypot(first_p[0] - from_xy[0], first_p[1] - from_xy[1]) > 0.1:
                    new_path[0] = from_xy
            m["reference_path"] = new_path

        pts = m.get("reference_path", [])
        if len(pts) >= 2:
            length = sum(
                math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
                for k in range(1, len(pts))
            )
            m["reference_length_m"] = round(length, 2)


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

        # Лечение микроразрывов дорог и синхронизация миссий с доками
        if isinstance(raw_content.get("map"), dict) and "drivable" in raw_content["map"]:
            raw_content["map"]["drivable"] = heal_scenario_drivable_microgaps(
                raw_content["map"]["drivable"]
            )
        sync_scenario_missions_with_points(raw_content)

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

    # Обработка всех тактов: вычисление ошибки оценки позы pe_error
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
            # Если в сыром логе присутствуют лучи лидара (lidarRays), сохраняем их
            if "lidarRays" in t and isinstance(t["lidarRays"], list):
                t["lidarRays"] = t["lidarRays"]
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
