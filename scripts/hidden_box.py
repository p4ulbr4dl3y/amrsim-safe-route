#!/usr/bin/env python3
"""Генератор скрытых сценариев и фильтр допуска (Контур B).

Правила:
- генерация скрытых сценариев по рамке amrsim-participants/docs/DATA.md;
- базовая карта из scenarios/01_clear.json;
- вариации плеч через amrsim.planner.dock_route с clearance 1.4 м;
- вариации теней ГНСС: длинная 120-135 м (корпус и навес B) или северный проезд 76-126 м;
- препятствия: dropped object или map_patches add около 2 м от оси, map_patches remove;
- пешеходы: attentive/inattentive, пересечения оси, туман, появление у дока;
- погода: сухая, snow, fog_bank, snow + fog;
- фильтр допуска:
  - оракул (baseline --cheat, seed 7): total > 85 и deliveries >= 1;
  - baseline без --cheat (seed 7): total < 70 или deliveries < len(missions);
  - допущенным ставить generator.status = "accepted", hidden = true.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
PARTICIPANTS_PATH = REPO_ROOT / "amrsim-participants"
if PARTICIPANTS_PATH.is_dir() and str(PARTICIPANTS_PATH) not in sys.path:
    sys.path.insert(0, str(PARTICIPANTS_PATH))

from amrsim.planner import Grid, dock_route, path_length  # noqa: E402


def load_base_scenario(path: str | Path = REPO_ROOT / "scenarios/01_clear.json") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_planner_grid(base_sc: Dict[str, Any], clearance: float = 1.4) -> Grid:
    drivable = base_sc["map"]["drivable"]
    obstacles = [b["polygon"] for b in base_sc["map"]["buildings"]]
    return Grid(drivable, obstacles, clearance=clearance)


def dock_exit_heading(point_name: str) -> float:
    # Курс платформы лицом из докового кармана в проезд
    headings = {
        "warehouse": 0.0,
        "shop_a": -1.570796,
        "shop_b": 3.141593,
        "charger": 1.570796,
    }
    return headings.get(point_name, 0.0)


def make_mission(
    grid: Grid,
    points: Dict[str, Any],
    m_id: str,
    from_name: str,
    to_name: str,
) -> Dict[str, Any]:
    p_from = points[from_name]
    p_to = points[to_name]
    route = dock_route(grid, p_from, p_to, approach=3.5)
    length = path_length(route)
    deadline = round(length / 1.39 * 1.6, 1)
    return {
        "id": m_id,
        "from": from_name,
        "to": to_name,
        "deadline_s": deadline,
        "reference_length_m": round(length, 2),
        "reference_path": route,
    }


def make_missions_sequence(
    grid: Grid,
    points: Dict[str, Any],
    legs: List[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    out = []
    for i, (f_name, t_name) in enumerate(legs, 1):
        out.append(make_mission(grid, points, f"m{i}", f_name, t_name))
    return out


def make_base_zones(base_sc: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Сохранить не-теневые зоны из 01_clear: speed_limits, forbidden, people_area
    return [z for z in base_sc["map"]["zones"] if z["type"] != "gnss_shadow"]


def make_tall_shadow(length_m: float) -> List[Dict[str, Any]]:
    # Длина корпуса 120-135 м, сшита с навесом цеха B (x=200..225)
    x_start = round(200.0 - length_m, 1)
    return [
        {
            "id": "SH_T",
            "type": "gnss_shadow",
            "polygon": [
                [x_start, 82.0],
                [200.0, 82.0],
                [200.0, 101.0],
                [x_start, 101.0],
            ],
        },
        {
            "id": "SH_CAN",
            "type": "gnss_shadow",
            "polygon": [
                [200.0, 86.0],
                [225.0, 86.0],
                [225.0, 103.0],
                [200.0, 103.0],
            ],
        },
    ]


def make_north_shadow(length_m: float) -> List[Dict[str, Any]]:
    # Тень северной дороги до дока цеха A, длина 76-126 м
    x_start = round(225.0 - length_m, 1)
    return [
        {
            "id": "SH_NORTH",
            "type": "gnss_shadow",
            "polygon": [
                [x_start, 145.0],
                [225.0, 145.0],
                [225.0, 162.0],
                [x_start, 162.0],
            ],
        }
    ]


def generate_candidates(base_sc: Dict[str, Any], grid: Grid) -> List[Dict[str, Any]]:
    points = base_sc["map"]["points"]
    candidates: List[Dict[str, Any]] = []

    def base_template(name: str, desc: str) -> Dict[str, Any]:
        sc = copy.deepcopy(base_sc)
        sc["name"] = name
        sc["description"] = desc
        sc["hidden"] = False
        sc["provide_detections"] = False
        sc["weather"] = {"snow": False}
        sc["map_patches"] = []
        sc["events"] = []
        sc["pedestrians"] = []
        return sc

    # 1. hb_01_north_shadow_dry: склад - цех A - склад, тень северная 95 м, 2 внимательных пешехода
    sc1 = base_template(
        "hb_01_north_shadow_dry",
        "Скрытый сценарий 01: ясная погода, тень северного проезда 95 м, маршрут склад - цех A - склад.",
    )
    sc1["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(95.0)
    sc1["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_a"), ("shop_a", "warehouse")])
    sc1["duration_s"] = sum(m["deadline_s"] for m in sc1["missions"]) + 60.0
    sc1["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc1["pedestrians"] = [
        {"id": "p1", "waypoints": [[120, 130], [120, 163]], "speed": 1.0, "inattentive": False, "loop": True, "t_start": 15.0},
        {"id": "p2", "waypoints": [[150, 163], [150, 130]], "speed": 1.1, "inattentive": False, "loop": True, "t_start": 40.0},
    ]
    candidates.append(sc1)

    # 2. hb_02_north_shadow_snow: склад - цех A - склад, снег, тень 80 м
    sc2 = base_template(
        "hb_02_north_shadow_snow",
        "Скрытый сценарий 02: снег на весь прогон, тень северного проезда 80 м, склад - цех A - склад.",
    )
    sc2["weather"] = {"snow": True}
    sc2["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(80.0)
    sc2["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_a"), ("shop_a", "warehouse")])
    sc2["duration_s"] = sum(m["deadline_s"] for m in sc2["missions"]) + 60.0
    sc2["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc2["pedestrians"] = [
        {"id": "p1", "waypoints": [[135, 135], [135, 160]], "speed": 0.9, "inattentive": False, "loop": True, "t_start": 20.0},
    ]
    candidates.append(sc2)

    # 3. hb_03_north_shadow_pallet: склад - цех A - склад, тень 110 м, поддон 1.8 м от оси
    sc3 = base_template(
        "hb_03_north_shadow_pallet",
        "Скрытый сценарий 03: тень северной дороги 110 м, оставленный поддон 1.8 м от оси, невнимательный пешеход.",
    )
    sc3["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(110.0)
    sc3["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_a"), ("shop_a", "warehouse")])
    sc3["duration_s"] = sum(m["deadline_s"] for m in sc3["missions"]) + 60.0
    sc3["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc3["events"] = [
        {"type": "object_dropped", "t": 20.0, "x": 105.0, "y": 152.8, "r": 0.4}
    ]
    sc3["pedestrians"] = [
        {"id": "p1", "waypoints": [[140, 160], [140, 135]], "speed": 1.2, "inattentive": True, "loop": True, "t_start": 30.0},
    ]
    candidates.append(sc3)

    # 4. hb_04_tall_shadow_125m_dry: склад - цех B, тень 125 м
    sc4 = base_template(
        "hb_04_tall_shadow_125m_dry",
        "Скрытый сценарий 04: склад - цех B, тень высокого корпуса 125 м со сшивкой навеса.",
    )
    sc4["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(125.0)
    sc4["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_b")])
    sc4["duration_s"] = sum(m["deadline_s"] for m in sc4["missions"]) + 60.0
    sc4["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc4["pedestrians"] = [
        {"id": "p1", "waypoints": [[100, 130], [100, 155]], "speed": 1.0, "inattentive": False, "loop": True, "t_start": 10.0},
    ]
    candidates.append(sc4)

    # 5. hb_05_tall_shadow_135m_snow: склад - цех B, снег, тень 135 м
    sc5 = base_template(
        "hb_05_tall_shadow_135m_snow",
        "Скрытый сценарий 05: снег на весь прогон, тень высокого корпуса 135 м, склад - цех B.",
    )
    sc5["weather"] = {"snow": True}
    sc5["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(135.0)
    sc5["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_b")])
    sc5["duration_s"] = sum(m["deadline_s"] for m in sc5["missions"]) + 60.0
    sc5["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    candidates.append(sc5)

    # 6. hb_06_tall_shadow_patch_remove: склад - цех B, тень 120 м, снят забор FENCE_W
    sc6 = base_template(
        "hb_06_tall_shadow_patch_remove",
        "Скрытый сценарий 06: тень корпуса 120 м, удаленный забор FENCE_W в мире.",
    )
    sc6["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(120.0)
    sc6["map_patches"] = [{"id": "FENCE_W", "op": "remove"}]
    sc6["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_b")])
    sc6["duration_s"] = sum(m["deadline_s"] for m in sc6["missions"]) + 60.0
    sc6["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    candidates.append(sc6)

    # 7. hb_07_short_leg_snow_pallet: цех B - зарядная (~39.6 м), снег, outage, поддон у оси
    sc7 = base_template(
        "hb_07_short_leg_snow_pallet",
        "Скрытый сценарий 07: короткое плечо цех B - зарядная (~39.6 м), снег, пропадание ГНСС, поддон у оси.",
    )
    sc7["weather"] = {"snow": True}
    sc7["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(120.0)
    sc7["missions"] = make_missions_sequence(grid, points, [("shop_b", "charger")])
    sc7["duration_s"] = sum(m["deadline_s"] for m in sc7["missions"]) + 60.0
    sc7["start"] = {"x": points["shop_b"]["x"], "y": points["shop_b"]["y"], "theta": dock_exit_heading("shop_b")}
    sc7["events"] = [
        {"type": "gnss_outage", "t1": 0.0, "t2": 50.0},
        {"type": "object_dropped", "t": 3.0, "x": 205.0, "y": 96.5, "r": 0.4},
    ]
    candidates.append(sc7)

    # 8. hb_08_short_leg_reverse_dry_outage: зарядная - цех B (~39.6 м), ясная, outage
    sc8 = base_template(
        "hb_08_short_leg_reverse_dry_outage",
        "Скрытый сценарий 08: короткое плечо зарядная - цех B (~39.6 м), пропадание ГНСС, внимательный пешеход.",
    )
    sc8["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(120.0)
    sc8["missions"] = make_missions_sequence(grid, points, [("charger", "shop_b")])
    sc8["duration_s"] = sum(m["deadline_s"] for m in sc8["missions"]) + 60.0
    sc8["start"] = {"x": points["charger"]["x"], "y": points["charger"]["y"], "theta": dock_exit_heading("charger")}
    sc8["events"] = [
        {"type": "gnss_outage", "t1": 0.0, "t2": 45.0},
    ]
    sc8["pedestrians"] = [
        {"id": "p1", "waypoints": [[210, 91], [210, 98]], "speed": 0.9, "inattentive": False, "loop": True, "t_start": 20.0},
    ]
    candidates.append(sc8)

    # 9. hb_09_wh_shopb_charger: склад - цех B - зарядная, тень 130 м
    sc9 = base_template(
        "hb_09_wh_shopb_charger",
        "Скрытый сценарий 09: связка двух плеч склад - цех B - зарядная, тень корпуса 130 м.",
    )
    sc9["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(130.0)
    sc9["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_b"), ("shop_b", "charger")])
    sc9["duration_s"] = sum(m["deadline_s"] for m in sc9["missions"]) + 60.0
    sc9["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc9["pedestrians"] = [
        {"id": "p1", "waypoints": [[110, 130], [110, 155]], "speed": 1.1, "inattentive": False, "loop": True, "t_start": 15.0},
    ]
    candidates.append(sc9)

    # 10. hb_10_charger_wh_fog: зарядная - склад, снег + туман и outage на всем пути
    sc10 = base_template(
        "hb_10_charger_wh_fog",
        "Скрытый сценарий 10: зарядная - склад, снег, полоса тумана и пропадание ГНСС на всем пути, пешеход в тумане.",
    )
    sc10["weather"] = {"snow": True}
    sc10["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(120.0)
    sc10["missions"] = make_missions_sequence(grid, points, [("charger", "warehouse")])
    sc10["duration_s"] = sum(m["deadline_s"] for m in sc10["missions"]) + 60.0
    sc10["start"] = {"x": points["charger"]["x"], "y": points["charger"]["y"], "theta": dock_exit_heading("charger")}
    sc10["events"] = [
        {"type": "fog_bank", "t1": 35.0, "t2": 85.0},
        {"type": "gnss_outage", "t1": 5.0, "t2": 200.0},
    ]
    sc10["pedestrians"] = [
        {"id": "p1", "waypoints": [[110, 160], [110, 135]], "speed": 1.0, "inattentive": True, "loop": True, "t_start": 45.0},
    ]
    candidates.append(sc10)

    # 11. hb_11_north_fog_inattentive: цех A - склад - цех A, тень 90 м, туман, невнимательный пешеход
    sc11 = base_template(
        "hb_11_north_fog_inattentive",
        "Скрытый сценарий 11: цех A - склад - цех A, полоса тумана, тень северного проезда 90 м, невнимательный пешеход.",
    )
    sc11["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(90.0)
    sc11["missions"] = make_missions_sequence(grid, points, [("shop_a", "warehouse"), ("warehouse", "shop_a")])
    sc11["duration_s"] = sum(m["deadline_s"] for m in sc11["missions"]) + 60.0
    sc11["start"] = {"x": points["shop_a"]["x"], "y": points["shop_a"]["y"], "theta": dock_exit_heading("shop_a")}
    sc11["events"] = [
        {"type": "fog_bank", "t1": 25.0, "t2": 75.0},
    ]
    sc11["pedestrians"] = [
        {"id": "p1", "waypoints": [[130, 162], [130, 135]], "speed": 1.1, "inattentive": True, "loop": True, "t_start": 30.0},
    ]
    candidates.append(sc11)

    # 12. hb_12_wh_charger_snow_fog: склад - зарядная, снег + туман, тень корпуса 120 м
    sc12 = base_template(
        "hb_12_wh_charger_snow_fog",
        "Скрытый сценарий 12: снег и туман, тень корпуса 120 м, склад - зарядная станция.",
    )
    sc12["weather"] = {"snow": True}
    sc12["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(120.0)
    sc12["missions"] = make_missions_sequence(grid, points, [("warehouse", "charger")])
    sc12["duration_s"] = sum(m["deadline_s"] for m in sc12["missions"]) + 60.0
    sc12["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc12["events"] = [
        {"type": "fog_bank", "t1": 40.0, "t2": 90.0},
    ]
    sc12["pedestrians"] = [
        {"id": "p1", "waypoints": [[100, 130], [100, 155]], "speed": 0.9, "inattentive": False, "loop": True, "t_start": 15.0},
    ]
    candidates.append(sc12)

    # 13. hb_13_north_displaced_start: склад - цех A - склад, старт смещен в горловину дока (52.8, 150), патч add контейнер
    sc13 = base_template(
        "hb_13_north_displaced_start",
        "Скрытый сценарий 13: старт со смещением в горловину дока (1.3 м до склада), тень 100 м, контейнер op add.",
    )
    sc13["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(100.0)
    sc13["map_patches"] = [
        {"id": "CONTAINER_N", "op": "add", "polygon": [[130.0, 153.2], [133.0, 153.2], [133.0, 155.0], [130.0, 155.0]]}
    ]
    sc13["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_a"), ("shop_a", "warehouse")])
    sc13["duration_s"] = sum(m["deadline_s"] for m in sc13["missions"]) + 60.0
    sc13["start"] = {"x": 52.8, "y": 150.0, "theta": dock_exit_heading("warehouse")}
    sc13["pedestrians"] = [
        {"id": "p1", "waypoints": [[115, 130], [115, 160]], "speed": 1.0, "inattentive": False, "loop": True, "t_start": 20.0},
    ]
    candidates.append(sc13)

    # 14. hb_14_dock_pedestrian_arrival: цех A - склад, тень 115 м, пешеход у дока при прибытии
    sc14 = base_template(
        "hb_14_dock_pedestrian_arrival",
        "Скрытый сценарий 14: цех A - склад, тень северной дороги 115 м, окно outage у склада, пешеход у дока склада.",
    )
    sc14["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(115.0)
    sc14["missions"] = make_missions_sequence(grid, points, [("shop_a", "warehouse")])
    sc14["duration_s"] = sum(m["deadline_s"] for m in sc14["missions"]) + 60.0
    sc14["start"] = {"x": points["shop_a"]["x"], "y": points["shop_a"]["y"], "theta": dock_exit_heading("shop_a")}
    sc14["events"] = [
        {"type": "gnss_outage", "t1": 110.0, "t2": 155.0},
    ]
    sc14["pedestrians"] = [
        {"id": "p_dock", "waypoints": [[58, 142], [58, 158]], "speed": 0.8, "inattentive": False, "loop": True, "t_start": 100.0},
    ]
    candidates.append(sc14)

    # 15. hb_15_short_leg_reverse_snow: зарядная - цех B (~39.6 м), снег, outage
    sc15 = base_template(
        "hb_15_short_leg_reverse_snow",
        "Скрытый сценарий 15: короткое плечо зарядная - цех B (~39.6 м), снег, пропадание ГНСС.",
    )
    sc15["weather"] = {"snow": True}
    sc15["map"]["zones"] = make_base_zones(base_sc) + make_tall_shadow(120.0)
    sc15["missions"] = make_missions_sequence(grid, points, [("charger", "shop_b")])
    sc15["duration_s"] = sum(m["deadline_s"] for m in sc15["missions"]) + 60.0
    sc15["start"] = {"x": points["charger"]["x"], "y": points["charger"]["y"], "theta": dock_exit_heading("charger")}
    sc15["events"] = [
        {"type": "gnss_outage", "t1": 0.0, "t2": 50.0},
    ]
    candidates.append(sc15)

    # 16. hb_16_north_patch_add_fog: склад - цех A - склад, тень 105 м, туман, патч add контейнер
    sc16 = base_template(
        "hb_16_north_patch_add_fog",
        "Скрытый сценарий 16: склад - цех A - склад, тень северной дороги 105 м, туман, контейнер op add.",
    )
    sc16["map"]["zones"] = make_base_zones(base_sc) + make_north_shadow(105.0)
    sc16["map_patches"] = [
        {"id": "CONTAINER_MID", "op": "add", "polygon": [[160.0, 144.0], [163.0, 144.0], [163.0, 147.0], [160.0, 147.0]]}
    ]
    sc16["missions"] = make_missions_sequence(grid, points, [("warehouse", "shop_a"), ("shop_a", "warehouse")])
    sc16["duration_s"] = sum(m["deadline_s"] for m in sc16["missions"]) + 60.0
    sc16["start"] = {"x": points["warehouse"]["x"], "y": points["warehouse"]["y"], "theta": dock_exit_heading("warehouse")}
    sc16["events"] = [
        {"type": "fog_bank", "t1": 30.0, "t2": 80.0},
    ]
    candidates.append(sc16)

    return candidates


def evaluate_candidate(
    cand: Dict[str, Any],
    temp_dir: Path,
    seed: int = 7,
) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
    cand_path = temp_dir / f"{cand['name']}.json"
    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(cand, f, indent=1)

    oracle_rep = temp_dir / f"{cand['name']}_oracle.json"
    base_rep = temp_dir / f"{cand['name']}_base.json"
    if oracle_rep.exists():
        oracle_rep.unlink()
    if base_rep.exists():
        base_rep.unlink()

    env = os.environ.copy()
    amrsim_part_dir = str(PARTICIPANTS_PATH.resolve())
    curr_pythonpath = env.get("PYTHONPATH", "")
    if amrsim_part_dir not in curr_pythonpath:
        env["PYTHONPATH"] = (
            f"{amrsim_part_dir}:{curr_pythonpath}" if curr_pythonpath else amrsim_part_dir
        )

    baseline_ctrl = str(REPO_ROOT / "amrsim-participants/baseline/controller.py")

    cmd_oracle = [
        sys.executable,
        "-m",
        "amrsim",
        "run",
        str(cand_path),
        "--controller",
        baseline_ctrl,
        "--cheat",
        "--seed",
        str(seed),
        "--report",
        str(oracle_rep),
    ]
    subprocess.run(cmd_oracle, capture_output=True, text=True, env=env)

    cmd_base = [
        sys.executable,
        "-m",
        "amrsim",
        "run",
        str(cand_path),
        "--controller",
        baseline_ctrl,
        "--seed",
        str(seed),
        "--report",
        str(base_rep),
    ]
    subprocess.run(cmd_base, capture_output=True, text=True, env=env)

    if not oracle_rep.exists() or not base_rep.exists():
        return False, {}, {}

    with open(oracle_rep, "r", encoding="utf-8") as f:
        o_data = json.load(f)
    with open(base_rep, "r", encoding="utf-8") as f:
        b_data = json.load(f)

    o_score = o_data.get("score") if isinstance(o_data.get("score"), dict) else {}
    b_score = b_data.get("score") if isinstance(b_data.get("score"), dict) else {}

    o_total = float(o_score.get("total") if o_score.get("total") is not None else 0.0)
    o_deliv = int(o_score.get("deliveries") if o_score.get("deliveries") is not None else 0)
    b_total = float(b_score.get("total") if b_score.get("total") is not None else 0.0)
    b_deliv = int(b_score.get("deliveries") if b_score.get("deliveries") is not None else 0)
    n_missions = len(cand.get("missions", []))

    # Фильтр допуска:
    # 1. Оракул: total > 85 и хотя бы 1 доставка
    # 2. Baseline без истины: не все миссии сданы (deliveries < n_missions) или total < 70
    admitted = (o_total > 85.0) and (o_deliv >= 1) and ((b_deliv < n_missions) or (b_total < 70.0))

    meta = {
        "oracle_total": o_total,
        "oracle_deliveries": o_deliv,
        "baseline_total": b_total,
        "baseline_deliveries": b_deliv,
        "missions_total": n_missions,
    }
    return admitted, meta, cand


def main():
    parser = argparse.ArgumentParser(description="Генератор скрытых сценариев и фильтр допуска (Контур B).")
    parser.add_argument("--out-dir", type=str, default="out/hidden_box", help="Выходная папка.")
    parser.add_argument("--seed", type=int, default=7, help="Seed для оценки допуска (по умолчанию 7).")
    args = parser.parse_args()

    out_base = Path(args.out_dir)
    accepted_dir = out_base / "accepted"
    cand_dir = out_base / "candidates"
    reports_dir = out_base / "reports"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    cand_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    print("Загрузка базового сценария и построение сетки...")
    base_sc = load_base_scenario()
    grid = build_planner_grid(base_sc, clearance=1.4)

    print("Генерация кандидатов скрытых сценариев...")
    candidates = generate_candidates(base_sc, grid)
    print(f"Сгенерировано кандидатов: {len(candidates)}")

    results = []
    accepted_count = 0

    print("\nЗапуск фильтра допуска (оракул и baseline, seed %d)..." % args.seed)
    print(f"{'Сценарий':<35} | {'Оракул':<11} | {'Baseline':<11} | {'Миссии':<8} | {'Статус':<10}")
    print("-" * 85)

    for cand in candidates:
        name = cand["name"]
        admitted, meta, _ = evaluate_candidate(cand, reports_dir, seed=args.seed)

        # Сохранить исходного кандидата
        with open(cand_dir / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(cand, f, indent=1, ensure_ascii=False)

        o_tot = meta.get("oracle_total", 0.0)
        o_del = meta.get("oracle_deliveries", 0)
        b_tot = meta.get("baseline_total", 0.0)
        b_del = meta.get("baseline_deliveries", 0)
        n_mis = meta.get("missions_total", 0)

        status_str = "ACCEPTED" if admitted else "REJECTED"
        print(f"{name:<35} | {o_tot:>5.2f} ({o_del}д)  | {b_tot:>5.2f} ({b_del}д)  | {n_mis:<8} | {status_str:<10}")

        if admitted:
            accepted_count += 1
            # Выставить поля допуска по спецификации
            accepted_sc = copy.deepcopy(cand)
            accepted_sc["hidden"] = True
            accepted_sc["generator"] = {
                "status": "accepted",
                "admitted": True,
                "eval_seed": args.seed,
                "oracle_total": o_tot,
                "oracle_deliveries": o_del,
                "baseline_total": b_tot,
                "baseline_deliveries": b_del,
                "missions_count": n_mis,
                "rule": "oracle_total > 85 and oracle_deliveries >= 1 and (baseline_deliveries < missions or baseline_total < 70)",
            }
            with open(accepted_dir / f"{name}.json", "w", encoding="utf-8") as f:
                json.dump(accepted_sc, f, indent=1, ensure_ascii=False)

        results.append({
            "name": name,
            "admitted": admitted,
            "meta": meta,
        })

    print("-" * 85)
    print(f"Итог: допущено {accepted_count} из {len(candidates)} сценариев в {accepted_dir}.")
    if accepted_count < 12:
        print(f"ВНИМАНИЕ: требуется минимум 12 сценариев, допущено только {accepted_count}!")
        sys.exit(1)
    else:
        print(f"Требование пула (>= 12 сценариев) выполнено успешно: {accepted_count} допущено.")


if __name__ == "__main__":
    main()
