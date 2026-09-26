"""Подмодуль кластеризации точек лидара и аппроксимации геометрии кластеров.

Требования изоляции: только стандартная библиотека и numpy.
"""

import math
from typing import Any, Dict, List, Tuple

import numpy as np

__all__ = [
    "fit_cluster_geometry",
    "is_wall_cluster",
    "is_wall_continuation",
    "group_unexplained_rays",
    "extract_clusters",
    "euclidean_cluster_points",
]


def fit_cluster_geometry(pts: np.ndarray) -> Tuple[float, float]:
    """Вычислить длину и толщину по 80-му перцентилю методом PCA (SVD).

    pts: массив (N, 2) 2D точек на декартовой плоскости.
    Возвращает:
      (length, thickness) в метрах.
    """
    if len(pts) < 2:
        return 0.0, 0.0
    if len(pts) == 2:
        length = float(np.hypot(pts[1, 0] - pts[0, 0], pts[1, 1] - pts[0, 1]))
        return length, 0.0

    c = pts.mean(axis=0)
    centered = pts - c
    try:
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        along = centered @ vt[0]
        across = centered @ vt[1]
        length = float(along.max() - along.min())
        thickness = float(np.percentile(np.abs(across), 80))
        return length, thickness
    except Exception:
        length = float(np.ptp(pts[:, 0]) + np.ptp(pts[:, 1]))
        return length, 0.0


def is_wall_cluster(pts: np.ndarray) -> bool:
    """Определить, соответствует ли геометрия кластера неразмеченной стене или забору.

    Критерий: длина > 1.0 м и толщина по 80-му перцентилю < 0.1 м.
    """
    if len(pts) < 3:
        return False
    length, thickness = fit_cluster_geometry(pts)
    return length > 1.0 and thickness < 0.10


def is_wall_continuation(pts: np.ndarray, wall_point_clouds: List[np.ndarray]) -> bool:
    """Определить, продолжает ли короткий кластер неразмеченную стену.

    Критерий: кластер ближе 0.6 м к известному кластеру стены, а его
    боковое отклонение по 80-му перцентилю от главной оси стены < 0.15 м.
    """
    if len(pts) == 0 or not wall_point_clouds:
        return False

    for w_pts in wall_point_clouds:
        if len(w_pts) < 3:
            continue
        dists = np.hypot(pts[:, None, 0] - w_pts[None, :, 0], pts[:, None, 1] - w_pts[None, :, 1])
        if float(dists.min()) > 0.6:
            continue

        c = w_pts.mean(axis=0)
        try:
            _, _, vt = np.linalg.svd(w_pts - c, full_matrices=False)
            proj_across = (pts - c) @ vt[1]
            if float(np.percentile(np.abs(proj_across), 80)) < 0.15:
                return True
        except Exception:
            continue

    return False


def group_unexplained_rays(
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    bad_mask: np.ndarray,
) -> List[List[int]]:
    """Сгруппировать необъясненные лучи в непрерывные кластеры с учетом разрывов в тумане.

    Возвращает:
      список списков индексов лучей для каждого обнаруженного кластера.
    """
    r = np.asarray(ranges, dtype=float)
    rel = np.asarray(rel_angles, dtype=float)
    n = len(r)
    if n == 0 or not bad_mask.any():
        return []

    finite = np.isfinite(r)
    breaks = finite & ~bad_mask
    clusters: List[List[int]] = []

    start = (
        int(np.argmax(breaks))
        if breaks.any()
        else int(np.argmax(~finite))
        if (~finite).any()
        else 0
    )
    run: List[int] = []
    skipped = 0

    for j in range(1, n + 1):
        k = (start + j) % n
        if bad_mask[k]:
            if not run:
                run.append(k)
                skipped = 0
                continue
            gap = math.hypot(
                r[k] * math.cos(rel[k]) - r[run[-1]] * math.cos(rel[run[-1]]),
                r[k] * math.sin(rel[k]) - r[run[-1]] * math.sin(rel[run[-1]]),
            )
            if gap < 0.6:
                run.append(k)
                skipped = 0
                continue

        # До 2 пропущенных лучей не разрывают кластер для устойчивости в тумане
        if run and skipped < 2:
            nxt = [(start + j + d) % n for d in (1, 2)]
            can_resume = not finite[k] or any(
                bad_mask[q]
                and (
                    math.hypot(
                        r[q] * math.cos(rel[q]) - r[run[-1]] * math.cos(rel[run[-1]]),
                        r[q] * math.sin(rel[q]) - r[run[-1]] * math.sin(rel[run[-1]]),
                    )
                    < 0.6
                )
                for q in nxt
            )
            if can_resume:
                skipped += 1
                continue

        if len(run) >= 2:
            clusters.append(run)
        run = [k] if bad_mask[k] else []
        skipped = 0

    if len(run) >= 2:
        clusters.append(run)

    return clusters


def extract_clusters(
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    cluster_indices: List[List[int]],
    odom_pose: Tuple[float, float, float],
) -> Tuple[List[Dict[str, Any]], List[np.ndarray]]:
    """Преобразовать индексы кластеров в точки и центроиды в базисе одометрии."""
    r = np.asarray(ranges, dtype=float)
    rel = np.asarray(rel_angles, dtype=float)
    ox, oy, oth = odom_pose

    cos_oth = math.cos(oth)
    sin_oth = math.sin(oth)
    cos_rel = np.cos(rel)
    sin_rel = np.sin(rel)

    detected_clusters: List[Dict[str, Any]] = []
    confirmed_wall_pts: List[np.ndarray] = []

    for run in cluster_indices:
        idx = np.array(run)
        px = r[idx] * cos_rel[idx]
        py = r[idx] * sin_rel[idx]
        pts = np.column_stack([px, py])

        mean_px = float(px.mean())
        mean_py = float(py.mean())

        cluster_ox = ox + cos_oth * mean_px - sin_oth * mean_py
        cluster_oy = oy + sin_oth * mean_px + cos_oth * mean_py

        length, thickness = fit_cluster_geometry(pts)
        is_wall = length > 1.0 and thickness < 0.10
        if is_wall:
            confirmed_wall_pts.append(pts)

        detected_clusters.append(
            {
                "pts": pts,
                "ox": cluster_ox,
                "oy": cluster_oy,
                "length": length,
                "thickness": thickness,
                "is_wall": is_wall,
            }
        )

    # Второй проход: проверка продолжений стен
    for c_dict in detected_clusters:
        if not c_dict["is_wall"]:
            c_dict["is_wall_piece"] = is_wall_continuation(c_dict["pts"], confirmed_wall_pts)
        else:
            c_dict["is_wall_piece"] = False

    return detected_clusters, confirmed_wall_pts


def euclidean_cluster_points(
    pts: np.ndarray,
    eps: float = 0.6,
    min_samples: int = 2,
) -> List[np.ndarray]:
    """Евклидова кластеризация набора 2D точек на базе поиска в ширину (DBSCAN-аналог).

    Используются только стандартные средства Python и numpy.
    """
    n = len(pts)
    if n < min_samples:
        return []

    visited = np.zeros(n, dtype=bool)
    clusters: List[np.ndarray] = []

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True

        dists = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1])
        neighbors = list(np.flatnonzero(dists < eps))

        if len(neighbors) < min_samples:
            continue

        cluster_indices = [i]
        queue = [idx for idx in neighbors if idx != i]

        for idx in queue:
            if not visited[idx]:
                visited[idx] = True
                sub_dists = np.hypot(pts[:, 0] - pts[idx, 0], pts[:, 1] - pts[idx, 1])
                sub_neighbors = np.flatnonzero(sub_dists < eps)
                if len(sub_neighbors) >= min_samples:
                    for s_idx in sub_neighbors:
                        if s_idx not in queue and s_idx != i:
                            queue.append(s_idx)
            if idx not in cluster_indices:
                cluster_indices.append(idx)

        if len(cluster_indices) >= min_samples:
            clusters.append(pts[cluster_indices])

    return clusters
