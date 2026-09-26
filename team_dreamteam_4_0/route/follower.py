"""Класс RouteFollower: интеграция миссий, докинга, объезда и перепланирования.

Изоляция: используются только стандартные math, typing и numpy.
"""

import math
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

try:
    from ..geom import box_segs, wrap_angle
except (ImportError, ValueError):
    from geom import box_segs, wrap_angle

from .astar import astar_search, replan_astar
from .grid import (
    build_static_free_grid,
    cell_to_coord,
    coord_to_cell,
    find_nearest_free_cell,
    is_clear_of_obstacles,
    is_drivable,
    is_line_free,
    lateral_clearance,
    parse_obstacles,
)
from .pure_pursuit import (
    check_speed_zones,
    compute_curvature_speed_limit,
    compute_pure_pursuit_cmd,
    compute_stanley_cmd,
    get_path_progress,
)


def check_obstacles_in_tube(
    path: np.ndarray,
    obstacles: Any,
    current_s: float,
    tube_radius: float = 1.25,
) -> Optional[Tuple[float, float, float, float]]:
    """Определить, проникает ли препятствие в опорную трубку или требует бокового объезда."""
    parsed = parse_obstacles(obstacles)
    if not parsed or len(path) < 2:
        return None

    diffs = path[1:] - path[:-1]
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])

    best_obs = None
    min_s = math.inf

    for ox, oy, r in parsed:
        for i in range(len(seg_lens)):
            p1 = path[i]
            v = diffs[i]
            L = seg_lens[i]
            if L < 1e-6:
                continue
            u = np.clip(((ox - p1[0]) * v[0] + (oy - p1[1]) * v[1]) / (L * L), 0.0, 1.0)
            proj = p1 + u * v
            s_obs = cum_lens[i] + u * L

            if s_obs < current_s - 0.5 or s_obs > current_s + 35.0:
                continue
            if s_obs > cum_lens[-1] - 3.0:
                continue

            dist_center = math.hypot(ox - proj[0], oy - proj[1])
            dist_edge = dist_center - r

            if dist_edge < max(tube_radius, 2.0):
                if s_obs < min_s:
                    min_s = s_obs
                    best_obs = (ox, oy, r, s_obs)

    return best_obs


def apply_lateral_offset(
    path: np.ndarray,
    obstacle: Tuple[float, float, float, float],
    current_s: float,
    all_obstacles: Optional[List[Tuple[float, float, float]]] = None,
    drivable_fn: Optional[Callable[..., Any]] = None,
) -> Tuple[Optional[np.ndarray], float]:
    """Применить боковое смещение к полилинии шагами 0.2 м."""
    ox, oy, r, s_obs = obstacle
    if len(path) < 2:
        return None, 0.0

    obs_list = all_obstacles or [(ox, oy, r)]

    diffs = path[1:] - path[:-1]
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total_len = cum_lens[-1]

    idx = np.searchsorted(cum_lens, s_obs) - 1
    idx = max(0, min(len(seg_lens) - 1, idx))
    v = diffs[idx]
    L = max(seg_lens[idx], 1e-6)
    u_dir = v / L
    normal = np.array([-u_dir[1], u_dir[0]])  # Левая нормаль

    p1 = path[idx]
    d_lat_obs = (ox - p1[0]) * normal[0] + (oy - p1[1]) * normal[1]

    t_obs = (s_obs - cum_lens[idx]) / max(1e-6, L)
    p_obs = p1 + t_obs * diffs[idx]

    if drivable_fn is not None:
        c_plus = lateral_clearance((float(p_obs[0]), float(p_obs[1])), normal, drivable_fn)
        c_minus = lateral_clearance((float(p_obs[0]), float(p_obs[1])), -normal, drivable_fn)
    else:
        c_plus, c_minus = 1.0, 1.0

    if abs(c_plus - c_minus) < 0.05:
        prefer = -1.0 if d_lat_obs >= 0.0 else 1.0
    else:
        prefer = 1.0 if c_plus > c_minus else -1.0

    base_shifts = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
    candidates = [prefer * s for s in base_shifts] + [-prefer * s for s in base_shifts]

    s_ramp_in = max(current_s, s_obs - 4.5)
    s_plat_in = s_obs - 2.0
    s_plat_out = s_obs + 2.0
    s_ramp_out = min(total_len, s_obs + 4.5)

    for delta in candidates:
        s_samples = np.arange(s_ramp_in, s_ramp_out + 0.2, 0.25)
        pts_shifted = []
        feasible = True

        for s_val in s_samples:
            if s_val <= s_ramp_in:
                w = 0.0
            elif s_val < s_plat_in:
                w = (s_val - s_ramp_in) / max(1e-6, s_plat_in - s_ramp_in)
            elif s_val <= s_plat_out:
                w = 1.0
            elif s_val < s_ramp_out:
                w = 1.0 - (s_val - s_plat_out) / max(1e-6, s_ramp_out - s_plat_out)
            else:
                w = 0.0

            s_idx = np.searchsorted(cum_lens, s_val) - 1
            s_idx = max(0, min(len(seg_lens) - 1, s_idx))
            tau = (s_val - cum_lens[s_idx]) / max(1e-6, seg_lens[s_idx])
            p_orig = path[s_idx] + tau * diffs[s_idx]

            p_shift = p_orig + w * delta * normal
            pts_shifted.append(p_shift)

            if s_plat_in <= s_val <= s_plat_out:
                for o_x, o_y, o_r in obs_list:
                    if math.hypot(p_shift[0] - o_x, p_shift[1] - o_y) < 0.9 + o_r + 1.1001:
                        feasible = False
                        break
                if not feasible:
                    break

            if drivable_fn is not None and not drivable_fn(p_shift[0], p_shift[1], margin=0.2):
                feasible = False
                break

        if feasible and len(pts_shifted) > 0:
            prefix = [path[j] for j in range(len(path)) if cum_lens[j] < s_ramp_in - 0.1]
            suffix = [path[j] for j in range(len(path)) if cum_lens[j] > s_ramp_out + 0.1]
            new_path = prefix + pts_shifted + suffix
            return np.asarray(new_path, dtype=float), float(delta)

    return None, 0.0


class RouteFollower:
    """Следователь маршрута AMR методом чистого преследования и локальный планировщик пути."""

    def __init__(
        self,
        map_dict: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.map_dict = map_dict or {}
        self.config = config or {}

        self.drivable_polys: List[np.ndarray] = []
        self.forbidden_polys: List[np.ndarray] = []
        self.speed_zones: List[Dict[str, Any]] = []
        self.points: Dict[str, Dict[str, Any]] = {}
        self.building_segs: np.ndarray = np.empty((0, 4), dtype=float)

        self._parse_map(self.map_dict)

        self.grid_res = 0.5
        self.grid_margin = 0.2
        self._init_grid()

        self.current_mission_id: Optional[str] = None
        self.reference_path: np.ndarray = np.empty((0, 2), dtype=float)
        self.active_path: np.ndarray = np.empty((0, 2), dtype=float)
        self.last_s: float = 0.0
        self.arrived: bool = False
        self.hold_count: int = 0
        self.note: Optional[str] = None

        self.last_replan_t: float = -10.0
        self.replan_interval: float = 2.0

        self.t_start: Optional[float] = None
        self.deadline_s: Optional[float] = None
        self.time_left: Optional[float] = None
        self.final_approach: bool = False
        self.last_offset_dy: float = 0.0
        self.last_w: float = 0.0
        self.a_lat_max: float = float(self.config.get("a_lat_max", 0.85))

    def _parse_map(self, m: Dict[str, Any]) -> None:
        if "drivable" in m:
            self.drivable_polys = [np.asarray(p, dtype=float) for p in m["drivable"]]
        if "zones" in m:
            for z in m["zones"]:
                z_type = z.get("type", "")
                z_id = z.get("id", "")
                if z_type == "forbidden" or z_id == "FB_HAZ":
                    self.forbidden_polys.append(np.asarray(z["polygon"], dtype=float))
                elif z_type == "speed_limit" or "v_max" in z:
                    self.speed_zones.append(
                        {
                            "id": z_id,
                            "v_max": float(z["v_max"]),
                            "polygon": np.asarray(z["polygon"], dtype=float),
                        }
                    )
        if "points" in m:
            self.points = m["points"]
        if "buildings" in m:
            self.building_segs = box_segs(m["buildings"])

    def _init_grid(self) -> None:
        (
            self.static_free_grid,
            self.x_min,
            self.y_min,
            self.x_max,
            self.y_max,
            self.nx,
            self.ny,
        ) = build_static_free_grid(
            self.drivable_polys,
            self.forbidden_polys,
            grid_res=self.grid_res,
            grid_margin=self.grid_margin,
        )

    def is_drivable(
        self,
        x: Union[float, np.ndarray],
        y: Optional[Union[float, np.ndarray]] = None,
        margin: float = 0.2,
    ) -> Union[bool, np.ndarray]:
        """Проверить, что 2D координаты внутри проезда и не ближе margin к границе."""
        return is_drivable(
            x,
            y,
            drivable_polys=self.drivable_polys,
            forbidden_polys=self.forbidden_polys,
            margin=margin,
        )

    def check_speed_zones(self, x: float, y: float, th: float) -> float:
        """Проверить текущую точку, +3.0 м впереди и -1.5 м позади на попадание в скоростные зоны."""
        return check_speed_zones(x, y, th, self.speed_zones)

    def get_point_xy(
        self,
        pt_ident: Any,
        fallback: Optional[Union[List[float], np.ndarray]] = None,
    ) -> Tuple[float, float]:
        """Преобразовать идентификатор дока или путевой точки в координаты (x, y)."""
        if isinstance(pt_ident, str) and pt_ident in self.points:
            p = self.points[pt_ident]
            return float(p["x"]), float(p["y"])
        if isinstance(pt_ident, dict) and "x" in pt_ident and "y" in pt_ident:
            return float(pt_ident["x"]), float(pt_ident["y"])
        if isinstance(pt_ident, (list, tuple, np.ndarray)) and len(pt_ident) >= 2:
            return float(pt_ident[0]), float(pt_ident[1])
        if fallback is not None and len(fallback) >= 2:
            return float(fallback[0]), float(fallback[1])
        return 0.0, 0.0

    def update_mission(
        self, mission: Dict[str, Any], pose: Tuple[float, float, float]
    ) -> None:
        """Обработать обновления миссии и при необходимости построить начальный участок подъезда."""
        m_id = mission.get("id")
        if m_id == self.current_mission_id and len(self.active_path) > 0:
            return

        self.current_mission_id = m_id
        ref_path = np.asarray(mission["reference_path"], dtype=float)
        self.reference_path = ref_path
        self.active_path = ref_path.copy()
        self.arrived = False
        self.hold_count = 0
        self.last_s = 0.0
        self.note = None
        self.last_replan_t = -10.0
        self.last_offset_dy = 0.0
        self.last_w = 0.0

        t_start = mission.get("t_start")
        self.t_start = float(t_start) if t_start is not None else None
        deadline = mission.get("deadline_s")
        self.deadline_s = float(deadline) if deadline is not None else None
        self.time_left = None
        self.final_approach = False

        from_xy = self.get_point_xy(mission.get("from"), fallback=ref_path[0])
        dist_to_from = math.hypot(pose[0] - from_xy[0], pose[1] - from_xy[1])

        if dist_to_from > 1.5:
            init_leg = self.plan_path((pose[0], pose[1]), from_xy)
            if init_leg is not None and len(init_leg) > 0:
                init_arr = np.asarray(init_leg, dtype=float)
                if (
                    np.hypot(
                        init_arr[-1, 0] - ref_path[0, 0],
                        init_arr[-1, 1] - ref_path[0, 1],
                    )
                    < 0.2
                ):
                    self.active_path = np.vstack([init_arr[:-1], ref_path])
                else:
                    self.active_path = np.vstack([init_arr, ref_path])
            else:
                self.active_path = ref_path.copy()
        else:
            self.active_path = ref_path.copy()

    def plan_path(
        self,
        start: Tuple[float, float],
        goal: Tuple[float, float],
        obstacles: Optional[List[Tuple[float, float, float]]] = None,
    ) -> Optional[List[List[float]]]:
        """Вычислить путь между началом и целью в обход препятствий и FB_HAZ."""
        return self._astar_search(start, goal, obstacles=obstacles)

    def _coord_to_cell(self, x: float, y: float) -> Tuple[int, int]:
        return coord_to_cell(x, y, self.x_min, self.y_min, self.grid_res)

    def _cell_to_coord(self, ci: int, cj: int) -> Tuple[float, float]:
        return cell_to_coord(ci, cj, self.x_min, self.y_min, self.grid_res)

    def _find_nearest_free_cell(
        self,
        ci: int,
        cj: int,
        obs_circles: List[Tuple[float, float, float]],
        max_dist_m: float = 3.0,
    ) -> Optional[Tuple[int, int]]:
        return find_nearest_free_cell(
            ci,
            cj,
            self.static_free_grid,
            self.x_min,
            self.y_min,
            self.grid_res,
            obs_circles,
            max_dist_m=max_dist_m,
        )

    def _is_clear_of_obstacles(
        self, x: float, y: float, obs_circles: List[Tuple[float, float, float]]
    ) -> bool:
        return is_clear_of_obstacles(x, y, obs_circles)

    def _lateral_clearance(
        self, point: Tuple[float, float], normal: np.ndarray, max_dist: float = 3.0
    ) -> float:
        return lateral_clearance(point, normal, self.is_drivable, max_dist=max_dist)

    def _line_free(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        obs_circles: List[Tuple[float, float, float]],
        margin: float = 0.2,
    ) -> bool:
        return is_line_free(p1, p2, self.is_drivable, obs_circles, margin=margin)

    def _astar_search(
        self,
        start: Tuple[float, float],
        goal: Tuple[float, float],
        obstacles: Optional[List[Tuple[float, float, float]]] = None,
    ) -> Optional[List[List[float]]]:
        return astar_search(
            start,
            goal,
            self.static_free_grid,
            self.x_min,
            self.y_min,
            self.grid_res,
            obstacles=obstacles,
            drivable_fn=self.is_drivable,
        )

    def _parse_obstacles(self, obstacles: Any) -> List[Tuple[float, float, float]]:
        return parse_obstacles(obstacles)

    def _get_path_progress(
        self, path: np.ndarray, x: float, y: float, last_s: float = 0.0
    ) -> float:
        return get_path_progress(path, x, y, last_s=last_s)

    def check_obstacles_in_tube(
        self,
        path: np.ndarray,
        obstacles: Any,
        current_s: float,
        tube_radius: float = 1.25,
    ) -> Optional[Tuple[float, float, float, float]]:
        return check_obstacles_in_tube(path, obstacles, current_s, tube_radius=tube_radius)

    def apply_lateral_offset(
        self,
        path: np.ndarray,
        obstacle: Tuple[float, float, float, float],
        current_s: float,
        all_obstacles: Optional[List[Tuple[float, float, float]]] = None,
    ) -> Optional[np.ndarray]:
        shifted, dy = apply_lateral_offset(
            path,
            obstacle,
            current_s,
            all_obstacles=all_obstacles,
            drivable_fn=self.is_drivable,
        )
        if shifted is not None:
            self.last_offset_dy = dy
        return shifted

    def replan_astar(
        self,
        current_pose: Tuple[float, float, float],
        path: np.ndarray,
        obstacle: Tuple[float, float, float, float],
        all_obstacles: Optional[List[Tuple[float, float, float]]] = None,
    ) -> Optional[np.ndarray]:
        return replan_astar(
            current_pose,
            path,
            obstacle,
            self.static_free_grid,
            self.x_min,
            self.y_min,
            self.grid_res,
            all_obstacles=all_obstacles,
            drivable_fn=self.is_drivable,
        )

    def compute_curvature_speed_limit(
        self,
        alpha: float,
        lookahead_dist: float,
        a_lat_max: Optional[float] = None,
        v_nominal: float = 1.39,
    ) -> float:
        """Рассчитать предельную скорость по боковому ускорению в дуге."""
        limit_a = self.a_lat_max if a_lat_max is None else a_lat_max
        return compute_curvature_speed_limit(
            alpha, lookahead_dist, a_lat_max=limit_a, v_nominal=v_nominal
        )

    def pure_pursuit(
        self, pose: Tuple[float, float, float], path: np.ndarray, v_max: float = 1.39
    ) -> Tuple[float, float, Tuple[float, float], float, float]:
        v, w, target_pt, curr_s, rem_dist = compute_pure_pursuit_cmd(
            pose, path, last_s=self.last_s, v_max=v_max, a_lat_max=self.a_lat_max
        )
        self.last_s = curr_s
        return v, w, target_pt, curr_s, rem_dist

    def stanley(
        self,
        pose: Tuple[float, float, float],
        path: np.ndarray,
        v_max: float = 1.39,
        k_e: float = 1.5,
        k_soft: float = 0.5,
    ) -> Tuple[float, float, Tuple[float, float], float, float]:
        v, w, target_pt, curr_s, rem_dist = compute_stanley_cmd(
            pose, path, last_s=self.last_s, v_max=v_max, k_e=k_e, k_soft=k_soft, a_lat_max=self.a_lat_max
        )
        self.last_s = curr_s
        return v, w, target_pt, curr_s, rem_dist

    def step(
        self,
        pose: Tuple[float, float, float],
        mission: Optional[Dict[str, Any]] = None,
        obstacles: Optional[Any] = None,
        current_time: float = 0.0,
    ) -> Dict[str, Any]:
        """Вычислить команду навигации для текущего такта симуляции."""
        x, y, th = pose

        if mission is not None:
            self.update_mission(mission, pose)

        if len(self.active_path) < 2:
            return {
                "v": 0.0,
                "w": 0.0,
                "status": "arrived" if self.arrived else "waiting",
                "note": self.note,
                "arrived": self.arrived,
                "hold_count": self.hold_count,
            }

        goal_pt = self.active_path[-1]
        dist_to_goal = math.hypot(x - goal_pt[0], y - goal_pt[1])

        if dist_to_goal < 0.10:
            self.arrived = True
            self.hold_count += 1
            w_align = 0.0
            if mission is not None and "goal" in mission:
                goal_th = float(mission["goal"][2])
                dth = wrap_angle(goal_th - th)
                if abs(dth) > 0.05:
                    w_align = float(np.clip(1.5 * dth, -0.5, 0.5))

            return {
                "v": 0.0,
                "w": w_align,
                "status": "arrived",
                "note": self.note,
                "arrived": True,
                "hold_count": self.hold_count,
            }

        curr_progress = get_path_progress(self.active_path, x, y, self.last_s)

        t0 = self.t_start if self.t_start is not None else current_time
        self.time_left = None if self.deadline_s is None else self.deadline_s - (current_time - t0)
        self.final_approach = bool(
            self.time_left is not None and self.time_left < 8.0 and dist_to_goal < 2.0
        )

        parsed_obstacles = parse_obstacles(obstacles)
        obs_ahead = self.check_obstacles_in_tube(self.active_path, parsed_obstacles, curr_progress)

        if obs_ahead is not None and self.final_approach:
            if self._line_free((x, y), (float(goal_pt[0]), float(goal_pt[1])), parsed_obstacles):
                obs_ahead = None

        if obs_ahead is not None:
            shifted = self.apply_lateral_offset(
                self.active_path, obs_ahead, curr_progress, all_obstacles=parsed_obstacles
            )
            if shifted is not None:
                self.active_path = shifted
                self.note = "offset dy=%.1f" % self.last_offset_dy
                self.last_s = get_path_progress(self.active_path, x, y, 0.0)
            else:
                can_replan = (current_time - self.last_replan_t) >= self.replan_interval
                if can_replan:
                    self.last_replan_t = float(current_time)
                    replanned = self.replan_astar(
                        pose, self.active_path, obs_ahead, all_obstacles=parsed_obstacles
                    )
                    if replanned is not None:
                        self.active_path = replanned
                        self.note = "replan"
                        self.last_s = 0.0
                    else:
                        self.note = "stop_object"
                        return {
                            "v": 0.0,
                            "w": 0.0,
                            "status": "waiting",
                            "note": "stop_object",
                            "arrived": False,
                            "hold_count": 0,
                        }
                elif self.note == "replan":
                    pass
                else:
                    self.note = "stop_object"
                    return {
                        "v": 0.0,
                        "w": 0.0,
                        "status": "waiting",
                        "note": "stop_object",
                        "arrived": False,
                        "hold_count": 0,
                    }
        else:
            self.note = None

        v_zone_limit = self.check_speed_zones(x, y, th)
        v, w, target_pt, _, rem_dist = self.pure_pursuit(pose, self.active_path, v_max=v_zone_limit)

        return {
            "v": v,
            "w": w,
            "status": "moving",
            "note": self.note,
            "arrived": False,
            "hold_count": 0,
            "target_point": target_pt,
            "remaining_dist": rem_dist,
        }


# Псевдоним Planner для полной совместимости
Planner = RouteFollower
