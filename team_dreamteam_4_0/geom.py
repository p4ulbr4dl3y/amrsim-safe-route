"""Geometric utilities for AMR navigation, localization and perception.

Conventions:
- Coordinates in meters, Cartesian 2D (x east, y north).
- Angles in radians counterclockwise from +X (east).
- Segments stored as shape (M, 4): [x1, y1, x2, y2].
- Polygons stored as shape (K, 2): [[x, y], ...].
Only standard library (math) and numpy are used.
"""

import math
from typing import Union

import numpy as np


def wrap_angle(theta: Union[float, int, np.ndarray]) -> Union[float, np.ndarray]:
    """Normalize angle(s) to [-pi, pi].

    Supports scalar floats/ints and numpy arrays.
    """
    if isinstance(theta, (int, float, np.floating, np.integer)):
        return float((theta + math.pi) % (2.0 * math.pi) - math.pi)
    arr = np.asarray(theta)
    return (arr + np.pi) % (2.0 * np.pi) - np.pi


def rot2d(x, y=None, theta=None):
    """Rotate 2D points by angle theta (radians) counterclockwise.

    Supported calling conventions:
      rot2d(x, y, theta) -> (rx, ry)
      rot2d(pts, theta)  -> rotated_pts (shape (2,) or (N, 2))
    """
    if theta is None:
        # Вызов в формате rot2d(pts, theta)
        pts = np.asarray(x, dtype=float)
        th = float(y)
        c, s = math.cos(th), math.sin(th)
        if pts.ndim == 1:
            return np.array([pts[0] * c - pts[1] * s, pts[0] * s + pts[1] * c])
        rx = pts[:, 0] * c - pts[:, 1] * s
        ry = pts[:, 0] * s + pts[:, 1] * c
        return np.column_stack([rx, ry])

    # Вызов в формате rot2d(x, y, theta)
    if isinstance(theta, (int, float, np.floating, np.integer)):
        c, s = math.cos(theta), math.sin(theta)
    else:
        c, s = np.cos(theta), np.sin(theta)
    rx = x * c - y * s
    ry = x * s + y * c
    return rx, ry


def segments_aabb(segs: np.ndarray) -> np.ndarray:
    """Compute axis-aligned bounding boxes for segments.

    segs: (M, 4) -> (M, 4) containing [min_x, min_y, max_x, max_y].
    """
    if segs is None or len(segs) == 0:
        return np.empty((0, 4), dtype=float)
    return np.column_stack(
        [
            np.minimum(segs[:, 0], segs[:, 2]),
            np.minimum(segs[:, 1], segs[:, 3]),
            np.maximum(segs[:, 0], segs[:, 2]),
            np.maximum(segs[:, 1], segs[:, 3]),
        ]
    )


def filter_segs_aabb(
    segs: np.ndarray, x: float, y: float, radius: float, aabb: np.ndarray = None
) -> np.ndarray:
    """Filter segments whose AABB intersects the box [x - radius, y - radius, x + radius, y + radius]."""
    if segs is None or len(segs) == 0:
        return np.empty((0, 4), dtype=float)
    if aabb is None:
        aabb = segments_aabb(segs)
    mask = (
        (aabb[:, 2] >= x - radius)
        & (aabb[:, 0] <= x + radius)
        & (aabb[:, 3] >= y - radius)
        & (aabb[:, 1] <= y + radius)
    )
    return segs[mask]


def raycast(
    ox: float, oy: float, angles: np.ndarray, segs: np.ndarray, max_range: float = np.inf
) -> np.ndarray:
    """Vectorized raycast of lidar rays against 2D line segments with AABB pruning.

    ox, oy: lidar origin coordinates
    angles: 1D array of ray angles in world frame (radians)
    segs: (M, 4) array of segment endpoints [x1, y1, x2, y2]
    max_range: maximum detection distance (default inf)

    Returns:
      ranges: 1D array of distances to first intersection along each ray (inf if none).
    """
    angles_arr = np.asarray(angles, dtype=float)
    is_scalar_angle = angles_arr.ndim == 0
    angles_arr = np.atleast_1d(angles_arr)

    if len(angles_arr) == 0:
        return np.empty(0, dtype=float)

    if segs is None or len(segs) == 0:
        out = np.full(angles_arr.shape, np.inf)
        return float(out[0]) if is_scalar_angle else out

    segs_arr = np.asarray(segs, dtype=float)

    # Отсечение по ограничивающему прямоугольнику AABB при конечном max_range
    if np.isfinite(max_range) and max_range > 0.0:
        seg_min_x = np.minimum(segs_arr[:, 0], segs_arr[:, 2])
        seg_max_x = np.maximum(segs_arr[:, 0], segs_arr[:, 2])
        seg_min_y = np.minimum(segs_arr[:, 1], segs_arr[:, 3])
        seg_max_y = np.maximum(segs_arr[:, 1], segs_arr[:, 3])
        mask = (
            (seg_max_x >= ox - max_range)
            & (seg_min_x <= ox + max_range)
            & (seg_max_y >= oy - max_range)
            & (seg_min_y <= oy + max_range)
        )
        segs_arr = segs_arr[mask]
        if len(segs_arr) == 0:
            out = np.full(angles_arr.shape, np.inf)
            return float(out[0]) if is_scalar_angle else out

    dx = np.cos(angles_arr)  # (K,)
    dy = np.sin(angles_arr)  # (K,)

    px = segs_arr[:, 0] - ox  # (M,)
    py = segs_arr[:, 1] - oy  # (M,)
    ex = segs_arr[:, 2] - segs_arr[:, 0]  # (M,)
    ey = segs_arr[:, 3] - segs_arr[:, 1]  # (M,)

    # 2D векторное произведение направления луча и вектора отрезка: (K, M)
    den = dx[:, None] * ey[None, :] - dy[:, None] * ex[None, :]

    cpe = (px * ey - py * ex)[None, :]  # (1, M)
    cpd = px[None, :] * dy[:, None] - py[None, :] * dx[:, None]  # (K, M)

    with np.errstate(divide="ignore", invalid="ignore"):
        t = cpe / den
        u = cpd / den

    ok = (np.abs(den) > 1e-12) & (t > 1e-9) & (u >= 0.0) & (u <= 1.0)
    if np.isfinite(max_range):
        ok = ok & (t <= max_range)

    hits = np.where(ok, t, np.inf)
    res = hits.min(axis=1)

    return float(res[0]) if is_scalar_angle else res


def seg_dist(px, py, segs: np.ndarray) -> Union[float, np.ndarray]:
    """Distance from point(s) to the nearest segment (vectorized).

    px, py: scalars or 1D arrays of point coordinates.
    segs: (M, 4) array of segments [ax, ay, bx, by].

    Returns:
      scalar float if px, py are scalars, else (N,) array of minimum distances.
    """
    is_scalar = np.ndim(px) == 0 and np.ndim(py) == 0
    px_arr = np.atleast_1d(np.asarray(px, dtype=float))
    py_arr = np.atleast_1d(np.asarray(py, dtype=float))

    if segs is None or len(segs) == 0 or len(px_arr) == 0:
        res = np.full(len(px_arr), np.inf)
        return float(res[0]) if is_scalar else res

    segs_arr = np.asarray(segs, dtype=float)
    ax, ay = segs_arr[:, 0], segs_arr[:, 1]
    bx, by = segs_arr[:, 2], segs_arr[:, 3]
    ex, ey = bx - ax, by - ay

    ll = np.maximum(ex * ex + ey * ey, 1e-12)

    # Параметр u ближайшей точки на отрезке: (N, M)
    u = np.clip(
        (
            (px_arr[:, None] - ax[None, :]) * ex[None, :]
            + (py_arr[:, None] - ay[None, :]) * ey[None, :]
        )
        / ll[None, :],
        0.0,
        1.0,
    )

    cx = ax[None, :] + u * ex[None, :]
    cy = ay[None, :] + u * ey[None, :]

    dx = cx - px_arr[:, None]
    dy = cy - py_arr[:, None]

    dists = np.sqrt(dx * dx + dy * dy).min(axis=1)
    return float(dists[0]) if is_scalar else dists


class Displacement(tuple):
    """Result of point_to_segs_displacement.

    Unpacks as tuple: (normals, projs, dists).
    Also provides attributes:
      .normals (alias .normal): unit normal pointing from wall to point ((N, 2) or (2,))
      .projs   (alias .proj):   closest point on nearest segment ((N, 2) or (2,))
      .dists   (alias .dist):   distance to nearest segment ((N,) or float)
      .seg_idx:                 index of nearest segment ((N,) or int)
    """

    normals: np.ndarray
    projs: np.ndarray
    dists: Union[float, np.ndarray]
    seg_idx: Union[int, np.ndarray]

    def __new__(cls, normals, projs, dists, seg_idx=None):
        inst = super().__new__(cls, (normals, projs, dists))
        inst.normals = normals
        inst.normal = normals
        inst.projs = projs
        inst.proj = projs
        inst.dists = dists
        inst.dist = dists
        inst.seg_idx = seg_idx
        return inst


def point_to_segs_displacement(px, py, segs: np.ndarray) -> Displacement:
    """Compute normal vector, projection point, and distance to nearest segment.

    Used for scan-matching Gauss-Newton Jacobian and residuals.

    px, py: scalars or 1D arrays of points (world frame).
    segs: (M, 4) array of segments [ax, ay, bx, by].

    Returns:
      Displacement instance: unpacks as (normals, projs, dists).
      - normals: unit normal pointing from closest point to query point ((N, 2) or (2,)).
      - projs:   closest point coordinates ((N, 2) or (2,)).
      - dists:   Euclidean distance ((N,) or float).
      - seg_idx: index of nearest segment ((N,) or int).
    """
    is_scalar = np.ndim(px) == 0 and np.ndim(py) == 0
    px_arr = np.atleast_1d(np.asarray(px, dtype=float))
    py_arr = np.atleast_1d(np.asarray(py, dtype=float))
    n_pts = len(px_arr)

    if segs is None or len(segs) == 0 or n_pts == 0:
        normals = np.full((n_pts, 2), np.nan)
        projs = np.full((n_pts, 2), np.nan)
        dists = np.full(n_pts, np.inf)
        seg_idx = np.full(n_pts, -1, dtype=int)
        if is_scalar:
            return Displacement(normals[0], projs[0], float(dists[0]), int(seg_idx[0]))
        return Displacement(normals, projs, dists, seg_idx)

    segs_arr = np.asarray(segs, dtype=float)
    ax, ay = segs_arr[:, 0], segs_arr[:, 1]
    bx, by = segs_arr[:, 2], segs_arr[:, 3]
    ex, ey = bx - ax, by - ay

    ll = np.maximum(ex * ex + ey * ey, 1e-12)

    # Параметр u: (N, M)
    u = np.clip(
        (
            (px_arr[:, None] - ax[None, :]) * ex[None, :]
            + (py_arr[:, None] - ay[None, :]) * ey[None, :]
        )
        / ll[None, :],
        0.0,
        1.0,
    )

    cx = ax[None, :] + u * ex[None, :]  # (N, M)
    cy = ay[None, :] + u * ey[None, :]  # (N, M)

    dx = px_arr[:, None] - cx  # Вектор от точки стены к точке запроса
    dy = py_arr[:, None] - cy
    dist_matrix = np.sqrt(dx * dx + dy * dy)  # (N, M)

    best_idx = np.argmin(dist_matrix, axis=1)  # (N,)
    row_idx = np.arange(n_pts)

    best_dist = dist_matrix[row_idx, best_idx]  # (N,)
    best_cx = cx[row_idx, best_idx]  # (N,)
    best_cy = cy[row_idx, best_idx]  # (N,)
    best_projs = np.column_stack([best_cx, best_cy])

    # Вектор направления от стены к точке запроса
    best_dx = dx[row_idx, best_idx]
    best_dy = dy[row_idx, best_idx]

    # Нормаль отрезка по умолчанию, если точка лежит прямо на отрезке (дистанция ~ 0)
    seg_len = np.sqrt(ll[best_idx])
    default_nx = -ey[best_idx] / seg_len
    default_ny = ex[best_idx] / seg_len

    has_dist = best_dist > 1e-9
    inv_d = np.where(has_dist, 1.0 / np.maximum(best_dist, 1e-12), 0.0)

    norm_x = np.where(has_dist, best_dx * inv_d, default_nx)
    norm_y = np.where(has_dist, best_dy * inv_d, default_ny)
    best_normals = np.column_stack([norm_x, norm_y])

    if is_scalar:
        return Displacement(best_normals[0], best_projs[0], float(best_dist[0]), int(best_idx[0]))
    return Displacement(best_normals, best_projs, best_dist, best_idx)


def inside_polygon(x, y=None, poly=None) -> Union[bool, np.ndarray]:
    """Test whether point(s) lie inside a 2D polygon using even-odd crossing rule.

    Supported calling conventions:
      inside_polygon(x, y, poly) -> bool or (N,) boolean array
      inside_polygon(pts, poly)  -> bool or (N,) boolean array
    """
    if poly is None:
        pts = np.asarray(x, dtype=float)
        poly_arr = np.asarray(y, dtype=float)
        is_single = pts.ndim == 1
        pts_arr = np.atleast_2d(pts)
        px = pts_arr[:, 0]
        py = pts_arr[:, 1]
    else:
        is_single = np.ndim(x) == 0 and np.ndim(y) == 0
        px = np.atleast_1d(np.asarray(x, dtype=float))
        py = np.atleast_1d(np.asarray(y, dtype=float))
        poly_arr = np.asarray(poly, dtype=float)

    if len(poly_arr) < 3 or len(px) == 0:
        res = np.zeros(len(px), dtype=bool)
        return bool(res[0]) if is_single else res

    x_q = px[:, None]
    y_q = py[:, None]

    x1 = poly_arr[:, 0][None, :]
    y1 = poly_arr[:, 1][None, :]
    x2 = np.roll(poly_arr[:, 0], -1)[None, :]
    y2 = np.roll(poly_arr[:, 1], -1)[None, :]

    straddle = (y1 > y_q) != (y2 > y_q)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_cross = x1 + (y_q - y1) * (x2 - x1) / (y2 - y1)

    crossings = straddle & (x_q < x_cross)
    inside = (crossings.sum(axis=1) % 2) == 1

    return bool(inside[0]) if is_single else inside


def box_segs(poly) -> np.ndarray:
    """Extract line segments [x1, y1, x2, y2] from polygon(s).

    Accepts:
      - (K, 2) array / list of vertices representing a single closed polygon -> (K, 4)
      - dict with 'polygon' key -> (K, 4)
      - list/collection of polygons or building dicts -> (M, 4)
    """
    if poly is None:
        return np.empty((0, 4), dtype=float)

    if isinstance(poly, dict) and "polygon" in poly:
        poly = poly["polygon"]

    # Проверка: коллекция полигонов или одиночный полигон
    if isinstance(poly, (list, tuple)) and len(poly) > 0:
        first = poly[0]
        if isinstance(first, dict) and "polygon" in first:
            # Коллекция словарей
            segs_list = [box_segs(item["polygon"]) for item in poly]
            valid = [s for s in segs_list if len(s) > 0]
            return np.vstack(valid) if valid else np.empty((0, 4), dtype=float)
        if isinstance(first, (list, tuple, np.ndarray)):
            first_arr = np.asarray(first)
            # Если элементы являются 2D массивами или списком списков точек (вложенные полигоны)
            if first_arr.ndim == 2 and first_arr.shape[1] == 2:
                # poly является списком полигонов
                segs_list = [box_segs(item) for item in poly]
                valid = [s for s in segs_list if len(s) > 0]
                return np.vstack(valid) if valid else np.empty((0, 4), dtype=float)

    p = np.asarray(poly, dtype=float)
    if p.ndim != 2 or p.shape[0] < 2 or p.shape[1] != 2:
        return np.empty((0, 4), dtype=float)

    nxt = np.roll(p, -1, axis=0)
    return np.hstack([p, nxt])


def polygon_area(poly) -> float:
    """Signed area of 2D polygon (positive if counterclockwise)."""
    p = np.asarray(poly, dtype=float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
