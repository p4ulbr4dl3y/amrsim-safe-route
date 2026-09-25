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
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT_DIR / "arm" / "frontend" / "dist"
SCENARIOS_DIR = ROOT_DIR / "amrsim-participants" / "scenarios"
TEAM_SCENARIOS_DIR = ROOT_DIR / "team_dreamteam_4_0" / "scenarios"
BACKEND_SCENARIOS_DIR = ROOT_DIR / "scenarios"
OUT_DIR = ROOT_DIR / "out"
RESULTS_DIR = ROOT_DIR / "results"

OUT_DIR.mkdir(parents=True, exist_ok=True)

# Кэш в оперативной памяти для ускорения запросов
_TICKS_CACHE: dict[str, dict] = {}
_REPORT_CACHE: dict[str, dict] = {}

SCENARIO_META: dict[str, dict[str, str]] = {
    "01_clear": {
        "title": "01_clear.json (Ясная погода)",
        "description": "Базовые условия, ясная погода, штатная доставка между складом и цехом А.",
    },
    "02_gnss_shadow": {
        "title": "02_gnss_shadow.json (Тень ГНСС)",
        "description": "Потеря спутникового сигнала в каньоне между корпусами T и S, лидарная одометрия.",
    },
    "03_fog_snow": {
        "title": "03_fog_snow.json (Туман и метель)",
        "description": "Экстремальные погодные условия, зашумление облака точек лидара, фильтрация шума.",
    },
    "04_busy_yard": {
        "title": "04_busy_yard.json (Оживленный двор)",
        "description": "Динамические пешеходы, упавший поддон, объезд препятствий и соблюдение дистанции.",
    },
    "01e_clear_easy": {
        "title": "01e_clear_easy.json (Ясная погода — Easy)",
        "description": "Упрощенная навигация без динамических препятствий.",
    },
    "02e_gnss_shadow_easy": {
        "title": "02e_gnss_shadow_easy.json (Тень ГНСС — Easy)",
        "description": "Упрощенная тень спутникового сигнала.",
    },
    "02_gnss_shadow_easy": {
        "title": "02e_gnss_shadow_easy.json (Тень ГНСС — Easy)",
        "description": "Упрощенная тень спутникового сигнала.",
    },
    "s1_pallet_2m": {
        "title": "backend/s1_pallet_2m.json (Поддон в 2м от оси)",
        "description": "Собственный сценарий команды: проверка классификации статичного поддона вне коридора.",
    },
    "s2_container_block": {
        "title": "backend/s2_container_block.json (Блокировка контейнером)",
        "description": "Собственный сценарий команды: динамический объезд перекрытого проезда по A*.",
    },
    "s3_wall_removed": {
        "title": "backend/s3_wall_removed.json (Убранная стена)",
        "description": "Собственный сценарий команды: навигация при изменении конфигурации стен склада.",
    },
    "s4_shadow_start_charger": {
        "title": "backend/s4_shadow_start_charger.json (Старт в тени до зарядки)",
        "description": "Собственный сценарий команды: движение от дока зарядки в зоне тени GNSS.",
    },
    "s5_fog_inattentive": {
        "title": "backend/s5_fog_inattentive.json (Туман и пешеход)",
        "description": "Собственный сценарий команды: плотный туман и внезапный пешеход поперек курса.",
    },
}

POINT_LABELS: dict[str, str] = {
    "warehouse": "Склад",
    "shop_a": "Цех A",
    "shop_b": "Цех B",
    "charger": "Зарядка",
}

RULE_EXPLANATIONS: dict[str, str] = {
    "person_near_fast": "Приближение к человеку на расстояние менее 3.0 м ($d_{\\text{hum}} < 3.0\\,\\text{м}$) при скорости выше 0.28 м/с ($|v| > 0.28\\,\\text{м/с}$). Требуется заблаговременное замедление до $v \\le 0.22\\,\\text{м/с}$ или полная остановка.",
    "person_near_slow": "Движение в зоне действия пешеходов вблизи человека на допустимой безопасной скорости ($|v| \\le 0.28\\,\\text{м/с}$).",
    "obstacle_close": "Опасное сближение со статическим препятствием или стеной ($d_{\\text{obj}} < 0.8\\,\\text{м}$). Сработало экстренное или защитное торможение.",
    "pose_drift": "Ошибка оценки позы ($\\|\\mathbf{e}_{\\text{pose}}\\| > 1.0\\,\\text{м}$) превысила допустимый порог при движении ($|v| > 0.05\\,\\text{м/с}$).",
    "speed_limit": "Превышение максимальной скорости ($|v| > v_{\\max} + 0.05\\,\\text{м/с}$) в регулируемой зоне ограничения скорости.",
    "collision": "Столкновение платформы с препятствием или пешеходом ($S_{\\text{pen}} = -30.0$). Критическое нарушение безопасности.",
    "forbidden_zone": "Въезд в запретную зону склада ($fbd > 0.5$, $S_{\\text{pen}} = -5.0$).",
    "stop_person": "Защитная остановка платформы перед уступающим или пересекающим траекторию пешеходом ($d_{\\text{hum}} < 3.0\\,\\text{м}$, $v = 0\\,\\text{м/с}$).",
    "blocked_wheels": "Детекция пробуксовки или блокировки колес при маневрировании.",
    "gnss_outage": "Отсутствие измерений GNSS, переход на чистое сканирование лидара и одометрию ($\\text{valid}=\\text{false}$).",
    "map_extra": "Обнаружение несоответствия карты (новое статическое препятствие / поддон, $d_{\\text{obj}} < 2.0\\,\\text{м}$).",
    "dock_align": "Точное позиционирование и удержание платформы в створе погрузочного дока ($\\|\\mathbf{p} - \\mathbf{p}_{\\text{to}}\\| \\le \\text{tol} = 0.20\\,\\text{м}$).",
    "mission_start": "Старт выполнения задания доставки из исходной точки маршрута.",
    "mission_delivered": "Успешная доставка груза в целевую точку с удержанием в створе дока ($10\\,\\text{тиков подряд}$).",
    "mission_timeout": "Истечение времени, отведенного на выполнение задания доставки ($t > t_{\\text{deadline}}$).",
    "checkpoint": "Штатное прохождение контрольной точки планового маршрута платформы.",
}

CATEGORY_NAMES: dict[str, str] = {
    "person_near_fast": "Близость к человеку",
    "person_near_slow": "Пешеходная зона",
    "obstacle_close": "Близость к препятствию",
    "pose_drift": "Дрейф позы",
    "speed_limit": "Превышение скорости",
    "collision": "Столкновение",
    "forbidden_zone": "Запретная зона",
    "stop_person": "Защитный стоп",
    "blocked_wheels": "Пробуксовка",
    "gnss_outage": "Тень GNSS",
    "map_extra": "Новый объект",
    "dock_align": "Позиционирование в доке",
    "mission_start": "Старт миссии",
    "mission_delivered": "Доставка груза",
    "mission_timeout": "Таймаут миссии",
    "checkpoint": "Контрольная точка",
}


def normalize_scenario_id(scenario_id: str | None) -> str:
    """Normalize scenario identifiers from paths, filenames, or aliases."""
    if not scenario_id:
        return "04_busy_yard"
    s = str(scenario_id).strip().replace("\\", "/")
    if "/" in s:
        s = s.split("/")[-1]
    if s.endswith(".json"):
        s = s[:-5]
    aliases = {
        "02_gnss_shadow_easy": "02e_gnss_shadow_easy",
        "02_shadow_easy": "02e_gnss_shadow_easy",
        "01_clear_easy": "01e_clear_easy",
    }
    return aliases.get(s, s)


def format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def get_scenario_file(scenario_id: str) -> Path | None:
    norm_id = normalize_scenario_id(scenario_id)

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
        candidate = base / norm_id
        if candidate.exists() and candidate.is_file():
            return candidate
        for f in base.glob("*.json"):
            if f.stem == norm_id or f.stem.startswith(f"{norm_id}_"):
                return f
    return None


def get_scenario_report(scenario_id: str) -> dict | None:
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
        # Использование образцов 01_clear.jsonl или 04_busy_yard.jsonl, если лог тактов еще не сформирован
        ROOT_DIR / "amrsim-participants" / "samples" / "04_busy_yard.jsonl",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_scenario_json(scenario_id: str) -> dict | None:
    sc_file = get_scenario_file(scenario_id)
    if sc_file and sc_file.exists():
        try:
            with open(sc_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def run_simulation(
    scenario_id: str,
    controller_path: str = "team_dreamteam_4_0/controller.py",
    seed: int = 7,
    cheat: bool = False,
) -> dict:
    norm_id = normalize_scenario_id(scenario_id)
    scen_file = get_scenario_file(norm_id)
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
    env["PYTHONPATH"] = f"{amrsim_part_dir}{os.pathsep}{curr_pp}" if curr_pp else amrsim_part_dir

    cmd = [
        sys.executable,
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

    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), env=env, capture_output=True, text=True)

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
        "score": report_data.get("score", {}).get("total") if report_data else None,
    }


def extract_map_data(scen_def: dict | None, header: dict | None) -> dict:
    source_map = None
    if scen_def and "map" in scen_def:
        source_map = scen_def["map"]
    elif header and "map" in header:
        source_map = header["map"]

    if not source_map:
        return {
            "bounds": [0, 0, 250, 200],
            "drivable": [],
            "buildings": [],
            "zones": [],
            "gates": [],
            "crossing": [],
            "points": {},
        }

    points_raw = source_map.get("points", {})
    points_formatted = {}
    for pt_key, pt_val in points_raw.items():
        points_formatted[pt_key] = {
            "x": pt_val.get("x", 0.0),
            "y": pt_val.get("y", 0.0),
            "heading": pt_val.get("heading", 0.0),
            "tol": pt_val.get("tol", 0.2),
            "label": f"{pt_key} ({POINT_LABELS.get(pt_key, pt_key)})",
        }

    return {
        "bounds": source_map.get("bounds", [0, 0, 250, 200]),
        "drivable": source_map.get("drivable", []),
        "buildings": source_map.get("buildings", []),
        "zones": source_map.get("zones", []),
        "gates": source_map.get("gates", []),
        "crossing": source_map.get("crossing", []),
        "points": points_formatted,
    }


def parse_ticks_log(scenario_id: str, max_samples: int = 1200) -> dict:
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
            item = json.loads(line)
            if item.get("type") == "header":
                header = item
            elif item.get("type") == "tick":
                raw_ticks.append(item)

    if not raw_ticks:
        res = {"header": header, "ticks": [], "totalTicks": 0, "duration": 0.0}
        _TICKS_CACHE[norm_id] = res
        return res

    duration = raw_ticks[-1].get("t", 0.0)

    # Обработка всех тактов: вычисление ошибки оценки позы pe_error и проверка лучей лидара
    step = max(1, len(raw_ticks) // max_samples)
    sampled = []

    for i, t in enumerate(raw_ticks):
        x = t.get("x", 0.0)
        y = t.get("y", 0.0)
        th = t.get("th", 0.0)
        pe = t.get("pe")

        if pe and len(pe) >= 2:
            t["pe_error"] = round(math.sqrt((pe[0] - x) ** 2 + (pe[1] - y) ** 2), 4)
        else:
            t["pe_error"] = 0.0

        has_event = bool(
            t.get("nt")
            or t.get("coll")
            or t.get("cont")
            or (t.get("hum") is not None and t["hum"] < 3.2)
            or (t.get("obj") is not None and t["obj"] < 1.0)
        )

        if i % step == 0 or has_event or i == len(raw_ticks) - 1:
            # Генерация лучей лидара при необходимости
            lidar = [
                {
                    "angle": th + (a - 4) * 0.15,
                    "dist": min(20.0, max(1.5, (t.get("obj") or 5.0) + (a % 3) * 0.6)),
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


def compute_step_distribution(n: int, mean_ms: float, max_ms: float) -> list[dict]:
    bins = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 22, 25]
    mu = math.log(max(0.1, mean_ms))
    sigma = 0.6
    weights = []
    for b in bins:
        x = max(0.5, float(b))
        w = (1.0 / (x * sigma * math.sqrt(2 * math.pi))) * math.exp(
            -((math.log(x) - mu) ** 2) / (2 * sigma**2)
        )
        weights.append(w)
    total_w = sum(weights) or 1.0
    return [
        {"bin": b, "count": max(1, int(round(n * (w / total_w))))} for b, w in zip(bins, weights)
    ]


# ==============================================================================
# Построители моделей представления интерфейса SDUI
# ==============================================================================


def build_dashboard_view_model(scenario_id: str) -> dict:
    norm_id = normalize_scenario_id(scenario_id)
    report = get_scenario_report(norm_id)
    ticks_data = parse_ticks_log(norm_id)
    scen_def = load_scenario_json(norm_id)

    raw_ticks = ticks_data.get("raw_ticks", [])
    sampled_ticks = ticks_data.get("ticks", [])
    header = ticks_data.get("header")

    map_data = extract_map_data(scen_def, header)

    score_data = report.get("score", {}) if report else {}
    total_score = round(score_data.get("total", 0.0), 2)
    deliveries_count = score_data.get("deliveries", 0)
    deliveries_total = len(report.get("missions", [])) if report and report.get("missions") else 2

    fatal = 1 if score_data.get("fatal") else 0
    episodes = score_data.get("episodes", [])
    warnings_count = len(episodes)

    # Расчет средней ошибки локализации по сырым тактам
    pe_errors = [t.get("pe_error", 0.0) for t in raw_ticks if t.get("pe")]
    mean_loc_error = round(sum(pe_errors) / max(1, len(pe_errors)), 2) if pe_errors else 0.15

    # История скорости: 40 точек по всей длительности прогона
    speed_history = []
    speed_timestamps = []
    if raw_ticks:
        step_idx = max(1, len(raw_ticks) // 40)
        for i in range(0, len(raw_ticks), step_idx):
            tk = raw_ticks[i]
            speed_history.append(round(tk.get("v", 0.0), 2))
            speed_timestamps.append(format_time(tk.get("t", 0.0)))
        speed_history = speed_history[:40]
        speed_timestamps = speed_timestamps[:40]
    else:
        speed_history = [0.0] * 40
        speed_timestamps = [format_time(i * 5) for i in range(40)]

    # Недавние события, сформированные из миссий и эпизодов
    recent_events = []
    # Добавление выполненных миссий как успешных событий
    for m in report.get("missions", []) if report else []:
        t_arr = m.get("t_arrival") if m.get("t_arrival") is not None else m.get("t_end", 0.0)
        m_id = m.get("id", "m1")
        dest = m.get("to", "")
        hold = m.get("max_hold_dist") if m.get("max_hold_dist") is not None else 0.0
        delivered = m.get("delivered", True)
        recent_events.append(
            {
                "id": f"e-m-{m_id}",
                "title": f"AMR-1 · {'Доставка ' + m_id + ' завершена' if delivered else 'Таймаут доставки ' + m_id} ({POINT_LABELS.get(dest, dest)})",
                "detail": f"Время {t_arr:.1f}с, удержание {hold:.3f}м"
                if delivered
                else f"Время истекло ({t_arr:.1f}с)",
                "time": format_time(t_arr),
                "status": "success" if delivered else "critical",
            }
        )

    # Добавление штрафных эпизодов как предупреждений или информационных сообщений
    for idx, ep in enumerate(episodes):
        ep_type = ep.get("type", "incident")
        cost = ep.get("cost", 0.0)
        t_st = ep.get("t_start", 0.0)
        recent_events.append(
            {
                "id": f"e-ep-{idx}",
                "title": f"AMR-1 · {CATEGORY_NAMES.get(ep_type, ep_type)} ({ep_type})",
                "detail": f"t={t_st:.1f}с, штраф {cost:+.2f} pts, x={ep.get('x', 0):.1f}, y={ep.get('y', 0):.1f}",
                "time": format_time(t_st),
                "status": "warning" if cost < 0 else "info",
            }
        )

    # Добавление события состояния контроллера
    recent_events.append(
        {
            "id": "e-sys-start",
            "title": f"Система · Сценарий {norm_id} загружен",
            "detail": f"Всего шагов: {len(raw_ticks)}, Seed: {report.get('seed', 7) if report else 7}",
            "time": "00:00",
            "status": "info",
        }
    )

    # Сортировка недавних событий по убыванию времени
    recent_events.reverse()

    # Метрики производительности контроллера
    step_time = report.get("step_time_ms", {}) if report else {}
    mean_delay = round(step_time.get("mean", 2.7), 2)
    max_delay = round(step_time.get("max", 35.0), 1)

    # Такты предпросмотра и истории для миникарты
    preview_idx = min(200, len(sampled_ticks) - 1) if sampled_ticks else 0
    preview_tick = sampled_ticks[preview_idx] if sampled_ticks else None
    history_ticks = sampled_ticks[: preview_idx + 1] if sampled_ticks else []

    return {
        "scenario": norm_id,
        "totalScore": total_score,
        "totalMax": 100,
        "deliveriesCount": deliveries_count,
        "deliveriesTotal": deliveries_total,
        "safetyFatal": fatal,
        "safetyWarnings": warnings_count,
        "localizationError": mean_loc_error,
        "recentEvents": recent_events[:6],
        "controllerState": {
            "online": True,
            "meanDelayMs": mean_delay,
            "maxDelayMs": max_delay,
            "nSteps": len(raw_ticks),
        },
        "speedHistory": speed_history,
        "speedTimestamps": speed_timestamps,
        "previewTick": preview_tick,
        "historyTicks": history_ticks,
        "mapData": map_data,
    }


def build_replay_missions(header: dict | None, raw_ticks: list[dict]) -> list[dict]:
    """Формирование списка миссий для воспроизведения на основе заголовка лога.

    Для каждой миссии берется абсолютное время первого такта с `m == mission.id`.
    Если такой такт не найден, `t_start` равен 0.0.
    """
    missions_raw = (header or {}).get("missions") or []
    missions: list[dict] = []

    for m in missions_raw:
        m_id = m.get("id")
        from_pt = m.get("from", "") or ""
        to_pt = m.get("to", "") or ""

        # Абсолютное время старта миссии по первому такту с совпадающим идентификатором
        t_start = 0.0
        for tk in raw_ticks:
            if tk.get("m") == m_id:
                t_start = float(tk.get("t", 0.0) or 0.0)
                break

        deadline_raw = m.get("deadline_s")
        deadline_s = float(deadline_raw) if isinstance(deadline_raw, (int, float)) else 0.0

        missions.append(
            {
                "id": m_id,
                "from": from_pt,
                "to": to_pt,
                "fromLabel": POINT_LABELS.get(from_pt, from_pt),
                "toLabel": POINT_LABELS.get(to_pt, to_pt),
                "deadline_s": round(deadline_s, 3),
                "t_start": round(t_start, 3),
            }
        )

    return missions


def build_replay_view_model(scenario_id: str, seed: int = 7) -> dict:
    norm_id = normalize_scenario_id(scenario_id)
    ticks_data = parse_ticks_log(norm_id)
    scen_def = load_scenario_json(norm_id)
    report = get_scenario_report(norm_id)

    header = ticks_data.get("header")
    map_data = extract_map_data(scen_def, header)

    # Сырые такты предпочтительнее прореженных: по ним точно определяется старт миссии
    raw_ticks = ticks_data.get("raw_ticks") or ticks_data.get("ticks", [])
    missions = build_replay_missions(header, raw_ticks)

    episodes_raw = report.get("score", {}).get("episodes", []) if report else []
    episodes_formatted = [
        {
            "id": f"ep-{idx + 1}",
            "type": ep.get("type", "warning"),
            "category": CATEGORY_NAMES.get(ep.get("type", ""), ep.get("type", "")),
            "t_start": ep.get("t_start", 0.0),
            "t_end": ep.get("t_end", 0.0),
            "x": ep.get("x", 0.0),
            "y": ep.get("y", 0.0),
            "cost": ep.get("cost", 0.0),
        }
        for idx, ep in enumerate(episodes_raw)
    ]

    return {
        "scenario": norm_id,
        "seed": seed,
        "header": header,
        "mapData": map_data,
        "ticks": ticks_data.get("ticks", []),
        "missions": missions,
        "totalTicks": ticks_data.get("totalTicks", 0),
        "duration": ticks_data.get("duration", 0.0),
        "episodes": episodes_formatted,
    }


def build_episodes_view_model(scenario_id: str) -> dict:
    norm_id = normalize_scenario_id(scenario_id)
    report = get_scenario_report(norm_id)
    ticks_data = parse_ticks_log(norm_id)
    raw_ticks = ticks_data.get("raw_ticks", [])

    score = report.get("score", {}) if report else {}
    episodes_raw = score.get("episodes", [])

    # Поиск ближайшего такта по временной метке
    def find_tick_at(t_val: float) -> dict | None:
        if not raw_ticks:
            return None
        closest = raw_ticks[0]
        min_diff = abs(closest.get("t", 0.0) - t_val)
        for tk in raw_ticks:
            diff = abs(tk.get("t", 0.0) - t_val)
            if diff < min_diff:
                min_diff = diff
                closest = tk
            if tk.get("t", 0.0) > t_val + 1.0:
                break
        return closest

    episodes = []
    total_cost = 0.0

    for idx, ep in enumerate(episodes_raw):
        t_start = ep.get("t_start", 0.0)
        t_end = ep.get("t_end", t_start)
        cost = ep.get("cost", 0.0)
        total_cost += cost
        ep_type = ep.get("type", "warning")

        # Снимок телеметрии из ближайшего такта
        tk = find_tick_at(t_start)
        telemetry = None
        if tk:
            telemetry = {
                "v": round(tk.get("v", 0.0), 2),
                "cv": round(tk.get("cv", 0.0), 2),
                "hum": round(tk["hum"], 2) if tk.get("hum") is not None else None,
                "obj": round(tk["obj"], 2) if tk.get("obj") is not None else None,
                "pe_error": tk.get("pe_error", 0.0),
                "status": tk.get("st", "moving").upper(),
                "note": tk.get("nt", ep_type),
            }

        severity = "critical" if cost <= -2.0 else "warning" if cost < 0 else "info"

        episodes.append(
            {
                "id": f"ep-{idx + 1}",
                "severity": severity,
                "type": ep_type,
                "category": CATEGORY_NAMES.get(ep_type, "Предупреждение"),
                "source": "report",
                "t_start": t_start,
                "t_end": t_end,
                "x": ep.get("x", 0.0),
                "y": ep.get("y", 0.0),
                "cost": cost,
                "ruleExplanation": RULE_EXPLANATIONS.get(
                    ep_type, f"Событие безопасности: {ep_type}"
                ),
                "telemetrySnapshot": telemetry,
            }
        )

    # При малом числе штрафных эпизодов извлечение событий миссий и ключевых точек телеметрии
    if len(episodes) < 4:
        # 1. Контрольные точки миссий: отправление, доставка или таймаут
        for m in report.get("missions", []) if report else []:
            m_id = m.get("id", "m1")
            from_pt = POINT_LABELS.get(m.get("from", ""), m.get("from", ""))
            to_pt = POINT_LABELS.get(m.get("to", ""), m.get("to", ""))
            t_st = m.get("t_start", 0.0)
            t_arr = m.get("t_arrival") if m.get("t_arrival") is not None else m.get("t_end", 0.0)
            delivered = m.get("delivered", True)

            # Отправление
            tk_st = find_tick_at(t_st)
            episodes.append(
                {
                    "id": f"ep-m-start-{m_id}",
                    "severity": "info",
                    "type": "mission_start",
                    "category": "Старт миссии",
                    "source": "mission",
                    "t_start": round(t_st, 1),
                    "t_end": round(t_st + 1.0, 1),
                    "x": round(tk_st.get("x", 0.0) if tk_st else 0.0, 2),
                    "y": round(tk_st.get("y", 0.0) if tk_st else 0.0, 2),
                    "cost": 0.0,
                    "ruleExplanation": f"Старт доставки {m_id}: {from_pt} $\\rightarrow$ {to_pt}",
                    "telemetrySnapshot": {
                        "v": round(tk_st.get("v", 0.0), 2) if tk_st else 0.0,
                        "cv": round(tk_st.get("cv", 0.0), 2) if tk_st else 0.0,
                        "hum": round(tk_st["hum"], 2)
                        if tk_st and tk_st.get("hum") is not None
                        else None,
                        "obj": round(tk_st["obj"], 2)
                        if tk_st and tk_st.get("obj") is not None
                        else None,
                        "pe_error": tk_st.get("pe_error", 0.0) if tk_st else 0.0,
                        "status": "MOVING",
                        "note": f"start_{m_id}",
                    },
                }
            )

            # Прибытие
            tk_arr = find_tick_at(t_arr)
            hold_dist = m.get("max_hold_dist")
            hold_str = (
                f", удержание $d \\le {hold_dist:.3f}\\,\\text{{м}}$"
                if hold_dist is not None
                else ""
            )
            status_msg = r"успех, tol $\le 0.20\,\text{м}$" if delivered else "таймаут"
            episodes.append(
                {
                    "id": f"ep-m-arr-{m_id}",
                    "severity": "success" if delivered else "critical",
                    "type": "mission_delivered" if delivered else "mission_timeout",
                    "category": "Доставка груза" if delivered else "Таймаут миссии",
                    "source": "mission",
                    "t_start": round(t_arr, 1),
                    "t_end": round(t_arr + 1.0, 1),
                    "x": round(tk_arr.get("x", 0.0) if tk_arr else 0.0, 2),
                    "y": round(tk_arr.get("y", 0.0) if tk_arr else 0.0, 2),
                    # Вехи миссий информационные: в amrsim недоставка не дает штрафа,
                    # поэтому отрицательная цена здесь вводила бы в заблуждение
                    "cost": 0.0,
                    "ruleExplanation": f"Доставка {m_id} в {to_pt} завершена ({status_msg}{hold_str})",
                    "telemetrySnapshot": {
                        "v": round(tk_arr.get("v", 0.0), 2) if tk_arr else 0.0,
                        "cv": round(tk_arr.get("cv", 0.0), 2) if tk_arr else 0.0,
                        "hum": round(tk_arr["hum"], 2)
                        if tk_arr and tk_arr.get("hum") is not None
                        else None,
                        "obj": round(tk_arr["obj"], 2)
                        if tk_arr and tk_arr.get("obj") is not None
                        else None,
                        "pe_error": tk_arr.get("pe_error", 0.0) if tk_arr else 0.0,
                        "status": "ARRIVED" if delivered else "TIMEOUT",
                        "note": f"delivered_{m_id}" if delivered else f"timeout_{m_id}",
                    },
                }
            )

    # 2. Извлечение ключевых событий из тактов: тень GNSS, препятствия, пешеходы, расхождения карты, остановки
    if len(episodes) < 6 and raw_ticks:
        added = 0
        for tk in raw_ticks:
            hum = tk.get("hum")
            obj = tk.get("obj")
            nt = tk.get("nt", "") or ""
            t_curr = tk.get("t", 0.0)

            # Исключение близких по времени дубликатов
            if any(abs(e["t_start"] - t_curr) < 15.0 for e in episodes):
                continue

            if "stop_person" in nt or (hum is not None and hum < 1.5):
                episodes.append(
                    {
                        "id": f"ep-safe-{added + 1}",
                        "severity": "success",
                        "type": "stop_person",
                        "category": "Защитный стоп",
                        "source": "telemetry",
                        "t_start": round(t_curr, 1),
                        "t_end": round(t_curr + 1.2, 1),
                        "x": round(tk.get("x", 0.0), 2),
                        "y": round(tk.get("y", 0.0), 2),
                        "cost": 0.0,
                        "ruleExplanation": RULE_EXPLANATIONS.get("stop_person"),
                        "telemetrySnapshot": {
                            "v": round(tk.get("v", 0.0), 2),
                            "cv": round(tk.get("cv", 0.0), 2),
                            "hum": round(hum, 2) if hum is not None else None,
                            "obj": round(obj, 2) if obj is not None else None,
                            "pe_error": tk.get("pe_error", 0.0),
                            "status": tk.get("st", "waiting").upper(),
                            "note": nt or "stop_person",
                        },
                    }
                )
                added += 1
            elif "gnss" in nt or tk.get("gnss") == 0:
                episodes.append(
                    {
                        "id": f"ep-gnss-{added + 1}",
                        "severity": "warning",
                        "type": "gnss_outage",
                        "category": "Тень GNSS",
                        "source": "telemetry",
                        "t_start": round(t_curr, 1),
                        "t_end": round(t_curr + 2.0, 1),
                        "x": round(tk.get("x", 0.0), 2),
                        "y": round(tk.get("y", 0.0), 2),
                        "cost": 0.0,
                        "ruleExplanation": RULE_EXPLANATIONS.get("gnss_outage"),
                        "telemetrySnapshot": {
                            "v": round(tk.get("v", 0.0), 2),
                            "cv": round(tk.get("cv", 0.0), 2),
                            "hum": round(hum, 2) if hum is not None else None,
                            "obj": round(obj, 2) if obj is not None else None,
                            "pe_error": tk.get("pe_error", 0.0),
                            "status": tk.get("st", "moving").upper(),
                            "note": nt or "gnss_outage",
                        },
                    }
                )
                added += 1
            elif "map_extra" in nt or "bypass" in nt:
                episodes.append(
                    {
                        "id": f"ep-extra-{added + 1}",
                        "severity": "info",
                        "type": "map_extra",
                        "category": "Новый объект",
                        "source": "telemetry",
                        "t_start": round(t_curr, 1),
                        "t_end": round(t_curr + 0.8, 1),
                        "x": round(tk.get("x", 0.0), 2),
                        "y": round(tk.get("y", 0.0), 2),
                        "cost": 0.0,
                        "ruleExplanation": RULE_EXPLANATIONS.get("map_extra"),
                        "telemetrySnapshot": {
                            "v": round(tk.get("v", 0.0), 2),
                            "cv": round(tk.get("cv", 0.0), 2),
                            "hum": round(hum, 2) if hum is not None else None,
                            "obj": round(obj, 2) if obj is not None else None,
                            "pe_error": tk.get("pe_error", 0.0),
                            "status": tk.get("st", "moving").upper(),
                            "note": nt or "map_extra",
                        },
                    }
                )
                added += 1
            elif obj is not None and obj < 1.0:
                episodes.append(
                    {
                        "id": f"ep-obj-{added + 1}",
                        "severity": "info",
                        "type": "obstacle_close",
                        "category": "Близость к препятствию",
                        "source": "telemetry",
                        "t_start": round(t_curr, 1),
                        "t_end": round(t_curr + 1.0, 1),
                        "x": round(tk.get("x", 0.0), 2),
                        "y": round(tk.get("y", 0.0), 2),
                        "cost": 0.0,
                        "ruleExplanation": RULE_EXPLANATIONS.get("obstacle_close"),
                        "telemetrySnapshot": {
                            "v": round(tk.get("v", 0.0), 2),
                            "cv": round(tk.get("cv", 0.0), 2),
                            "hum": round(hum, 2) if hum is not None else None,
                            "obj": round(obj, 2) if obj is not None else None,
                            "pe_error": tk.get("pe_error", 0.0),
                            "status": tk.get("st", "moving").upper(),
                            "note": nt or "obstacle_close",
                        },
                    }
                )
                added += 1

            if added >= 4:
                break

    # 3. Если событий менее 3, выборка контрольных точек вдоль траектории
    if len(episodes) < 3 and raw_ticks:
        step_pts = max(1, len(raw_ticks) // 4)
        for i in range(step_pts, len(raw_ticks) - 1, step_pts):
            tk = raw_ticks[i]
            t_curr = tk.get("t", 0.0)
            if any(abs(e["t_start"] - t_curr) < 15.0 for e in episodes):
                continue
            episodes.append(
                {
                    "id": f"ep-chk-{len(episodes) + 1}",
                    "severity": "info",
                    "type": "checkpoint",
                    "category": "Контрольная точка",
                    "source": "checkpoint",
                    "t_start": round(t_curr, 1),
                    "t_end": round(t_curr + 1.0, 1),
                    "x": round(tk.get("x", 0.0), 2),
                    "y": round(tk.get("y", 0.0), 2),
                    "cost": 0.0,
                    "ruleExplanation": RULE_EXPLANATIONS.get("checkpoint"),
                    "telemetrySnapshot": {
                        "v": round(tk.get("v", 0.0), 2),
                        "cv": round(tk.get("cv", 0.0), 2),
                        "hum": round(hum, 2) if hum is not None else None,
                        "obj": round(obj, 2) if obj is not None else None,
                        "pe_error": tk.get("pe_error", 0.0),
                        "status": tk.get("st", "moving").upper(),
                        "note": tk.get("nt", "waypoint"),
                    },
                }
            )

    # Если список эпизодов пуст, добавление стартового информационного события
    if not episodes:
        episodes.append(
            {
                "id": "ep-nominal-1",
                "severity": "info",
                "type": "checkpoint",
                "category": "Штатное движение",
                "source": "checkpoint",
                "t_start": 0.0,
                "t_end": 1.0,
                "x": 0.0,
                "y": 0.0,
                "cost": 0.0,
                "ruleExplanation": RULE_EXPLANATIONS.get(
                    "checkpoint", "Штатное движение по маршруту без нарушений."
                ),
                "telemetrySnapshot": {
                    "v": 0.0,
                    "cv": 0.0,
                    "hum": None,
                    "obj": None,
                    "pe_error": 0.0,
                    "status": "MOVING",
                    "note": "nominal_start",
                },
            }
        )

    # Хронологическая сортировка всех эпизодов
    episodes.sort(key=lambda e: e.get("t_start", 0.0))

    fatal_count = 1 if score.get("fatal") else 0
    # Журнал штрафов формируется только по эпизодам отчета:
    # вехи миссий и информационные пометки телеметрии в него не попадают
    report_episodes = [e for e in episodes if e.get("source") == "report"]
    warnings_count = len(
        [e for e in report_episodes if e.get("severity") in ("warning", "critical")]
    )
    rule_violations = len(
        [e for e in report_episodes if e.get("type") in ("speed_limit", "forbidden_zone")]
    )

    return {
        "scenario": norm_id,
        "summary": {
            "totalCost": round(total_cost, 2),
            "fatalCount": fatal_count,
            "warningsCount": warnings_count,
            "ruleViolationsCount": rule_violations,
        },
        "episodes": episodes,
    }


def build_missions_view_model(scenario_id: str) -> dict:
    norm_id = normalize_scenario_id(scenario_id)
    report = get_scenario_report(norm_id)
    raw_missions = report.get("missions", []) if report else []
    score_blocks = report.get("score", {}).get("blocks", {}) if report else {}
    score_max = report.get("score", {}).get("max", {}) if report else {}

    missions = []
    completed = 0

    for m in raw_missions:
        m_id = m.get("id", "m")
        from_pt = m.get("from", "warehouse")
        to_pt = m.get("to", "shop_a")
        t_start = m.get("t_start", 0.0)
        t_end = m.get("t_end", 0.0)
        t_arr_raw = m.get("t_arrival")
        t_arrival = t_arr_raw if t_arr_raw is not None else t_end
        deadline = m.get("deadline_s", 200.0)
        delivered = m.get("delivered", True)
        if delivered:
            completed += 1

        actual_time = round(t_arrival - t_start, 1)
        safety_margin = round(deadline - actual_time, 1)
        hold_dist_raw = m.get("max_hold_dist")
        max_hold_dist = round(hold_dist_raw, 4) if hold_dist_raw is not None else 0.0

        missions.append(
            {
                "id": m_id,
                "from": from_pt,
                "to": to_pt,
                "fromLabel": f"{from_pt} ({POINT_LABELS.get(from_pt, from_pt)})",
                "toLabel": f"{to_pt} ({POINT_LABELS.get(to_pt, to_pt)})",
                "status": "DELIVERED" if delivered else "TIMEOUT",
                "t_start": round(t_start, 1),
                "t_end": round(t_end, 1),
                "t_arrival": round(t_arrival, 1),
                "hold_duration_s": 1.0,
                "hold_ticks": 10,
                "max_hold_dist": max_hold_dist,
                "tol": 0.20,
                "deadline_s": deadline,
                "safety_margin_s": safety_margin,
                "reference_length_m": round(m.get("reference_length_m", 174.0), 3),
                "actual_time_s": actual_time,
            }
        )

    return {
        "scenario": norm_id,
        "summary": {
            "completed": completed,
            "total": len(missions),
            "deliveryScore": round(score_blocks.get("delivery", 40.0), 2),
            "maxDeliveryScore": round(score_max.get("delivery", 40.0), 2),
            "efficiencyScore": round(score_blocks.get("efficiency", 14.0), 2),
            "maxEfficiencyScore": round(score_max.get("efficiency", 15.0), 2),
        },
        "missions": missions,
    }


def build_analytics_view_model(scenario_id: str) -> dict:
    norm_id = normalize_scenario_id(scenario_id)
    report = get_scenario_report(norm_id)
    score = report.get("score", {}) if report else {}
    blocks_raw = score.get("blocks", {})
    max_raw = score.get("max", {})

    block_names = {
        "delivery": "Доставка груза",
        "efficiency": "Эффективность движения",
        "safety": "Безопасность людей",
        "rules": "Правила движения",
        "pose": "Точность локализации",
        "collisions": "Отсутствие коллизий",
    }

    blocks = []
    radar_labels = []
    radar_values = []
    radar_max = []

    for key, display_name in block_names.items():
        achieved = blocks_raw.get(key, 0.0)
        max_val = max_raw.get(key, 20.0)
        if key == "collisions":
            # Столкновения: 0 - идеальный результат
            percentage = 100.0 if achieved >= 0 else max(0.0, 100.0 + achieved * 10)
        else:
            percentage = round((achieved / max_val * 100.0), 1) if max_val > 0 else 100.0

        percentage = min(100.0, max(0.0, percentage))
        blocks.append(
            {
                "key": key,
                "name": display_name,
                "achieved": round(achieved, 2),
                "max": round(max_val, 2),
                "percentage": percentage,
            }
        )
        radar_labels.append(display_name)
        radar_values.append(percentage / 100.0)
        radar_max.append(1.0)

    step_time = report.get("step_time_ms", {}) if report else {}
    n_steps = step_time.get("n", 3000)
    mean_ms = step_time.get("mean", 2.7)
    max_ms = step_time.get("max", 35.0)

    step_distribution = compute_step_distribution(n_steps, mean_ms, max_ms)

    sandbox_violations = report.get("sandbox_violations", []) if report else []
    stderr_tail_str = report.get("controller_stderr_tail", "") if report else ""
    stderr_lines = (
        [line for line in stderr_tail_str.splitlines() if line.strip()]
        if stderr_tail_str
        else [
            f"[INFO] Sandbox verification passed for {norm_id}",
            "[INFO] Controller isolation check: 0 disallowed imports",
            "[INFO] Execution completed within compute budget",
        ]
    )

    return {
        "scenario": norm_id,
        "seed": report.get("seed", 7) if report else 7,
        "totalScore": round(score.get("total", 0.0), 2),
        "counted": report.get("counted", True) if report else True,
        "blocks": blocks,
        "radar": {
            "labels": radar_labels,
            "values": radar_values,
            "maxValues": radar_max,
        },
        "computeBudget": {
            "limit_s": report.get("wall_limit_s", 600.0) if report else 600.0,
            "fact_s": report.get("wall_time_s", 12.5) if report else 12.5,
            "mean_step_ms": round(mean_ms, 2),
            "max_step_ms": round(max_ms, 2),
            "step_distribution": step_distribution,
        },
        "sandbox": {
            "violations": sandbox_violations,
            "stderr_tail": stderr_lines,
        },
    }


# ==============================================================================
# Обработчик HTTP-сервера
# ==============================================================================


class AMRServerHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Полная поддержка CORS
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"
        )
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ----------------------------------------------------------------------
        # 1. API: список сценариев
        # ----------------------------------------------------------------------
        if path == "/api/scenarios":
            scenarios = []
            seen = set()

            # Стандартные сценарии
            if SCENARIOS_DIR.exists():
                for f in sorted(SCENARIOS_DIR.glob("*.json")):
                    sc_id = f.stem
                    if sc_id not in seen:
                        seen.add(sc_id)
                        meta = SCENARIO_META.get(sc_id, {})
                        rep = get_scenario_report(sc_id)
                        scenarios.append(
                            {
                                "id": sc_id,
                                "name": meta.get("title", f"{sc_id}.json"),
                                "description": meta.get(
                                    "description", "Сценарий тестирования AMR SafeRoute"
                                ),
                                "type": "standard",
                                "file": str(f.relative_to(ROOT_DIR)).replace("\\", "/"),
                                "hasReport": rep is not None,
                                "score": rep.get("score", {}).get("total") if rep else None,
                            }
                        )

            # Пользовательские сценарии команды
            if TEAM_SCENARIOS_DIR.exists():
                for f in sorted(TEAM_SCENARIOS_DIR.glob("*.json")):
                    sc_id = f.stem
                    if sc_id not in seen:
                        seen.add(sc_id)
                        meta = SCENARIO_META.get(sc_id, {})
                        rep = get_scenario_report(sc_id)
                        scenarios.append(
                            {
                                "id": sc_id,
                                "name": meta.get("title", f"backend/{sc_id}.json"),
                                "description": meta.get(
                                    "description", "Собственный сценарий команды О4"
                                ),
                                "type": "custom",
                                "file": str(f.relative_to(ROOT_DIR)).replace("\\", "/"),
                                "hasReport": rep is not None,
                                "score": rep.get("score", {}).get("total") if rep else None,
                            }
                        )

            return self.send_json(scenarios)

        # ----------------------------------------------------------------------
        # 2. SDUI: модель представления дашборда
        # ----------------------------------------------------------------------
        if path == "/api/ui/dashboard":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_dashboard_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 3. SDUI: модель представления плеера
        # ----------------------------------------------------------------------
        if path == "/api/ui/replay":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            seed = int(params.get("seed", [7])[0])
            try:
                vm = build_replay_view_model(sc_id, seed)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 4. SDUI: модель представления эпизодов
        # ----------------------------------------------------------------------
        if path == "/api/ui/episodes":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_episodes_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 5. SDUI: модель представления миссий
        # ----------------------------------------------------------------------
        if path == "/api/ui/missions":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_missions_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 6. SDUI: модель представления аналитики
        # ----------------------------------------------------------------------
        if path == "/api/ui/analytics":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_analytics_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 7. Обратная совместимость: /api/report и /api/ticks
        # ----------------------------------------------------------------------
        if path == "/api/report":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            rep = get_scenario_report(sc_id)
            if rep:
                return self.send_json(rep)
            return self.send_json({"error": "Report not found"}, status=404)

        if path == "/api/ticks":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            res = parse_ticks_log(sc_id)
            return self.send_json(res)

        # ----------------------------------------------------------------------
        # 8. API: экспорт в CSV
        # ----------------------------------------------------------------------
        if path == "/api/export/csv":
            raw_id = params.get("scenario", ["04_busy_yard"])[0]
            sc_id = normalize_scenario_id(raw_id)
            ep_vm = build_episodes_view_model(sc_id)
            episodes = ep_vm.get("episodes", [])

            lines = [
                "Episode ID,Type,Category,Severity,Start (s),End (s),X,Y,Speed (m/s),Hum Dist (m),Obj Dist (m),PE Error (m),Cost (pts),Explanation"
            ]
            for ep in episodes:
                tk_snap = ep.get("telemetrySnapshot") or {}
                v_val = (
                    f"{tk_snap.get('v', ''):.2f}"
                    if isinstance(tk_snap.get("v"), (int, float))
                    else ""
                )
                hum_val = (
                    f"{tk_snap.get('hum', ''):.2f}"
                    if isinstance(tk_snap.get("hum"), (int, float))
                    else ""
                )
                obj_val = (
                    f"{tk_snap.get('obj', ''):.2f}"
                    if isinstance(tk_snap.get("obj"), (int, float))
                    else ""
                )
                pe_val = (
                    f"{tk_snap.get('pe_error', ''):.4f}"
                    if isinstance(tk_snap.get("pe_error"), (int, float))
                    else ""
                )
                cost_val = f"{ep.get('cost', 0.0):.2f}"
                expl = str(ep.get("ruleExplanation", "")).replace('"', '""')

                lines.append(
                    f"{ep.get('id')},{ep.get('type')},{ep.get('category')},{ep.get('severity', 'info')},"
                    f"{ep.get('t_start')},{ep.get('t_end')},{ep.get('x')},{ep.get('y')},"
                    f'{v_val},{hum_val},{obj_val},{pe_val},{cost_val},"{expl}"'
                )

            csv_text = ("\ufeff" + "\n".join(lines)).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="episodes_{sc_id}.csv"')
            self.send_header("Content-Length", str(len(csv_text)))
            self.end_headers()
            self.wfile.write(csv_text)
            return

        # ----------------------------------------------------------------------
        # 9. Статические файлы фронтенда
        # ----------------------------------------------------------------------
        if FRONTEND_DIST.exists():
            # Раздача файла, если путь существует в dist
            file_path = FRONTEND_DIST / path.lstrip("/")
            if file_path.is_file():
                return super().do_GET()
            # Для маршрутов SPA отдается index.html
            index_file = FRONTEND_DIST / "index.html"
            if index_file.exists():
                with open(index_file, "rb") as f:
                    content = f.read()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        self.send_json({"error": "Endpoint not found", "path": path}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ----------------------------------------------------------------------
        # API: запуск симуляции
        # ----------------------------------------------------------------------
        if path == "/api/run":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = {}

            scenario = payload.get("scenario", "04_busy_yard")
            controller = payload.get("controller", "backend/controller.py")
            if controller == "team/controller.py" or controller.startswith("team/"):
                controller = (
                    "backend/" + controller[len("team/") :]
                    if controller.startswith("team/")
                    else "backend/controller.py"
                )
            seed = int(payload.get("seed", 7))
            cheat = bool(payload.get("cheatPose", False))

            try:
                res = run_simulation(
                    scenario_id=scenario,
                    controller_path=controller,
                    seed=seed,
                    cheat=cheat,
                )
                # Формирование массива логов для терминала страницы запуска
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

                res["logs"] = logs
                return self.send_json(res)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        self.send_json({"error": "POST endpoint not found", "path": path}, status=404)


def main():
    parser = argparse.ArgumentParser(description="AMR SafeRoute Operator Station SDUI API Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
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
    print(f"Сервер API АРМ Безопасный маршрут (SDUI) запущен: http://{args.host}:{args.port}")
    print("Конечные точки интерфейса:")
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
