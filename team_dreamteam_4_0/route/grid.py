"""Дискретная сетка препятствий, дилатация/инфляция и геометрические проверки проезда.

Изоляция: используются только стандартные math, typing и numpy.
"""

import math
from typing import Any, Callable, List, Optional, Tuple, Union

import numpy as np

try:
    from ..geom import inside_polygon
except (ImportError, ValueError):
    from geom import inside_polygon


def is_drivable(
    x: Union[float, np.ndarray],
    y: Optional[Union[float, np.ndarray]] = None,
    drivable_polys: Optional[List[np.ndarray]] = None,
    forbidden_polys: Optional[List[np.ndarray]] = None,
    margin: float = 0.2,
) -> Union[bool, np.ndarray]:
    """Проверить, что 2D координаты внутри проезжего полигона, вне FB_HAZ,

    и не ближе margin метров к границам проезжей части.
    """
    d_polys = drivable_polys or []
    f_polys = forbidden_polys or []

    if y is None:
        pts = np.atleast_2d(np.asarray(x, dtype=float))
        is_single = np.ndim(x) == 1
    else:
        is_single = np.ndim(x) == 0 and np.ndim(y) == 0
        px = np.atleast_1d(np.asarray(x, dtype=float))
        py = np.atleast_1d(np.asarray(y, dtype=float))
        pts = np.column_stack([px, py])

    def _check(p: np.ndarray) -> np.ndarray:
        in_d = np.zeros(len(p), dtype=bool)
        for poly in d_polys:
            in_d |= inside_polygon(p, poly)
        in_f = np.zeros(len(p), dtype=bool)
        for poly in f_polys:
            in_f |= inside_polygon(p, poly)
        return in_d & (~in_f)

    valid = _check(pts)
    if margin > 0.0:
        diag = margin * 0.70710678
        offsets = [
            (margin, 0.0),
            (-margin, 0.0),
            (0.0, margin),
            (0.0, -margin),
            (diag, diag),
            (-diag, diag),
            (diag, -diag),
            (-diag, -diag),
        ]
        for dx, dy in offsets:
            valid &= _check(pts + np.array([dx, dy]))

    return bool(valid[0]) if is_single else valid


def build_static_free_grid(
    drivable_polys: List[np.ndarray],
    forbidden_polys: List[np.ndarray],
    grid_res: float = 0.5,
    grid_margin: float = 0.2,
) -> Tuple[np.ndarray, float, float, float, float, int, int]:
    """Построить статическую двумерную сетку свободных ячеек с учетом запаса margin."""
    if drivable_polys:
        all_pts = np.vstack(drivable_polys)
        x_min = float(all_pts[:, 0].min()) - 3.0
        y_min = float(all_pts[:, 1].min()) - 3.0
        x_max = float(all_pts[:, 0].max()) + 3.0
        y_max = float(all_pts[:, 1].max()) + 3.0
    else:
        x_min, y_min, x_max, y_max = 0.0, 0.0, 250.0, 200.0

    nx = int(math.ceil((x_max - x_min) / grid_res)) + 1
    ny = int(math.ceil((y_max - y_min) / grid_res)) + 1

    xs = x_min + np.arange(nx) * grid_res
    ys = y_min + np.arange(ny) * grid_res
    gx, gy = np.meshgrid(xs, ys)
    pts = np.column_stack([gx.ravel(), gy.ravel()])

    in_d = np.zeros(len(pts), dtype=bool)
    for poly in drivable_polys:
        in_d |= inside_polygon(pts, poly)

    in_f = np.zeros(len(pts), dtype=bool)
    for poly in forbidden_polys:
        in_f |= inside_polygon(pts, poly)

    free_mask = in_d & (~in_f)

    if grid_margin > 0.0:
        cand = np.flatnonzero(free_mask)
        if cand.size:
            ok = np.asarray(
                is_drivable(
                    pts[cand],
                    drivable_polys=drivable_polys,
                    forbidden_polys=forbidden_polys,
                    margin=grid_margin,
                ),
                dtype=bool,
            )
            free_mask[cand[~ok]] = False

    static_free_grid = free_mask.reshape((ny, nx))
    return static_free_grid, x_min, y_min, x_max, y_max, nx, ny


def coord_to_cell(
    x: float, y: float, x_min: float, y_min: float, grid_res: float
) -> Tuple[int, int]:
    """Преобразовать декартовы координаты (x, y) в индексы сетки (ci, cj)."""
    ci = int(round((y - y_min) / grid_res))
    cj = int(round((x - x_min) / grid_res))
    return ci, cj


def cell_to_coord(
    ci: int, cj: int, x_min: float, y_min: float, grid_res: float
) -> Tuple[float, float]:
    """Преобразовать индексы сетки (ci, cj) в декартовы координаты (x, y)."""
    x = x_min + cj * grid_res
    y = y_min + ci * grid_res
    return x, y


def parse_obstacles(obstacles: Any) -> List[Tuple[float, float, float]]:
    """Извлечь список кортежей [(x, y, radius)] из различных структур данных."""
    if obstacles is None:
        return []
    out: List[Tuple[float, float, float]] = []
    if isinstance(obstacles, (list, tuple)):
        for o in obstacles:
            if isinstance(o, dict):
                ox = float(o.get("x", 0.0))
                oy = float(o.get("y", 0.0))
                r = float(o.get("r", o.get("radius", 0.4)))
                out.append((ox, oy, r))
            elif isinstance(o, (list, tuple, np.ndarray)):
                ox = float(o[0])
                oy = float(o[1])
                r = float(o[2]) if len(o) >= 3 else 0.4
                out.append((ox, oy, r))
    elif isinstance(obstacles, np.ndarray):
        if obstacles.ndim == 2:
            for row in obstacles:
                ox, oy = float(row[0]), float(row[1])
                r = float(row[2]) if len(row) >= 3 else 0.4
                out.append((ox, oy, r))
    return out


def inflate_obstacles(
    obstacles: List[Tuple[float, float, float]], safe_margin: float = 1.25
) -> List[Tuple[float, float, float]]:
    """Дилатация/инфляция препятствий на запас безопасности safe_margin."""
    return [(ox, oy, r + safe_margin) for ox, oy, r in obstacles]


def is_clear_of_obstacles(
    x: float,
    y: float,
    obs_circles: List[Tuple[float, float, float]],
    safe_margin: float = 1.25,
) -> bool:
    """Проверить, что точка (x, y) находится на расстоянии не менее safe_margin + r от всех препятствий."""
    for ox, oy, r in obs_circles:
        req_dist = safe_margin + r
        if math.hypot(x - ox, y - oy) < req_dist:
            return False
    return True


def find_nearest_free_cell(
    ci: int,
    cj: int,
    static_free_grid: np.ndarray,
    x_min: float,
    y_min: float,
    grid_res: float,
    obs_circles: List[Tuple[float, float, float]],
    max_dist_m: float = 3.0,
    safe_margin: float = 1.25,
) -> Optional[Tuple[int, int]]:
    """Найти ближайшую свободную ячейку сетки в радиусе max_dist_m."""
    ny, nx = static_free_grid.shape
    k = int(math.ceil(max_dist_m / grid_res))
    best_cell = None
    best_d2 = math.inf
    for di in range(-k, k + 1):
        for dj in range(-k, k + 1):
            ni, nj = ci + di, cj + dj
            if 0 <= ni < ny and 0 <= nj < nx and static_free_grid[ni, nj]:
                cx, cy = cell_to_coord(ni, nj, x_min, y_min, grid_res)
                if is_clear_of_obstacles(cx, cy, obs_circles, safe_margin=safe_margin):
                    d2 = di * di + dj * dj
                    if d2 < best_d2:
                        best_d2 = d2
                        best_cell = (ni, nj)
    return best_cell


def is_line_free(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    drivable_fn: Callable[..., Any],
    obs_circles: List[Tuple[float, float, float]],
    margin: float = 0.2,
    safe_margin: float = 1.25,
) -> bool:
    """Проверить, что прямой отрезок между p1 и p2 свободен."""
    dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    steps = max(2, int(math.ceil(dist / 0.25)))
    ts = np.linspace(0.0, 1.0, steps)
    pts = np.column_stack([p1[0] + ts * (p2[0] - p1[0]), p1[1] + ts * (p2[1] - p1[1])])

    if not bool(np.all(drivable_fn(pts, margin=margin))):
        return False

    for ox, oy, r in obs_circles:
        req_dist = safe_margin + r
        if bool(np.any(np.hypot(pts[:, 0] - ox, pts[:, 1] - oy) < req_dist)):
            return False
    return True


def lateral_clearance(
    point: Tuple[float, float],
    normal: np.ndarray,
    drivable_fn: Callable[..., Any],
    max_dist: float = 3.0,
    margin: float = 0.2,
) -> float:
    """Наибольшее смещение вдоль normal, сохраняющее запас margin до границы проезда."""
    step = 0.2
    travelled = 0.0
    while travelled + step <= max_dist + 1e-9:
        dist = travelled + step
        if not drivable_fn(
            point[0] + dist * normal[0], point[1] + dist * normal[1], margin=margin
        ):
            break
        travelled = dist
    return travelled
