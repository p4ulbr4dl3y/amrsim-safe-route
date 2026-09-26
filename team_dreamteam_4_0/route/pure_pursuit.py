"""Чистое преследование пути (pure pursuit): расчет упреждения, линейной и угловой скорости.

Изоляция: используются только стандартные math, typing и numpy.
"""

import math
from typing import Any, Dict, List, Tuple

import numpy as np

try:
    from ..geom import inside_polygon, wrap_angle
except (ImportError, ValueError):
    from geom import inside_polygon, wrap_angle


def get_path_progress(
    path: np.ndarray, x: float, y: float, last_s: float = 0.0
) -> float:
    """Найти пройденное расстояние s вдоль полилинии, соответствующее точке (x, y)."""
    if len(path) < 2:
        return 0.0
    diffs = path[1:] - path[:-1]
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])

    best_s = last_s
    best_dist = math.inf
    for i in range(len(seg_lens)):
        p1 = path[i]
        v = diffs[i]
        L = seg_lens[i]
        if L < 1e-6:
            continue
        u = np.clip(((x - p1[0]) * v[0] + (y - p1[1]) * v[1]) / (L * L), 0.0, 1.0)
        proj = p1 + u * v
        s_cand = cum_lens[i] + u * L

        if s_cand >= last_s - 1.5:
            d = math.hypot(x - proj[0], y - proj[1])
            if d < best_dist:
                best_dist = d
                best_s = s_cand

    return max(last_s, best_s)


def check_speed_zones(
    x: float, y: float, th: float, speed_zones: List[Dict[str, Any]]
) -> float:
    """Проверить текущую точку, +3.0 м впереди и -1.5 м позади на попадание в скоростные зоны.

    Возвращает максимально допустимую скорость (м/с), по умолчанию 1.39 м/с.
    """
    c, s = math.cos(th), math.sin(th)
    test_pts = np.array(
        [
            [x, y],
            [x + 3.0 * c, y + 3.0 * s],
            [x - 1.5 * c, y - 1.5 * s],
        ]
    )

    speed_cap = 1.39
    for zone in speed_zones:
        poly = zone["polygon"]
        if np.any(inside_polygon(test_pts, poly)):
            z_limit = float(zone["v_max"]) - 0.05
            if z_limit < speed_cap:
                speed_cap = z_limit
    return speed_cap


def find_lookahead_point(
    path: np.ndarray,
    curr_s: float,
    cum_lens: np.ndarray,
    seg_lens: np.ndarray,
    diffs: np.ndarray,
    dist_to_goal: float,
    rem_dist: float,
    lookahead_dist: float = 1.5,
) -> Tuple[Tuple[float, float], bool]:
    """Определить точку упреждения pure pursuit и признак зоны дока."""
    goal_pt = path[-1]
    is_dock_zone = dist_to_goal <= 0.6 or rem_dist <= 0.6
    if is_dock_zone:
        target_pt = (float(goal_pt[0]), float(goal_pt[1]))
    else:
        total_len = cum_lens[-1]
        target_s = min(total_len, curr_s + lookahead_dist)
        idx = np.searchsorted(cum_lens, target_s) - 1
        idx = max(0, min(len(seg_lens) - 1, idx))
        tau = (target_s - cum_lens[idx]) / max(1e-6, seg_lens[idx])
        t_coord = path[idx] + tau * diffs[idx]
        target_pt = (float(t_coord[0]), float(t_coord[1]))
    return target_pt, is_dock_zone


def compute_pure_pursuit_cmd(
    pose: Tuple[float, float, float],
    path: np.ndarray,
    last_s: float = 0.0,
    v_max: float = 1.39,
) -> Tuple[float, float, Tuple[float, float], float, float]:
    """Следование по полилинии методом чистого преследования.

    Возвращает (v, w, target_point, current_s, remaining_dist).
    """
    x, y, th = pose
    if len(path) < 2:
        return 0.0, 0.0, (x, y), 0.0, 0.0

    diffs = path[1:] - path[:-1]
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total_len = cum_lens[-1]

    curr_s = get_path_progress(path, x, y, last_s=last_s)
    rem_dist = max(0.0, total_len - curr_s)

    goal_pt = path[-1]
    dist_to_goal = math.hypot(x - goal_pt[0], y - goal_pt[1])

    target_pt, is_dock_zone = find_lookahead_point(
        path, curr_s, cum_lens, seg_lens, diffs, dist_to_goal, rem_dist
    )

    dx = target_pt[0] - x
    dy = target_pt[1] - y
    ld = math.hypot(dx, dy)
    target_hd = math.atan2(dy, dx)
    alpha = wrap_angle(target_hd - th)

    if abs(alpha) > 0.8:
        v = 0.0
        w = float(np.clip(2.0 * alpha, -0.8, 0.8))
        return v, w, target_pt, curr_s, rem_dist

    v_dock = 0.25 if is_dock_zone else 1.39
    v_turn = 0.5 if abs(alpha) > 0.35 else 1.39
    effective_rem = max(0.0, min(rem_dist, dist_to_goal + 0.05) - 0.02)
    v_brake = math.sqrt(2.0 * 0.4 * effective_rem) + 0.03

    if dist_to_goal < 0.03 or effective_rem < 0.03:
        return 0.0, 0.0, target_pt, curr_s, 0.0

    v = min(v_max, v_dock, v_turn, v_brake)
    v = max(0.0, v)

    lx = max(0.5, ld)
    w = 2.0 * v * math.sin(alpha) / lx if v > 0.05 else float(np.clip(1.5 * alpha, -1.0, 1.0))
    w = float(np.clip(w, -1.0, 1.0))

    return v, w, target_pt, curr_s, rem_dist
