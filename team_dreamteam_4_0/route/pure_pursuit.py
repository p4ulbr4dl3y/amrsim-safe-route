"""Управление траекторным движением: чистое преследование и регулятор Стэнли.

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
    """Найти пройденное расстояние вдоль полилинии для текущей точки."""
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
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(th)):
        return 0.0

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
    """Определить точку упреждения траектории и признак зоны дока.

    Параметры зоны дока:
    - дистанция до цели: не более 0.6 м по евклидову расстоянию или по остатку пути вдоль полилинии;
    - ограничение скорости: максимальная линейная скорость платформы v <= 0.25 м/с;
    - прицеливание: непосредственно в целевую точку финиша вместо выноса точки упреждения по полилинии;
    - штатный режим: при расстоянии до цели более 0.6 м точка упреждения выносится вперед вдоль пути на 1.5 м.
    """
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


def compute_cross_track_error(
    path: np.ndarray,
    x: float,
    y: float,
    th: float,
    last_s: float = 0.0,
) -> Tuple[float, float, float, int]:
    """Вычислить пройденное расстояние, боковую ошибку и курсовую ошибку.

    Геометрические параметры положения платформы относительно полилинии:
    - пройденное расстояние: текущий прогресс платформы вдоль опорного маршрута;
    - боковая ошибка: знаковое расстояние от платформы до проекции на ближайший отрезок пути;
    - курсовая ошибка: разность между направлением касательной к сегменту и текущим курсом платформы;
    - индекс сегмента: номер опорного отрезка полилинии с минимальным расстоянием до платформы.

    Возвращает кортеж из пройденного расстояния, боковой ошибки, курсовой ошибки и индекса сегмента.
    """
    if len(path) < 2:
        return (last_s, 0.0, 0.0, 0)

    diffs = path[1:] - path[:-1]
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])

    best_s = last_s
    best_dist = math.inf
    best_idx = 0
    best_proj = path[0]

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
                best_idx = i
                best_proj = proj

    curr_s = max(last_s, best_s)
    v_seg = diffs[best_idx]
    L = max(1e-6, seg_lens[best_idx])
    tangent = v_seg / L
    path_hd = math.atan2(tangent[1], tangent[0])

    dx = x - best_proj[0]
    dy = y - best_proj[1]
    cross_track_e = -tangent[1] * dx + tangent[0] * dy
    heading_e = wrap_angle(path_hd - th)

    return curr_s, float(cross_track_e), float(heading_e), best_idx


def compute_curvature_speed_limit(
    alpha: float,
    lookahead_dist: float,
    a_lat_max: float = 0.85,
    v_nominal: float = 1.39,
) -> float:
    """Вычислить предельную скорость в дуге по ограничению центростремительного ускорения платформы.

    Кривизна траектории: kappa = 2 * sin(alpha) / max(lookahead_dist, 0.1).
    Ограничение бокового ускорения: a_lat = v^2 * |kappa| <= a_lat_max.
    Предельная скорость: v_curve = sqrt(a_lat_max / max(|kappa|, 1e-4)).
    """
    l_eff = max(lookahead_dist, 0.1)
    kappa = 2.0 * math.sin(alpha) / l_eff
    abs_kappa = abs(kappa)
    if abs_kappa < 1e-4:
        return v_nominal
    v_curve = math.sqrt(a_lat_max / abs_kappa)
    return min(v_nominal, float(v_curve))


def compute_pure_pursuit_cmd(
    pose: Tuple[float, float, float],
    path: np.ndarray,
    last_s: float = 0.0,
    v_max: float = 1.39,
    a_lat_max: float = 0.85,
) -> Tuple[float, float, Tuple[float, float], float, float]:
    """Следование по полилинии методом чистого преследования.

    Режимы движения и параметры зоны дока:
    - зона дока: дистанция до цели не более 0.6 м, ограничение скорости v <= 0.25 м/с, прицеливание непосредственно в целевую точку;
    - разворот на месте: при курсовом рассогласовании более 0.85 рад платформа поворачивает на месте с нулевой линейной скоростью;
    - ограничение бокового ускорения: на криволинейных участках скорость ограничивается допустимым центростремительным ускорением;
    - профиль торможения: безопасное замедление перед остановкой в доке по формуле равнозамедленного движения.

    Возвращает кортеж из линейной скорости, угловой скорости, координат целевой точки, пройденного пути и оставшейся дистанции.
    """
    x, y, th = pose
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(th)):
        target_pt = (float(path[0, 0]), float(path[0, 1])) if len(path) > 0 else (0.0, 0.0)
        return 0.0, 0.0, target_pt, 0.0, 0.0

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

    effective_rem = max(0.0, min(rem_dist, dist_to_goal + 0.05) - 0.02)
    if dist_to_goal < 0.03 or effective_rem < 0.03:
        return 0.0, 0.0, target_pt, curr_s, 0.0

    if abs(alpha) > 0.85:
        v = 0.0
        w = float(np.clip(2.0 * alpha, -0.8, 0.8))
        return v, w, target_pt, curr_s, rem_dist

    v_dock = 0.25 if is_dock_zone else 1.39
    v_curve = compute_curvature_speed_limit(alpha, ld, a_lat_max=a_lat_max, v_nominal=1.39)
    v_brake = math.sqrt(2.0 * 0.4 * effective_rem) + 0.03

    v = min(v_max, v_dock, v_curve, v_brake)
    v = max(0.0, v)

    lx = max(0.5, ld)
    w = 2.0 * v * math.sin(alpha) / lx if v > 0.05 else float(np.clip(1.5 * alpha, -1.0, 1.0))
    w = float(np.clip(w, -1.0, 1.0))

    return v, w, target_pt, curr_s, rem_dist


