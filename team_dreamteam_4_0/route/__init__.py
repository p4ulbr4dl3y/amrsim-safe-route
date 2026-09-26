"""Пакет планирования и следования по маршруту для AMR.

Строго соответствует требованиям изоляции и навигации (только math, typing и numpy).
"""

from .astar import _PriorityQueue, astar_search, replan_astar
from .follower import (
    Planner,
    RouteFollower,
    apply_lateral_offset,
    check_obstacles_in_tube,
)
from .grid import (
    build_static_free_grid,
    cell_to_coord,
    coord_to_cell,
    find_nearest_free_cell,
    inflate_obstacles,
    is_clear_of_obstacles,
    is_drivable,
    is_line_free,
    lateral_clearance,
    parse_obstacles,
)
from .pure_pursuit import (
    check_speed_zones,
    compute_cross_track_error,
    compute_curvature_speed_limit,
    compute_pure_pursuit_cmd,
    compute_stanley_cmd,
    find_lookahead_point,
    get_path_progress,
)
from .spline import (
    QuinticSpline1D,
    smooth_yaw_rate_quintic,
)

__all__ = [
    "Planner",
    "RouteFollower",
    "_PriorityQueue",
    "is_drivable",
    "build_static_free_grid",
    "coord_to_cell",
    "cell_to_coord",
    "parse_obstacles",
    "inflate_obstacles",
    "is_clear_of_obstacles",
    "find_nearest_free_cell",
    "is_line_free",
    "lateral_clearance",
    "astar_search",
    "replan_astar",
    "get_path_progress",
    "check_speed_zones",
    "compute_curvature_speed_limit",
    "find_lookahead_point",
    "compute_pure_pursuit_cmd",
    "compute_stanley_cmd",
    "compute_cross_track_error",
    "check_obstacles_in_tube",
    "apply_lateral_offset",
    "QuinticSpline1D",
    "smooth_yaw_rate_quintic",
]
