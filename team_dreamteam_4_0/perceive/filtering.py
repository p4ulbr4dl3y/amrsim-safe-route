"""Подмодуль фильтрации: предобработка сканов, фильтрация тумана/снега, удаление стен.

Требования изоляции: только стандартная библиотека и numpy.
"""

import math
from typing import Dict, Optional, Set, Tuple

import numpy as np

try:
    from ..geom import raycast, seg_dist, wrap_angle
except (ImportError, ValueError):
    from geom import raycast, seg_dist, wrap_angle

__all__ = [
    "filter_map_walls",
    "filter_snow_artifacts",
    "preprocess_scan",
    "check_map_discrepancies",
]


def filter_map_walls(
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    pose: Tuple[float, float, float],
    map_segs: np.ndarray,
    sigma_pose: float = 0.0,
    removed_segment_ids: Optional[Set[int]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Выделить необъясненные отклики лидара, исключив стены карты.

    Аргументы:
      ranges: массив дальностей лидара;
      rel_angles: углы лучей в базисе робота (рад);
      pose: поза робота (x, y, th);
      map_segs: отрезки стен зданий карты (M, 4);
      sigma_pose: неопределенность позы локализатора (м);
      removed_segment_ids: идентификаторы снесенных стен.

    Возвращает:
      (bad_mask, exp_ranges, active_segs)
    """
    x, y, th = pose
    r = np.asarray(ranges, dtype=float)
    rel = np.asarray(rel_angles, dtype=float)
    n = len(r)

    if n == 0 or map_segs is None or len(map_segs) == 0:
        return np.zeros(n, dtype=bool), np.full(n, np.inf), np.empty((0, 4))

    # Фильтрация активных отрезков карты
    active_segs = map_segs
    if removed_segment_ids:
        mask = np.ones(len(map_segs), dtype=bool)
        for sid in sorted(removed_segment_ids):
            if 0 <= sid < len(map_segs):
                mask[sid] = False
        active_segs = map_segs[mask]

    # Ожидаемые расстояния до стен карты
    exp = raycast(x, y, th + rel, active_segs)

    # Кандидаты в необъясненные лучи: короче карты с запасом
    margin = 0.35 + min(1.5, max(0.0, sigma_pose))
    bad = np.isfinite(r) & (r < exp - margin)

    # Исключение лучей, попадающих в пределы допустимого расстояния от стены карты
    if bad.any() and len(active_segs) > 0:
        bad_idx = np.flatnonzero(bad)
        beam_world_angles = th + rel[bad_idx]
        wx = x + r[bad_idx] * np.cos(beam_world_angles)
        wy = y + r[bad_idx] * np.sin(beam_world_angles)
        wall_margin = max(0.85, 0.4 + min(1.5, 2.0 * sigma_pose))
        near_wall = seg_dist(wx, wy, active_segs) < wall_margin
        bad[bad_idx[near_wall]] = False

    return bad, exp, active_segs


def filter_snow_artifacts(
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    bad_mask: np.ndarray,
) -> np.ndarray:
    """Отфильтровать одиночные изолированные шумовые отклики снегопада.

    Аргументы:
      ranges: массив дальностей лидара;
      rel_angles: углы лучей лидара (рад);
      bad_mask: булева маска необъясненных лучей.

    Возвращает:
      обновленная булева маска bad_mask.
    """
    r = np.asarray(ranges, dtype=float)
    rel = np.asarray(rel_angles, dtype=float)
    n = len(r)
    bad = bad_mask.copy()

    if not bad.any() or n == 0:
        return bad

    bad_idx = np.flatnonzero(bad)
    cos_rel = np.cos(rel)
    sin_rel = np.sin(rel)
    px_all = r * cos_rel
    py_all = r * sin_rel

    for k in bad_idx:
        prev_k = (k - 1) % n
        next_k = (k + 1) % n
        has_prev = bad[prev_k] and (
            math.hypot(px_all[k] - px_all[prev_k], py_all[k] - py_all[prev_k]) < 0.6
        )
        has_next = bad[next_k] and (
            math.hypot(px_all[k] - px_all[next_k], py_all[k] - py_all[next_k]) < 0.6
        )
        if not (has_prev or has_next):
            # Одиночный изолированный луч: артефакт снегопада
            bad[k] = False

    return bad


def preprocess_scan(
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    pose: Tuple[float, float, float],
    map_segs: np.ndarray,
    sigma_pose: float = 0.0,
    removed_segment_ids: Optional[Set[int]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Полная предобработка скана: отсечение стен карты и фильтрация шума снега."""
    bad, exp, active_segs = filter_map_walls(
        ranges=ranges,
        rel_angles=rel_angles,
        pose=pose,
        map_segs=map_segs,
        sigma_pose=sigma_pose,
        removed_segment_ids=removed_segment_ids,
    )
    bad = filter_snow_artifacts(ranges, rel_angles, bad)
    return bad, exp, active_segs


def check_map_discrepancies(
    ranges: np.ndarray,
    exp_ranges: np.ndarray,
    x: float,
    y: float,
    th: float,
    map_segs: np.ndarray,
    scan_inliers: int,
    removed_segment_ids: Set[int],
    missing_wall_votes: Dict[int, int],
    has_wall_tracks: bool,
) -> Optional[str]:
    """Обнаружить снесенные стены карты (map_missing) или новые конструкции (map_extra).

    Возвращает:
      'map_missing', 'map_extra' или None.
    """
    if len(map_segs) == 0:
        return None

    detected_note: Optional[str] = None

    # Обнаружение отсутствующих стен: лучи длиннее карты более чем на 1.2 м
    if scan_inliers >= 40:
        overshoot = (
            (exp_ranges < 15.0)
            & np.isfinite(ranges)
            & (ranges < 19.5)
            & (ranges > exp_ranges + 1.2)
        )
        if overshoot.any():
            over_indices = np.flatnonzero(overshoot)
            tick_votes: Dict[int, int] = {}
            for idx in over_indices:
                for s_idx, seg in enumerate(map_segs):
                    if s_idx in removed_segment_ids:
                        continue
                    ang = wrap_angle(th + np.radians(float(idx)))
                    r_s = raycast(x, y, np.array([ang]), seg[None, :])
                    if np.isfinite(r_s[0]) and abs(r_s[0] - exp_ranges[idx]) < 0.25:
                        tick_votes[s_idx] = tick_votes.get(s_idx, 0) + 1

            for s_idx, count in sorted(tick_votes.items()):
                if count >= 5:
                    missing_wall_votes[s_idx] = missing_wall_votes.get(s_idx, 0) + 1
                    if missing_wall_votes[s_idx] >= 20:
                        removed_segment_ids.add(s_idx)
                        detected_note = "map_missing"

    # Проверка подтвержденных лишних стен
    if detected_note is None and has_wall_tracks:
        detected_note = "map_extra"

    return detected_note
