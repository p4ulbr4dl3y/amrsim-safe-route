"""Локальный поиск пути A* при блокировке пути на 2D-сетке.

Подсистема глобального и локального перепланирования:
- дискретная сетка: регулярная карта проходимости с разрешением 0.5 м;
- алгоритм поиска: классический A* с евклидовой оценкой расстояния;
- сглаживание: жадное спрямление путевых точек лучами прямой видимости;
- перепланирование маршрута по сетке 0.5 м для сценария s3_blocked_corridor.

Изоляция: используются только стандартные math, typing и numpy.
"""

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .grid import (
    cell_to_coord,
    coord_to_cell,
    find_nearest_free_cell,
    is_clear_of_obstacles,
    is_line_free,
)


class _PriorityQueue:
    """Очередь с минимальным приоритетом на чистом бинарном мин-хепе Python."""

    def __init__(self) -> None:
        self.heap: List[Tuple[float, Any]] = []

    def empty(self) -> bool:
        return len(self.heap) == 0

    def put(self, priority: float, item: Any) -> None:
        self.heap.append((priority, item))
        self._sift_up(len(self.heap) - 1)

    def get(self) -> Any:
        if not self.heap:
            raise IndexError("pop from empty priority queue")
        last = self.heap.pop()
        if self.heap:
            item = self.heap[0][1]
            self.heap[0] = last
            self._sift_down(0)
            return item
        return last[1]

    def _sift_up(self, idx: int) -> None:
        while idx > 0:
            parent = (idx - 1) // 2
            if self.heap[idx][0] < self.heap[parent][0]:
                self.heap[idx], self.heap[parent] = self.heap[parent], self.heap[idx]
                idx = parent
            else:
                break

    def _sift_down(self, idx: int) -> None:
        n = len(self.heap)
        while 2 * idx + 1 < n:
            left = 2 * idx + 1
            right = left + 1
            smallest = left
            if right < n and self.heap[right][0] < self.heap[left][0]:
                smallest = right
            if self.heap[smallest][0] < self.heap[idx][0]:
                self.heap[idx], self.heap[smallest] = self.heap[smallest], self.heap[idx]
                idx = smallest
            else:
                break


def astar_search(
    start: Tuple[float, float],
    goal: Tuple[float, float],
    static_free_grid: np.ndarray,
    x_min: float,
    y_min: float,
    grid_res: float,
    obstacles: Optional[List[Tuple[float, float, float]]] = None,
    drivable_fn: Optional[Callable[..., Any]] = None,
) -> Optional[List[List[float]]]:
    """Поиск пути на 8-связной сетке A* со спрямлением лучами видимости:

    - евклидова эвристика с шагом сетки 0.5 м;
    - запас проходимости до статических и динамических препятствий 1.25 м;
    - жадное сглаживание по прямой видимости с контролем границ проезда.
    """
    obs_circles = obstacles or []
    ny, nx = static_free_grid.shape

    ci_s, cj_s = coord_to_cell(start[0], start[1], x_min, y_min, grid_res)
    ci_g, cj_g = coord_to_cell(goal[0], goal[1], x_min, y_min, grid_res)

    start_cell = find_nearest_free_cell(
        ci_s, cj_s, static_free_grid, x_min, y_min, grid_res, obs_circles, max_dist_m=3.0
    )
    goal_cell = find_nearest_free_cell(
        ci_g, cj_g, static_free_grid, x_min, y_min, grid_res, obs_circles, max_dist_m=3.0
    )

    if start_cell is None or goal_cell is None:
        return None

    nbr_offsets = [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, 1.4142),
        (-1, 1, 1.4142),
        (1, -1, 1.4142),
        (1, 1, 1.4142),
    ]

    pq = _PriorityQueue()
    pq.put(0.0, start_cell)

    g_score = {start_cell: 0.0}
    came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}

    gi, gj = goal_cell
    while not pq.empty():
        curr = pq.get()
        if curr == goal_cell:
            break

        cur_g = g_score[curr]
        ci, cj = curr

        for di, dj, cost in nbr_offsets:
            ni, nj = ci + di, cj + dj
            if not (0 <= ni < ny and 0 <= nj < nx):
                continue
            if not static_free_grid[ni, nj]:
                continue

            cx, cy = cell_to_coord(ni, nj, x_min, y_min, grid_res)
            if not is_clear_of_obstacles(cx, cy, obs_circles):
                continue

            tentative_g = cur_g + cost * grid_res
            next_cell = (ni, nj)
            if tentative_g < g_score.get(next_cell, math.inf):
                g_score[next_cell] = tentative_g
                came_from[next_cell] = curr
                h = math.hypot(ni - gi, nj - gj) * grid_res
                pq.put(tentative_g + h, next_cell)

    if goal_cell not in came_from and start_cell != goal_cell:
        return None

    path_cells = [goal_cell]
    while path_cells[-1] != start_cell:
        path_cells.append(came_from[path_cells[-1]])
    path_cells.reverse()

    coords = (
        [start]
        + [cell_to_coord(ci, cj, x_min, y_min, grid_res) for ci, cj in path_cells]
        + [goal]
    )

    if drivable_fn is None:
        return [[round(x, 2), round(y, 2)] for x, y in coords]

    shortcutted = [coords[0]]
    i = 0
    n_pts = len(coords)
    while i < n_pts - 1:
        furthest = i + 1
        for j in range(n_pts - 1, i + 1, -1):
            if is_line_free(coords[i], coords[j], drivable_fn, obs_circles):
                furthest = j
                break
        shortcutted.append(coords[furthest])
        i = furthest

    safe_pts = [p for p in shortcutted if bool(drivable_fn(p[0], p[1], margin=0.0))]
    if len(safe_pts) < 2:
        return None
    return [[round(x, 2), round(y, 2)] for x, y in safe_pts]


def replan_astar(
    current_pose: Tuple[float, float, float],
    path: np.ndarray,
    obstacle: Tuple[float, float, float, float],
    static_free_grid: np.ndarray,
    x_min: float,
    y_min: float,
    grid_res: float,
    all_obstacles: Optional[List[Tuple[float, float, float]]] = None,
    drivable_fn: Optional[Callable[..., Any]] = None,
) -> Optional[np.ndarray]:
    """Локальное перепланирование A* по сетке в обход всех препятствий сцены.

    Перепланирование маршрута по сетке 0.5 м для сценария s3_blocked_corridor:
    - условие срабатывания: полная блокировка проезда, когда боковое смещение недопустимо;
    - точка возврата: выбор ближайшего свободного узла на исходной траектории за зоной препятствия;
    - планирование обхода: построение пути алгоритмом A* по сетке 0.5 м с контролем проходимости;
    - стыковка пути: сохранение неизменным оставшегося хвоста эталонного маршрута до целевого дока.
    """
    ox, oy, r, s_obs = obstacle
    if len(path) < 2:
        return None

    obs_list = all_obstacles or [(ox, oy, r)]

    diffs = path[1:] - path[:-1]
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total_len = cum_lens[-1]

    start_pt = (current_pose[0], current_pose[1])

    s_goal = min(total_len, s_obs + 5.0)
    s_cap = min(total_len, s_obs + 40.0)
    s_try = s_obs
    if drivable_fn is not None:
        while s_try <= s_cap + 1e-9:
            idx_t = int(np.searchsorted(cum_lens, s_try) - 1)
            idx_t = max(0, min(len(seg_lens) - 1, idx_t))
            tau_t = (s_try - cum_lens[idx_t]) / max(1e-6, seg_lens[idx_t])
            cand_pt = path[idx_t] + tau_t * diffs[idx_t]
            if is_line_free(
                start_pt, (float(cand_pt[0]), float(cand_pt[1])), drivable_fn, obs_list
            ):
                s_goal = float(s_try)
                break
            s_try += 0.5

    g_idx = np.searchsorted(cum_lens, s_goal) - 1
    g_idx = max(0, min(len(seg_lens) - 1, g_idx))
    tau = (s_goal - cum_lens[g_idx]) / max(1e-6, seg_lens[g_idx])
    p_goal = tuple(path[g_idx] + tau * diffs[g_idx])

    bypass = astar_search(
        start_pt,
        p_goal,
        static_free_grid,
        x_min,
        y_min,
        grid_res,
        obstacles=obs_list,
        drivable_fn=drivable_fn,
    )
    if bypass is None:
        return None

    suffix = [path[j] for j in range(len(path)) if cum_lens[j] > s_goal]
    new_path = bypass + suffix
    if drivable_fn is not None:
        new_path = [p for p in new_path if bool(drivable_fn(p[0], p[1], margin=0.0))]
        if len(new_path) < 2:
            return None
    return np.asarray(new_path, dtype=float)


def grid_astar_path(
    start: Tuple[float, float],
    goal: Tuple[float, float],
    static_free_grid: np.ndarray,
    x_min: float,
    y_min: float,
    grid_res: float = 0.5,
    obstacles: Optional[List[Tuple[float, float, float]]] = None,
    drivable_fn: Optional[Callable[..., Any]] = None,
) -> Optional[List[List[float]]]:
    """Перепланирование маршрута по сетке 0.5 м для сценария s3_blocked_corridor.

    Поиск пути в обход блокировок и препятствий:
    - дискретизация: регулярная сетка проходимости полигона с шагом 0.5 м;
    - учет динамических препятствий: фильтрация занятых узлов карты;
    - эвристический поиск: алгоритм A* на 8-связной решетке;
    - спрямление траектории: устранение промежуточных узлов лучами прямой видимости.
    """
    return astar_search(
        start,
        goal,
        static_free_grid,
        x_min,
        y_min,
        grid_res,
        obstacles=obstacles,
        drivable_fn=drivable_fn,
    )
