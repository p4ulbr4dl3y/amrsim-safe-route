"""Route planning and tracking module for Autonomous Mobile Robot (AMR).

Conforms strictly to plan/04-marshrut-i-missii.md, plan/01-schet-i-ploshchadka.md,
and plan/05-sborka-i-priemka.md.
Pure pursuit tracking, speed zone management, lateral offset avoidance,
and grid A* fallback.
Isolation: only standard math, typing, and numpy are used.
"""
import math
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

try:
    from .geom import box_segs, inside_polygon, wrap_angle
except ImportError:
    from geom import box_segs, inside_polygon, wrap_angle


class _PriorityQueue:
    """Min-priority queue using pure-Python binary min-heap."""

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


class RouteFollower:
    """AMR Pure Pursuit route follower and local path planner.

    Features:
    - Pure pursuit with 1.5m lookahead.
    - Dock target snap within 1.5m, docking speed 0.15 m/s.
    - In-place rotation for |alpha| > 0.8 rad (v = 0, |w| <= 0.8 rad/s).
    - Turning speed limit for |alpha| > 0.35 rad (v <= 0.5 m/s).
    - Deceleration braking profile: v <= sqrt(2 * 0.4 * remaining_dist) + 0.03.
    - Speed zone limits (checking current, +3.0m ahead, -1.5m behind) capped at v_zone - 0.05.
    - FB_HAZ forbidden zone strictly excluded from drivable area.
    - Automatic generation of initial leg to 'from' point if distance > 1.5m.
    - Lateral shift avoidance (0.2m steps, gap > 1.1m, margin >= 0.2m to drivable boundary),
      shifted towards the roomy side of the aisle first (plan/04:36-39).
    - Grid A* fallback (0.5m grid, free cells keep a 0.2m boundary margin,
      forbidden zones cut out) re-joining the reference on clear line of sight.
    - A* replan throttled to once per 2 s; safe stop otherwise.
    - Deadline-aware final approach (< 8 s left, < 2 m to goal, clear corridor).
    - note strings: 'offset dy=<m>', 'replan', 'stop_object'.
    - Safe stop (v = 0, status waiting, note=stop_object) if corridor blocked.
    """

    def __init__(self, map_dict: Optional[Dict[str, Any]] = None,
                 config: Optional[Dict[str, Any]] = None) -> None:
        self.map_dict = map_dict or {}
        self.config = config or {}

        # Drivable and forbidden geometry
        self.drivable_polys: List[np.ndarray] = []
        self.forbidden_polys: List[np.ndarray] = []
        self.speed_zones: List[Dict[str, Any]] = []
        self.points: Dict[str, Dict[str, Any]] = {}
        self.building_segs: np.ndarray = np.empty((0, 4), dtype=float)

        self._parse_map(self.map_dict)

        # 2D Grid settings for A*
        self.grid_res = 0.5
        # Plan/04:40: a free cell must stay at least 0.2 m away from the
        # drivable boundary, so the margin is baked into the static grid.
        self.grid_margin = 0.2
        self._init_grid()

        # Mission and path tracking state
        self.current_mission_id: Optional[str] = None
        self.reference_path: np.ndarray = np.empty((0, 2), dtype=float)
        self.active_path: np.ndarray = np.empty((0, 2), dtype=float)
        self.progress_s: float = 0.0
        self.last_s: float = 0.0
        self.arrived: bool = False
        self.hold_count: int = 0
        self.status: str = "waiting"
        self.note: Optional[str] = None

        # Replan throttling
        self.last_replan_t: float = -10.0
        self.replan_interval: float = 2.0  # seconds

        # Deadline / final-approach state (plan/04:51-57)
        self.t_start: Optional[float] = None
        self.deadline_s: Optional[float] = None
        self.time_left: Optional[float] = None
        self.final_approach: bool = False
        self.last_offset_dy: float = 0.0

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
                    self.speed_zones.append({
                        "id": z_id,
                        "v_max": float(z["v_max"]),
                        "polygon": np.asarray(z["polygon"], dtype=float),
                    })
        if "points" in m:
            self.points = m["points"]
        if "buildings" in m:
            self.building_segs = box_segs(m["buildings"])

    def _init_grid(self) -> None:
        if self.drivable_polys:
            all_pts = np.vstack(self.drivable_polys)
            self.x_min = float(all_pts[:, 0].min()) - 3.0
            self.y_min = float(all_pts[:, 1].min()) - 3.0
            self.x_max = float(all_pts[:, 0].max()) + 3.0
            self.y_max = float(all_pts[:, 1].max()) + 3.0
        else:
            self.x_min, self.y_min, self.x_max, self.y_max = 0.0, 0.0, 250.0, 200.0

        self.nx = int(math.ceil((self.x_max - self.x_min) / self.grid_res)) + 1
        self.ny = int(math.ceil((self.y_max - self.y_min) / self.grid_res)) + 1

        xs = self.x_min + np.arange(self.nx) * self.grid_res
        ys = self.y_min + np.arange(self.ny) * self.grid_res
        gx, gy = np.meshgrid(xs, ys)
        pts = np.column_stack([gx.ravel(), gy.ravel()])

        in_d = np.zeros(len(pts), dtype=bool)
        for poly in self.drivable_polys:
            in_d |= inside_polygon(pts, poly)

        in_f = np.zeros(len(pts), dtype=bool)
        for poly in self.forbidden_polys:
            in_f |= inside_polygon(pts, poly)

        free_mask = in_d & (~in_f)

        # Plan/04:40: free cell = inside a drivable aisle with a 0.2 m margin
        # to its boundary, outside forbidden zones and outside map walls.
        # Only the cheap in_d candidates are re-checked with the margin.
        margin = float(getattr(self, "grid_margin", 0.2))
        if margin > 0.0:
            cand = np.flatnonzero(free_mask)
            if cand.size:
                ok = np.asarray(self.is_drivable(pts[cand], margin=margin), dtype=bool)
                free_mask[cand[~ok]] = False

        self.static_free_grid = free_mask.reshape((self.ny, self.nx))

    def is_drivable(self, x: Union[float, np.ndarray],
                    y: Union[float, np.ndarray] = None,
                    margin: float = 0.2) -> Union[bool, np.ndarray]:
        """Check if 2D coordinates are inside drivable polygon, outside FB_HAZ,
        and at least `margin` meters away from drivable boundaries."""
        if y is None:
            pts = np.atleast_2d(np.asarray(x, dtype=float))
            is_single = (np.ndim(x) == 1)
        else:
            is_single = (np.ndim(x) == 0 and np.ndim(y) == 0)
            px = np.atleast_1d(np.asarray(x, dtype=float))
            py = np.atleast_1d(np.asarray(y, dtype=float))
            pts = np.column_stack([px, py])

        def _check(p: np.ndarray) -> np.ndarray:
            in_d = np.zeros(len(p), dtype=bool)
            for poly in self.drivable_polys:
                in_d |= inside_polygon(p, poly)
            in_f = np.zeros(len(p), dtype=bool)
            for poly in self.forbidden_polys:
                in_f |= inside_polygon(p, poly)
            return in_d & (~in_f)

        valid = _check(pts)
        if margin > 0.0:
            diag = margin * 0.70710678
            offsets = [
                (margin, 0.0), (-margin, 0.0), (0.0, margin), (0.0, -margin),
                (diag, diag), (-diag, diag), (diag, -diag), (-diag, -diag)
            ]
            for dx, dy in offsets:
                valid &= _check(pts + np.array([dx, dy]))

        return bool(valid[0]) if is_single else valid

    def check_speed_zones(self, x: float, y: float, th: float) -> float:
        """Inspect current point, +3.0m ahead and -1.5m behind.

        Caps speed at v_zone - 0.05.
        Returns maximum permissible speed (m/s), default 1.39 m/s.
        """
        c, s = math.cos(th), math.sin(th)
        test_pts = np.array([
            [x, y],
            [x + 3.0 * c, y + 3.0 * s],
            [x - 1.5 * c, y - 1.5 * s],
        ])

        speed_cap = 1.39
        for zone in self.speed_zones:
            poly = zone["polygon"]
            if np.any(inside_polygon(test_pts, poly)):
                z_limit = float(zone["v_max"]) - 0.05
                if z_limit < speed_cap:
                    speed_cap = z_limit
        return speed_cap

    def get_point_xy(self, pt_ident: Any,
                     fallback: Optional[Union[List[float], np.ndarray]] = None) -> Tuple[float, float]:
        """Resolve a dock / waypoint identifier to (x, y) coordinates."""
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

    def update_mission(self, mission: Dict[str, Any],
                       pose: Tuple[float, float, float]) -> None:
        """Handle mission updates and generate initial approach leg if needed."""
        m_id = mission.get("id")
        if m_id == self.current_mission_id and len(self.active_path) > 0:
            return

        self.current_mission_id = m_id
        ref_path = np.asarray(mission["reference_path"], dtype=float)
        self.reference_path = ref_path
        self.active_path = ref_path.copy()
        self.arrived = False
        self.hold_count = 0
        self.progress_s = 0.0
        self.last_s = 0.0
        self.last_s = 0.0
        self.note = None
        self.last_replan_t = -10.0
        self.last_offset_dy = 0.0

        # Deadline bookkeeping (plan/04:51-57)
        t_start = mission.get("t_start")
        self.t_start = float(t_start) if t_start is not None else None
        deadline = mission.get("deadline_s")
        self.deadline_s = float(deadline) if deadline is not None else None
        self.time_left = None
        self.final_approach = False

        # Check pickup point distance
        from_xy = self.get_point_xy(mission.get("from"), fallback=ref_path[0])
        dist_to_from = math.hypot(pose[0] - from_xy[0], pose[1] - from_xy[1])

        if dist_to_from > 1.5:
            # Generate initial leg from current pose to from_xy
            init_leg = self.plan_path((pose[0], pose[1]), from_xy)
            if init_leg is not None and len(init_leg) > 0:
                init_arr = np.asarray(init_leg, dtype=float)
                # Concatenate with reference path (skipping first point if coincident)
                if np.hypot(init_arr[-1, 0] - ref_path[0, 0], init_arr[-1, 1] - ref_path[0, 1]) < 0.2:
                    self.active_path = np.vstack([init_arr[:-1], ref_path])
                else:
                    self.active_path = np.vstack([init_arr, ref_path])
            else:
                self.active_path = ref_path.copy()
        else:
            self.active_path = ref_path.copy()

    def plan_path(self, start: Tuple[float, float], goal: Tuple[float, float],
                  obstacles: Optional[List[Tuple[float, float, float]]] = None) -> Optional[List[Tuple[float, float]]]:
        """Compute path between start and goal avoiding obstacles and FB_HAZ."""
        return self._astar_search(start, goal, obstacles=obstacles)

    def _coord_to_cell(self, x: float, y: float) -> Tuple[int, int]:
        ci = int(round((y - self.y_min) / self.grid_res))
        cj = int(round((x - self.x_min) / self.grid_res))
        return ci, cj

    def _cell_to_coord(self, ci: int, cj: int) -> Tuple[float, float]:
        x = self.x_min + cj * self.grid_res
        y = self.y_min + ci * self.grid_res
        return x, y

    def _find_nearest_free_cell(self, ci: int, cj: int,
                                obs_circles: List[Tuple[float, float, float]],
                                max_dist_m: float = 3.0) -> Optional[Tuple[int, int]]:
        k = int(math.ceil(max_dist_m / self.grid_res))
        best_cell = None
        best_d2 = math.inf
        for di in range(-k, k + 1):
            for dj in range(-k, k + 1):
                ni, nj = ci + di, cj + dj
                if 0 <= ni < self.ny and 0 <= nj < self.nx and self.static_free_grid[ni, nj]:
                    cx, cy = self._cell_to_coord(ni, nj)
                    if self._is_clear_of_obstacles(cx, cy, obs_circles):
                        d2 = di * di + dj * dj
                        if d2 < best_d2:
                            best_d2 = d2
                            best_cell = (ni, nj)
        return best_cell

    def _is_clear_of_obstacles(self, x: float, y: float,
                               obs_circles: List[Tuple[float, float, float]]) -> bool:
        for ox, oy, r in obs_circles:
            # Safety inflation: 0.9 + 0.35 + obstacle radius r
            req_dist = 0.9 + 0.35 + r
            if math.hypot(x - ox, y - oy) < req_dist:
                return False
        return True

    def _lateral_clearance(self, point: Tuple[float, float],
                           normal: np.ndarray, max_dist: float = 3.0) -> float:
        """Largest shift along `normal` that keeps a 0.2 m drivable margin.

        Used to pick the roomy side of an aisle (plan/04:36-39): the northern
        aisle has 2.6 m to the south and only 0.6 m to the north, the western
        exit has 0.6 m to the east, the southern aisle is symmetric.
        """
        step = 0.2
        travelled = 0.0
        while travelled + step <= max_dist + 1e-9:
            dist = travelled + step
            if not self.is_drivable(point[0] + dist * normal[0],
                                    point[1] + dist * normal[1], margin=0.2):
                break
            travelled = dist
        return travelled

    def _line_free(self, p1: Tuple[float, float], p2: Tuple[float, float],
                   obs_circles: List[Tuple[float, float, float]],
                   margin: float = 0.2) -> bool:
        """Check if straight segment between p1 and p2 is clear (vectorised)."""
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        steps = max(2, int(math.ceil(dist / 0.25)))
        ts = np.linspace(0.0, 1.0, steps)
        pts = np.column_stack([p1[0] + ts * (p2[0] - p1[0]),
                               p1[1] + ts * (p2[1] - p1[1])])

        if not bool(np.all(self.is_drivable(pts, margin=margin))):
            return False

        for ox, oy, r in obs_circles:
            # Same 0.9 + 0.35 inflation used by the grid search.
            req_dist = 0.9 + 0.35 + r
            if bool(np.any(np.hypot(pts[:, 0] - ox, pts[:, 1] - oy) < req_dist)):
                return False
        return True

    def _astar_search(self, start: Tuple[float, float], goal: Tuple[float, float],
                      obstacles: Optional[List[Tuple[float, float, float]]] = None) -> Optional[List[Tuple[float, float]]]:
        obs_circles = obstacles or []

        ci_s, cj_s = self._coord_to_cell(start[0], start[1])
        ci_g, cj_g = self._coord_to_cell(goal[0], goal[1])

        start_cell = self._find_nearest_free_cell(ci_s, cj_s, obs_circles, max_dist_m=3.0)
        goal_cell = self._find_nearest_free_cell(ci_g, cj_g, obs_circles, max_dist_m=3.0)

        if start_cell is None or goal_cell is None:
            return None

        nbr_offsets = [
            (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
            (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)
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
                if not (0 <= ni < self.ny and 0 <= nj < self.nx):
                    continue
                if not self.static_free_grid[ni, nj]:
                    continue

                cx, cy = self._cell_to_coord(ni, nj)
                if not self._is_clear_of_obstacles(cx, cy, obs_circles):
                    continue

                tentative_g = cur_g + cost * self.grid_res
                next_cell = (ni, nj)
                if tentative_g < g_score.get(next_cell, math.inf):
                    g_score[next_cell] = tentative_g
                    came_from[next_cell] = curr
                    h = math.hypot(ni - gi, nj - gj) * self.grid_res
                    pq.put(tentative_g + h, next_cell)

        if goal_cell not in came_from and start_cell != goal_cell:
            return None

        # Reconstruct path
        path_cells = [goal_cell]
        while path_cells[-1] != start_cell:
            path_cells.append(came_from[path_cells[-1]])
        path_cells.reverse()

        coords = [start] + [self._cell_to_coord(ci, cj) for ci, cj in path_cells] + [goal]

        # Line-of-sight shortcutting
        shortcutted = [coords[0]]
        i = 0
        n_pts = len(coords)
        while i < n_pts - 1:
            furthest = i + 1
            for j in range(n_pts - 1, i + 1, -1):
                if self._line_free(coords[i], coords[j], obs_circles):
                    furthest = j
                    break
            shortcutted.append(coords[furthest])
            i = furthest

        return [[round(x, 2), round(y, 2)] for x, y in shortcutted]

    def _parse_obstacles(self, obstacles: Any) -> List[Tuple[float, float, float]]:
        """Extract [(x, y, radius)] list from various obstacle representations."""
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

    def _get_path_progress(self, path: np.ndarray, x: float, y: float,
                           last_s: float = 0.0) -> float:
        """Find progress distance s along polyline corresponding to point (x, y)."""
        if len(path) < 2:
            return 0.0
        diffs = path[1:] - path[:-1]
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])

        best_s = last_s
        best_dist = math.inf
        for i in range(len(seg_lens)):
            p1 = path[i]
            p2 = path[i + 1]
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

    def check_obstacles_in_tube(self, path: np.ndarray,
                                obstacles: Any,
                                current_s: float,
                                tube_radius: float = 1.25) -> Optional[Tuple[float, float, float, float]]:
        """Detect if an obstacle penetrates the reference tube or requires lateral avoidance.

        Trigger condition:
        - Penetration within reference tube: dist_center - r < tube_radius (1.25m)
        - OR insufficient clearance: gap = dist_center - 0.9 - r < 1.1m
        Returns (ox, oy, r, s_obs) for the earliest obstacle ahead of current progress.
        """
        parsed = self._parse_obstacles(obstacles)
        if not parsed or len(path) < 2:
            return None

        diffs = path[1:] - path[:-1]
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])

        best_obs = None
        min_s = math.inf

        for ox, oy, r in parsed:
            # Find projection onto path
            for i in range(len(seg_lens)):
                p1 = path[i]
                p2 = path[i + 1]
                v = diffs[i]
                L = seg_lens[i]
                if L < 1e-6:
                    continue
                u = np.clip(((ox - p1[0]) * v[0] + (oy - p1[1]) * v[1]) / (L * L), 0.0, 1.0)
                proj = p1 + u * v
                s_obs = cum_lens[i] + u * L

                # Only evaluate obstacles ahead of robot, but not beyond end of path
                if s_obs < current_s - 0.5 or s_obs > current_s + 35.0:
                    continue
                # Do not trigger tube avoidance near terminal dock point (last 3.0m)
                if s_obs > cum_lens[-1] - 3.0:
                    continue

                dist_center = math.hypot(ox - proj[0], oy - proj[1])
                dist_edge = dist_center - r

                # Tube check: obstacle edge enters reference tube or violates 1.1m clearance gap
                if dist_edge < max(tube_radius, 2.0):
                    if s_obs < min_s:
                        min_s = s_obs
                        best_obs = (ox, oy, r, s_obs)

        return best_obs

    def apply_lateral_offset(self, path: np.ndarray,
                             obstacle: Tuple[float, float, float, float],
                             current_s: float,
                             all_obstacles: Optional[List[Tuple[float, float, float]]] = None) -> Optional[np.ndarray]:
        """Apply lateral shift to polyline in 0.2m increments until clearance > 1.1m

        and boundary margin >= 0.2m is satisfied for all scene obstacles.
        """
        ox, oy, r, s_obs = obstacle
        if len(path) < 2:
            return None

        obs_list = all_obstacles or [(ox, oy, r)]

        diffs = path[1:] - path[:-1]
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])
        total_len = cum_lens[-1]

        # Find segment at s_obs
        idx = np.searchsorted(cum_lens, s_obs) - 1
        idx = max(0, min(len(seg_lens) - 1, idx))
        v = diffs[idx]
        L = max(seg_lens[idx], 1e-6)
        u_dir = v / L
        normal = np.array([-u_dir[1], u_dir[0]])  # Left normal

        # Signed lateral offset of primary obstacle from path
        p1 = path[idx]
        d_lat_obs = (ox - p1[0]) * normal[0] + (oy - p1[1]) * normal[1]

        # Plan/04:36-39: shift towards the roomy side of the aisle first
        # (northern aisle -> south, western exit -> west, southern aisle ->
        # either side); only a symmetric aisle falls back to moving away from
        # the obstacle.
        t_obs = (s_obs - cum_lens[idx]) / max(1e-6, L)
        p_obs = p1 + t_obs * diffs[idx]
        c_plus = self._lateral_clearance((float(p_obs[0]), float(p_obs[1])), normal)
        c_minus = self._lateral_clearance((float(p_obs[0]), float(p_obs[1])), -normal)
        if abs(c_plus - c_minus) < 0.05:
            prefer = -1.0 if d_lat_obs >= 0.0 else 1.0
        else:
            prefer = 1.0 if c_plus > c_minus else -1.0

        # Candidate lateral shifts in 0.2m increments
        base_shifts = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
        candidates = [prefer * s for s in base_shifts] + [-prefer * s for s in base_shifts]

        s_ramp_in = max(current_s, s_obs - 4.5)
        s_plat_in = s_obs - 2.0
        s_plat_out = s_obs + 2.0
        s_ramp_out = min(total_len, s_obs + 4.5)

        for delta in candidates:
            # Sample the shifted section
            s_samples = np.arange(s_ramp_in, s_ramp_out + 0.2, 0.25)
            pts_shifted = []
            feasible = True

            for s_val in s_samples:
                # Ramp weighting
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

                # Interpolate unshifted point on path
                s_idx = np.searchsorted(cum_lens, s_val) - 1
                s_idx = max(0, min(len(seg_lens) - 1, s_idx))
                tau = (s_val - cum_lens[s_idx]) / max(1e-6, seg_lens[s_idx])
                p_orig = path[s_idx] + tau * diffs[s_idx]

                p_shift = p_orig + w * delta * normal
                pts_shifted.append(p_shift)

                # Check gap > 1.1m at plateau to all nearby obstacles
                if s_plat_in <= s_val <= s_plat_out:
                    for o_x, o_y, o_r in obs_list:
                        # Required center distance: platform (0.9) + obstacle (o_r) + gap (1.1m)
                        if math.hypot(p_shift[0] - o_x, p_shift[1] - o_y) < 0.9 + o_r + 1.1001:
                            feasible = False
                            break
                    if not feasible:
                        break

                # Check drivable boundary clearance >= 0.2m
                if not self.is_drivable(p_shift[0], p_shift[1], margin=0.2):
                    feasible = False
                    break

            if feasible and len(pts_shifted) > 0:
                # Splice shifted waypoints into path
                prefix = [path[j] for j in range(len(path)) if cum_lens[j] < s_ramp_in - 0.1]
                suffix = [path[j] for j in range(len(path)) if cum_lens[j] > s_ramp_out + 0.1]
                new_path = prefix + pts_shifted + suffix
                self.last_offset_dy = float(delta)
                return np.asarray(new_path, dtype=float)

        return None

    def replan_astar(self, current_pose: Tuple[float, float, float],
                     path: np.ndarray,
                     obstacle: Tuple[float, float, float, float],
                     all_obstacles: Optional[List[Tuple[float, float, float]]] = None) -> Optional[np.ndarray]:
        """Local A* replan on 0.5m grid avoiding all scene obstacles."""
        ox, oy, r, s_obs = obstacle
        if len(path) < 2:
            return None

        obs_list = all_obstacles or [(ox, oy, r)]

        diffs = path[1:] - path[:-1]
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])
        total_len = cum_lens[-1]

        start_pt = (current_pose[0], current_pose[1])

        # Plan/04:40: re-join the remaining reference as soon as the straight
        # line from the current pose to it is clear, instead of a fixed 5 m.
        s_goal = min(total_len, s_obs + 5.0)
        s_cap = min(total_len, s_obs + 40.0)
        s_try = s_obs
        while s_try <= s_cap + 1e-9:
            idx_t = int(np.searchsorted(cum_lens, s_try) - 1)
            idx_t = max(0, min(len(seg_lens) - 1, idx_t))
            tau_t = (s_try - cum_lens[idx_t]) / max(1e-6, seg_lens[idx_t])
            cand_pt = path[idx_t] + tau_t * diffs[idx_t]
            if self._line_free(start_pt, (float(cand_pt[0]), float(cand_pt[1])), obs_list):
                s_goal = float(s_try)
                break
            s_try += 0.5

        g_idx = np.searchsorted(cum_lens, s_goal) - 1
        g_idx = max(0, min(len(seg_lens) - 1, g_idx))
        tau = (s_goal - cum_lens[g_idx]) / max(1e-6, seg_lens[g_idx])
        p_goal = tuple(path[g_idx] + tau * diffs[g_idx])

        bypass = self._astar_search(start_pt, p_goal, obstacles=obs_list)
        if bypass is None:
            return None

        # Splice bypass into downstream reference path
        suffix = [path[j] for j in range(len(path)) if cum_lens[j] > s_goal]
        new_path = bypass + suffix
        return np.asarray(new_path, dtype=float)

    def pure_pursuit(self, pose: Tuple[float, float, float],
                     path: np.ndarray,
                     v_max: float = 1.39) -> Tuple[float, float, Tuple[float, float], float, float]:
        """Pure pursuit tracking along polyline.

        Returns (v, w, target_point, current_s, remaining_dist).
        """
        x, y, th = pose
        if len(path) < 2:
            return 0.0, 0.0, (x, y), 0.0, 0.0

        diffs = path[1:] - path[:-1]
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_lens = np.concatenate([[0.0], np.cumsum(seg_lens)])
        total_len = cum_lens[-1]

        # Find closest point on path ahead of last_s
        best_s = self.last_s
        best_dist = math.inf

        for i in range(len(seg_lens)):
            p1 = path[i]
            p2 = path[i + 1]
            v = diffs[i]
            L = seg_lens[i]
            if L < 1e-6:
                continue
            u = np.clip(((x - p1[0]) * v[0] + (y - p1[1]) * v[1]) / (L * L), 0.0, 1.0)
            proj = p1 + u * v
            s_cand = cum_lens[i] + u * L

            if s_cand >= self.last_s - 1.5:
                d = math.hypot(x - proj[0], y - proj[1])
                if d < best_dist:
                    best_dist = d
                    best_s = s_cand

        curr_s = max(self.last_s, best_s)
        self.last_s = curr_s
        rem_dist = max(0.0, total_len - curr_s)

        # Distance to terminal dock goal
        goal_pt = path[-1]
        dist_to_goal = math.hypot(x - goal_pt[0], y - goal_pt[1])

        # Dock lookahead rule: within 1.5m, target strictly dock goal
        is_dock_zone = (dist_to_goal <= 1.5 or rem_dist <= 1.5)
        if is_dock_zone:
            target_pt = (float(goal_pt[0]), float(goal_pt[1]))
        else:
            target_s = min(total_len, curr_s + 1.5)
            idx = np.searchsorted(cum_lens, target_s) - 1
            idx = max(0, min(len(seg_lens) - 1, idx))
            tau = (target_s - cum_lens[idx]) / max(1e-6, seg_lens[idx])
            t_coord = path[idx] + tau * diffs[idx]
            target_pt = (float(t_coord[0]), float(t_coord[1]))

        # Target heading and alpha error
        dx = target_pt[0] - x
        dy = target_pt[1] - y
        ld = math.hypot(dx, dy)
        target_hd = math.atan2(dy, dx)
        alpha = wrap_angle(target_hd - th)

        # In-place rotation if |alpha| > 0.8
        if abs(alpha) > 0.8:
            v = 0.0
            w = float(np.clip(2.0 * alpha, -0.8, 0.8))
            return v, w, target_pt, curr_s, rem_dist

        # Speed limits:
        # 1. Dock speed 0.15 m/s within 1.5m
        v_dock = 0.15 if is_dock_zone else 1.39
        # 2. Turning speed limit: |alpha| > 0.35 -> v <= 0.5
        v_turn = 0.5 if abs(alpha) > 0.35 else 1.39
        # 3. Deceleration braking profile
        effective_rem = max(0.0, min(rem_dist, dist_to_goal + 0.05) - 0.02)
        v_brake = math.sqrt(2.0 * 0.4 * effective_rem) + 0.03

        if dist_to_goal < 0.03 or effective_rem < 0.03:
            return 0.0, 0.0, target_pt, curr_s, 0.0

        v = min(v_max, v_dock, v_turn, v_brake)
        v = max(0.0, v)

        # Pure pursuit curvature steering with fallback to alpha when v is small
        lx = max(0.5, ld)
        w = 2.0 * v * math.sin(alpha) / lx if v > 0.05 else float(np.clip(1.5 * alpha, -1.0, 1.0))
        w = float(np.clip(w, -1.0, 1.0))

        return v, w, target_pt, curr_s, rem_dist

    def step(self, pose: Tuple[float, float, float],
             mission: Optional[Dict[str, Any]] = None,
             obstacles: Optional[Any] = None,
             current_time: float = 0.0) -> Dict[str, Any]:
        """Compute navigation command for the current simulation tick.

        Returns dict containing:
          'v': linear velocity (m/s)
          'w': angular velocity (rad/s)
          'status': 'moving', 'arrived', 'waiting', or 'estop'
          'note': 'offset', 'replan', 'stop_object', or None
          'arrived': bool flag
        """
        x, y, th = pose

        # Update mission tracking if mission provided
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

        # Check terminal arrival condition
        goal_pt = self.active_path[-1]
        dist_to_goal = math.hypot(x - goal_pt[0], y - goal_pt[1])

        if dist_to_goal < 0.10:
            self.arrived = True
            self.hold_count += 1
            # Optional dock alignment
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

        # Current progress along active path
        curr_progress = self._get_path_progress(self.active_path, x, y, self.last_s)

        # Deadline / final approach (plan/04:55): with less than 8 s left, less
        # than 2 m to the goal and an empty corridor, dock at the allowed speed
        # without adding extra stops.
        t0 = self.t_start if self.t_start is not None else current_time
        self.time_left = None if self.deadline_s is None else self.deadline_s - (current_time - t0)
        self.final_approach = bool(
            self.time_left is not None and self.time_left < 8.0 and dist_to_goal < 2.0
        )

        # Obstacle avoidance in reference tube (0.9 + 0.35m) or clearance gap < 1.1m
        parsed_obstacles = self._parse_obstacles(obstacles)
        obs_ahead = self.check_obstacles_in_tube(self.active_path, parsed_obstacles, curr_progress)

        if obs_ahead is not None and self.final_approach:
            # Straight to the dock on the allowed speed, no avoidance stop.
            if self._line_free((x, y), (float(goal_pt[0]), float(goal_pt[1])),
                               parsed_obstacles):
                obs_ahead = None

        if obs_ahead is not None:
            # 1. Try lateral offset
            shifted = self.apply_lateral_offset(self.active_path, obs_ahead, curr_progress,
                                                all_obstacles=parsed_obstacles)
            if shifted is not None:
                self.active_path = shifted
                self.note = "offset dy=%.1f" % self.last_offset_dy
                self.last_s = self._get_path_progress(self.active_path, x, y, 0.0)
            else:
                # 2. Try local A*, throttled to once per 2 s (plan/04:41)
                can_replan = (current_time - self.last_replan_t) >= self.replan_interval
                if can_replan:
                    self.last_replan_t = float(current_time)
                    replanned = self.replan_astar(pose, self.active_path, obs_ahead,
                                                  all_obstacles=parsed_obstacles)
                    if replanned is not None:
                        self.active_path = replanned
                        self.note = "replan"
                        self.last_s = 0.0
                    else:
                        # 3. No path found -> safe stop, retry after 2 s
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
                    # Keep following the existing bypass until the next window.
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

        # Evaluate speed limit zones
        v_zone_limit = self.check_speed_zones(x, y, th)

        # Pure pursuit command
        v, w, target_pt, curr_s, rem_dist = self.pure_pursuit(pose, self.active_path, v_max=v_zone_limit)

        self.status = "moving"
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

    def compute_command(self, pose: Tuple[float, float, float],
                        mission: Optional[Dict[str, Any]] = None,
                        obstacles: Optional[Any] = None,
                        current_time: float = 0.0) -> Dict[str, Any]:
        """Alias for step() for flexible controller integration."""
        return self.step(pose, mission=mission, obstacles=obstacles, current_time=current_time)


# Export Planner as alias of RouteFollower
Planner = RouteFollower
