"""Unit tests for team.route module (RouteFollower and Planner).

Verifies Pure Pursuit tracking, speed zones, FB_HAZ forbidden zone exclusion,
mission 'from' distance leg generation, lateral offset, A* replan, and obstacle stop.
Conforms strictly to plan/04-marshrut-i-missii.md and isolation requirements.
"""

import json
import math
import os
import unittest
from typing import Tuple

import numpy as np

from team_dreamteam_4_0.geom import inside_polygon, wrap_angle
from team_dreamteam_4_0.route import (
    Planner,
    RouteFollower,
    build_static_free_grid,
    check_speed_zones,
    compute_cross_track_error,
    compute_curvature_speed_limit,
    compute_pure_pursuit_cmd,
    find_lookahead_point,
    is_drivable,
)


class QuinticSpline1D:
    """Одномерный квинтовый сплайн s(t): эталон гладкой траектории для тестов."""

    def __init__(
        self,
        x0: float,
        v0: float,
        a0: float,
        x1: float,
        v1: float,
        a1: float,
        duration: float,
    ) -> None:
        self.t_total = max(1e-4, float(duration))
        self.a0 = float(x0)
        self.a1 = float(v0)
        self.a2 = 0.5 * float(a0)

        t = self.t_total
        t2 = t * t
        t3 = t2 * t
        t4 = t3 * t
        t5 = t4 * t

        h = float(x1) - float(x0)
        self.a3 = (10.0 * h - (4.0 * float(v1) + 6.0 * float(v0)) * t + 0.5 * (float(a1) - 3.0 * float(a0)) * t2) / t3
        self.a4 = (-15.0 * h + (7.0 * float(v1) + 8.0 * float(v0)) * t - (float(a1) - 1.5 * float(a0)) * t2) / t4
        self.a5 = (6.0 * h - 3.0 * (float(v1) + float(v0)) * t + 0.5 * (float(a1) - float(a0)) * t2) / t5

    def calc_point(self, t: float) -> float:
        """Положение s(t)."""
        t = np.clip(t, 0.0, self.t_total)
        return float(
            self.a0
            + self.a1 * t
            + self.a2 * (t**2)
            + self.a3 * (t**3)
            + self.a4 * (t**4)
            + self.a5 * (t**5)
        )

    def calc_first_derivative(self, t: float) -> float:
        """Первая производная s'(t) (скорость)."""
        t = np.clip(t, 0.0, self.t_total)
        return float(
            self.a1
            + 2.0 * self.a2 * t
            + 3.0 * self.a3 * (t**2)
            + 4.0 * self.a4 * (t**3)
            + 5.0 * self.a5 * (t**4)
        )

    def calc_second_derivative(self, t: float) -> float:
        """Вторая производная s''(t) (ускорение)."""
        t = np.clip(t, 0.0, self.t_total)
        return float(
            2.0 * self.a2
            + 6.0 * self.a3 * t
            + 12.0 * self.a4 * (t**2)
            + 20.0 * self.a5 * (t**3)
        )


def smooth_yaw_rate_quintic(
    w_curr: float,
    w_target: float,
    dt: float = 0.1,
    horizon_s: float = 0.3,
) -> float:
    """Эталонное сглаживание угловой скорости сплайном для тестов."""
    if abs(w_target - w_curr) < 1e-4:
        return float(w_target)
    spline = QuinticSpline1D(
        x0=w_curr,
        v0=0.0,
        a0=0.0,
        x1=w_target,
        v1=0.0,
        a1=0.0,
        duration=max(dt, horizon_s),
    )
    return spline.calc_point(dt)


def compute_stanley_cmd(
    pose: Tuple[float, float, float],
    path: np.ndarray,
    last_s: float = 0.0,
    v_max: float = 1.39,
    k_e: float = 1.5,
    k_soft: float = 0.5,
    a_lat_max: float = 0.85,
) -> Tuple[float, float, Tuple[float, float], float, float]:
    """Эталонный регулятор Стэнли для тестов альтернатив."""
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

    curr_s, cross_e, theta_e, _ = compute_cross_track_error(path, x, y, th, last_s=last_s)
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

    delta_cross = math.atan2(-k_e * cross_e, v + k_soft)
    delta_steer = wrap_angle(theta_e + delta_cross)

    if is_dock_zone or v <= 0.05:
        lx = max(0.5, ld)
        w = 2.0 * v * math.sin(alpha) / lx if v > 0.05 else float(np.clip(1.5 * alpha, -1.0, 1.0))
    else:
        lx = max(0.6, ld)
        w = 2.0 * v * math.sin(delta_steer) / lx
    w = float(np.clip(w, -1.0, 1.0))

    return v, w, target_pt, curr_s, rem_dist


def load_test_map():
    scenario_path = "amrsim-participants/scenarios/01_clear.json"
    if os.path.exists(scenario_path):
        with open(scenario_path, "r", encoding="utf-8") as f:
            sc = json.load(f)
            return sc["map"]
    # Fallback synthetic map conforming to AMR warehouse spec
    return {
        "drivable": [
            [[50.0, 147.5], [56.0, 147.5], [56.0, 152.5], [50.0, 152.5]],
            [[56.0, 140.0], [75.0, 140.0], [75.0, 160.0], [56.0, 160.0]],
            [[56.0, 147.5], [222.5, 147.5], [222.5, 152.5], [56.0, 152.5]],
            [[217.5, 152.5], [222.5, 152.5], [222.5, 160.0], [217.5, 160.0]],
            [[62.5, 92.0], [67.5, 92.0], [67.5, 147.5], [62.5, 147.5]],
            [[62.5, 92.0], [225.0, 92.0], [225.0, 97.0], [62.5, 97.0]],
            [[187.5, 84.0], [192.5, 84.0], [192.5, 92.0], [187.5, 92.0]],
        ],
        "zones": [
            {
                "id": "FB_HAZ",
                "type": "forbidden",
                "polygon": [[68.0, 154.0], [75.0, 154.0], [75.0, 160.0], [68.0, 160.0]],
            },
            {
                "id": "SL_CROSS",
                "type": "speed_limit",
                "v_max": 0.8,
                "polygon": [[60.0, 108.0], [70.0, 108.0], [70.0, 128.0], [60.0, 128.0]],
            },
            {
                "id": "SL_YARD",
                "type": "speed_limit",
                "v_max": 1.0,
                "polygon": [[105.0, 145.0], [160.0, 145.0], [160.0, 155.0], [105.0, 155.0]],
            },
        ],
        "points": {
            "warehouse": {"x": 51.5, "y": 150.0, "heading": math.pi, "tol": 0.2},
            "shop_a": {"x": 220.0, "y": 158.5, "heading": math.pi / 2, "tol": 0.2},
            "shop_b": {"x": 223.5, "y": 94.5, "heading": 0.0, "tol": 0.2},
            "charger": {"x": 190.0, "y": 85.5, "heading": -math.pi / 2, "tol": 0.2},
        },
    }


class TestRouteFollower(unittest.TestCase):
    def setUp(self):
        self.map_dict = load_test_map()
        self.rf = RouteFollower(self.map_dict)

    def test_planner_alias(self):
        self.assertIs(Planner, RouteFollower)
        p = Planner(self.map_dict)
        self.assertIsInstance(p, RouteFollower)

    def test_fb_haz_exclusion(self):
        # Point inside FB_HAZ must not be drivable
        in_haz_x, in_haz_y = 70.0, 156.0
        self.assertFalse(self.rf.is_drivable(in_haz_x, in_haz_y, margin=0.0))
        self.assertFalse(self.rf.is_drivable(in_haz_x, in_haz_y, margin=0.2))

        # Point in north corridor outside FB_HAZ must be drivable
        in_corr_x, in_corr_y = 100.0, 151.0
        self.assertTrue(self.rf.is_drivable(in_corr_x, in_corr_y, margin=0.2))

        # Point near boundary of north corridor (y=152.4, edge at 152.5) should fail margin 0.2
        self.assertFalse(self.rf.is_drivable(100.0, 152.4, margin=0.2))

    def test_speed_zones(self):
        # 1. Normal corridor outside speed limits -> 1.39 m/s
        v1 = self.rf.check_speed_zones(80.0, 151.0, 0.0)
        self.assertAlmostEqual(v1, 1.39)

        # 2. Inside SL_YARD (v_max = 1.0) -> v_zone - 0.05 = 0.95 m/s
        v2 = self.rf.check_speed_zones(120.0, 151.0, 0.0)
        self.assertAlmostEqual(v2, 0.95)

        # 3. +3.0m ahead enters SL_YARD while current position is 2.0m before zone (x = 103.0)
        # Heading is East (th=0.0), point ahead is at x = 106.0 (inside SL_YARD [105, 160])
        v3 = self.rf.check_speed_zones(103.0, 151.0, 0.0)
        self.assertAlmostEqual(v3, 0.95)

        # 4. Inside SL_CROSS (v_max = 0.8) -> v_zone - 0.05 = 0.75 m/s
        v4 = self.rf.check_speed_zones(65.0, 115.0, -math.pi / 2)
        self.assertAlmostEqual(v4, 0.75)

    def test_mission_switch_and_from_planning(self):
        ref_path = [
            [51.5, 150.0],
            [55.0, 150.0],
            [217.5, 151.0],
            [220.0, 158.5],
        ]
        mission = {
            "id": "m1",
            "from": "warehouse",
            "to": "shop_a",
            "deadline_s": 200.0,
            "reference_path": ref_path,
        }

        # Case 1: Robot is already at warehouse (51.5, 150.0) -> distance <= 1.5m
        pose_close = (51.5, 150.0, 0.0)
        self.rf.update_mission(mission, pose_close)
        self.assertEqual(len(self.rf.active_path), len(ref_path))
        self.assertFalse(self.rf.arrived)
        self.assertEqual(self.rf.hold_count, 0)

        # Case 2: Robot starts far from 'from' point (e.g. hidden scenario displaced start: x=65.0, y=143.0)
        # Distance to warehouse (51.5, 150.0) is hypot(13.5, 7.0) ~ 15.2m > 1.5m
        pose_far = (65.0, 143.0, math.pi / 2)
        mission2 = {
            "id": "m2_hidden",
            "from": "warehouse",
            "to": "shop_a",
            "deadline_s": 200.0,
            "reference_path": ref_path,
        }
        self.rf.update_mission(mission2, pose_far)
        # Should generate initial leg to 'from' and prepend to active path
        self.assertGreater(len(self.rf.active_path), len(ref_path))
        # The path must pass within 1.5m of warehouse (51.5, 150.0)
        dists_to_from = [math.hypot(p[0] - 51.5, p[1] - 150.0) for p in self.rf.active_path]
        self.assertLess(min(dists_to_from), 1.5)

    def test_pure_pursuit_rotation_and_speed_limits(self):
        straight_path = np.array(
            [
                [100.0, 151.0],
                [150.0, 151.0],
                [200.0, 151.0],
            ]
        )

        # 1. In-place rotation when |alpha| > 0.8 rad:
        # Robot at (100, 151), path goes East (+X, angle 0), robot points North (th = pi/2 ~ 1.57 rad)
        # alpha = 0 - pi/2 = -1.57 rad (|alpha| > 0.8)
        pose_rot = (100.0, 151.0, math.pi / 2)
        v, w, tgt, curr_s, rem_dist = self.rf.pure_pursuit(pose_rot, straight_path)
        self.assertEqual(v, 0.0)
        self.assertLessEqual(abs(w), 0.8)
        self.assertLess(w, 0.0)  # should rotate clockwise (negative)

        # 2. Curvature speed limit: a_lat = v^2 * |kappa| <= a_lat_max
        pose_turn = (100.0, 151.0, 0.5)  # alpha = -0.5 rad
        v_turn, w_turn, tgt_turn, _, _ = self.rf.pure_pursuit(pose_turn, straight_path)
        self.assertLess(v_turn, 1.39)
        self.assertGreater(v_turn, 0.5)
        # Verify lateral acceleration does not exceed a_lat_max (0.85 m/s^2)
        kappa = 2.0 * math.sin(0.5) / 1.5
        expected_v = math.sqrt(0.85 / kappa)
        self.assertAlmostEqual(v_turn, expected_v, places=3)
        self.assertLessEqual(v_turn**2 * kappa, 0.85 + 1e-5)

        # 3. Straight course -> nominal speed (up to v_max)
        pose_str = (100.0, 151.0, 0.0)
        v_str, w_str, _, _, _ = self.rf.pure_pursuit(pose_str, straight_path)
        self.assertGreater(v_str, 1.0)
        self.assertAlmostEqual(w_str, 0.0, delta=1e-3)

    def test_curvature_optimal_speed_profile(self):
        """Регрессионный тест: непрерывный профиль скорости по боковому ускорению a_lat."""
        # 1. Прямолинейное движение (alpha = 0): скорость номинальная 1.39 м/с
        v0 = compute_curvature_speed_limit(0.0, 1.5, a_lat_max=0.85, v_nominal=1.39)
        self.assertAlmostEqual(v0, 1.39)

        # 2. Плавный изгиб (alpha = 0.2 рад): a_lat = v^2 * kappa < a_lat_max -> 1.39 м/с
        v_gentle = compute_curvature_speed_limit(0.2, 1.5, a_lat_max=0.85, v_nominal=1.39)
        self.assertAlmostEqual(v_gentle, 1.39)

        # 3. Средняя кривизна (alpha = 0.5 рад, lookahead = 1.5 м):
        # kappa = 2 * sin(0.5) / 1.5 ~ 0.6392 м^-1
        # v_curve = sqrt(0.85 / 0.6392) ~ 1.153 м/с
        v_curve = compute_curvature_speed_limit(0.5, 1.5, a_lat_max=0.85, v_nominal=1.39)
        self.assertAlmostEqual(v_curve, 1.153, places=3)
        self.assertLess(v_curve, 1.39)
        a_lat = v_curve**2 * (2.0 * math.sin(0.5) / 1.5)
        self.assertLessEqual(a_lat, 0.85 + 1e-6)

        # 4. Крутой поворот (alpha = 0.8 рад):
        # kappa = 2 * sin(0.8) / 1.5 ~ 0.9565 м^-1
        # v_curve = sqrt(0.85 / 0.9565) ~ 0.943 м/с
        v_sharp = compute_curvature_speed_limit(0.8, 1.5, a_lat_max=0.85, v_nominal=1.39)
        self.assertAlmostEqual(v_sharp, 0.943, places=3)
        self.assertLess(v_sharp, v_curve)

        # 5. Разворот на месте при |alpha| > 0.85 рад в pure_pursuit
        straight_path = np.array([[0.0, 0.0], [10.0, 0.0]])
        pose_pivot = (0.0, 0.0, 1.0)  # alpha = -1.0 rad (|alpha| > 0.85)
        v_piv, w_piv, _, _, _ = self.rf.pure_pursuit(pose_pivot, straight_path)
        self.assertEqual(v_piv, 0.0)
        self.assertNotEqual(w_piv, 0.0)

        # 6. Метод на RouteFollower с переопределением a_lat_max
        v_custom = self.rf.compute_curvature_speed_limit(0.5, 1.5, a_lat_max=0.7)
        self.assertAlmostEqual(v_custom, math.sqrt(0.7 / (2.0 * math.sin(0.5) / 1.5)), places=3)

    def test_pure_pursuit_braking_and_dock(self):
        dock_path = np.array(
            [
                [217.5, 151.0],
                [220.0, 158.5],
            ]
        )

        # 1. Lookahead in dock zone (remaining distance <= 0.6m):
        # Target must be strictly the dock goal (220.0, 158.5) and v <= 0.25 m/s
        pose_dock = (220.0, 158.0, math.pi / 2)  # 0.5m to goal
        v_dock, w_dock, tgt_dock, _, rem_dock = self.rf.pure_pursuit(pose_dock, dock_path)
        self.assertLessEqual(v_dock, 0.25)
        self.assertAlmostEqual(tgt_dock[0], 220.0)
        self.assertAlmostEqual(tgt_dock[1], 158.5)

        # Outside dock zone (> 0.6m): robot is not limited to 0.15/0.25 m/s dock crawl
        self.rf.last_s = 0.0
        pose_approach = (220.0, 157.0, math.pi / 2)  # 1.5m to goal
        v_app, _, _, _, _ = self.rf.pure_pursuit(pose_approach, dock_path)
        self.assertGreater(v_app, 0.5)

        # 2. Terminal arrival within 0.10m:
        cmd = self.rf.step(
            (220.0, 158.45, math.pi / 2),
            mission={
                "id": "dock_test",
                "from": "warehouse",
                "to": "shop_a",
                "goal": [220.0, 158.5, math.pi / 2],
                "reference_path": dock_path.tolist(),
            },
        )
        self.assertEqual(cmd["status"], "arrived")
        self.assertTrue(cmd["arrived"])
        self.assertEqual(cmd["v"], 0.0)

    def test_lateral_offset_avoidance(self):
        # Obstacle r=0.4 at x=120.0, y=153.0 (2.0m north of corridor centerline y=151.0)
        # Reference path along northern road y=151.0
        ref_path = [
            [100.0, 151.0],
            [140.0, 151.0],
        ]
        mission = {
            "id": "m_pallet",
            "from": [100.0, 151.0],
            "to": [140.0, 151.0],
            "reference_path": ref_path,
        }

        obstacle = {"x": 120.0, "y": 153.0, "r": 0.4}
        pose = (100.0, 151.0, 0.0)

        cmd = self.rf.step(pose, mission=mission, obstacles=[obstacle])
        # plan/03:110, plan/04:45: note carries the actual lateral shift in m.
        self.assertTrue(cmd["note"].startswith("offset dy="))
        self.assertAlmostEqual(float(cmd["note"].split("=", 1)[1]), -0.6, places=1)
        self.assertEqual(cmd["status"], "moving")

        # Verify active path shifts southward (y < 151.0) and maintains gap > 1.1m
        # Obstacle at y=153.0, platform radius 0.9, obstacle radius 0.4:
        # Distance must be > 0.9 + 0.4 + 1.1 = 2.4m, so shifted y <= 150.6
        min_shifted_y = min(p[1] for p in self.rf.active_path)
        self.assertLessEqual(min_shifted_y, 150.61)

        # Ensure all shifted points remain inside corridor with margin 0.2m (corridor y in [147.5, 152.5])
        self.assertGreaterEqual(min_shifted_y, 147.7)

    def test_astar_replan_when_offset_does_not_fit(self):
        # South road: y in [92.0, 97.0], centerline at y=94.5
        # Obstacle centered at (110.0, 95.0) with r=0.8
        # Lateral shift requires gap > 1.1m -> shifted y < 95.0 - 2.8 = 92.2
        # Which breaches 0.2m margin from south boundary 92.0!
        # Meanwhile A* requires clearance 0.9 + 0.35 + 0.8 = 2.05m -> y down to 92.95m fits cleanly!
        ref_path = [
            [80.0, 94.5],
            [140.0, 94.5],
        ]
        mission = {
            "id": "m_container",
            "from": [80.0, 94.5],
            "to": [140.0, 94.5],
            "reference_path": ref_path,
        }

        obstacle = {"x": 110.0, "y": 95.0, "r": 0.8}
        pose = (80.0, 94.5, 0.0)

        cmd = self.rf.step(pose, mission=mission, obstacles=[obstacle])
        self.assertEqual(cmd["note"], "replan")
        self.assertEqual(cmd["status"], "moving")

    def test_stop_object_when_fully_blocked(self):
        # Complete blockage of corridor
        ref_path = [
            [80.0, 94.5],
            [140.0, 94.5],
        ]
        mission = {
            "id": "m_wall",
            "from": [80.0, 94.5],
            "to": [140.0, 94.5],
            "reference_path": ref_path,
        }

        # Multi-point wall spanning entire width from y=91 to y=98
        wall_obstacles = [
            {"x": 110.0, "y": 92.0, "r": 0.8},
            {"x": 110.0, "y": 93.5, "r": 0.8},
            {"x": 110.0, "y": 95.0, "r": 0.8},
            {"x": 110.0, "y": 96.5, "r": 0.8},
        ]
        pose = (80.0, 94.5, 0.0)

        cmd = self.rf.step(pose, mission=mission, obstacles=wall_obstacles)
        self.assertEqual(cmd["v"], 0.0)
        self.assertEqual(cmd["status"], "waiting")
        self.assertEqual(cmd["note"], "stop_object")

    def test_grid_free_cells_respect_boundary_margin(self):
        # plan/04:40: a free A* cell must keep a 0.2 m margin from the aisle
        # boundary, so the margin is baked into the static grid.
        rf = self.rf
        ys, xs = np.nonzero(rf.static_free_grid)
        pts = np.column_stack([rf.x_min + xs * rf.grid_res, rf.y_min + ys * rf.grid_res])
        self.assertTrue(np.all(rf.is_drivable(pts, margin=0.2)))

        # A cell sitting on the northern aisle boundary (edge y=152.5) is not free.
        ci, cj = rf._coord_to_cell(100.0, 152.5)
        self.assertFalse(rf.static_free_grid[ci, cj])

    def test_astar_grid_excludes_forbidden_and_keeps_margin(self):
        # plan/04:28,40: FB_HAZ is cut out of the free grid and A* must detour
        # around it while every routed centre stays inside drivable space.
        fb_haz = np.array([[68.0, 154.0], [75.0, 154.0], [75.0, 160.0], [68.0, 160.0]])
        path = self.rf.plan_path((65.0, 155.0), (80.0, 151.0))
        self.assertIsNotNone(path)
        pts = np.asarray(path, dtype=float)
        self.assertTrue(np.all(self.rf.is_drivable(pts, margin=0.2)))
        self.assertFalse(np.any(inside_polygon(pts, fb_haz)))
        # The straight cut through FB_HAZ is impossible -> a real detour.
        self.assertGreater(len(path), 2)

    def test_offset_prefers_roomy_side_on_west_exit(self):
        # plan/04:38: the western exit (reference x=66) must shift west, never
        # east into the ~0.6 m strip; the roomy-side rule picks it.
        ref_path = [[66.0, 100.0], [66.0, 140.0]]
        mission = {
            "id": "m_west",
            "from": [66.0, 100.0],
            "to": [66.0, 140.0],
            "reference_path": ref_path,
        }
        obstacle = {"x": 68.0, "y": 120.0, "r": 0.4}
        cmd = self.rf.step((66.0, 100.0, math.pi / 2), mission=mission, obstacles=[obstacle])
        self.assertTrue(cmd["note"].startswith("offset dy="))
        dy = float(cmd["note"].split("=", 1)[1])
        self.assertGreater(dy, 0.0)  # west = +left-normal for a northbound leg
        self.assertLess(min(p[0] for p in self.rf.active_path), 66.0)

    def test_astar_rejoins_reference_on_clear_line_of_sight(self):
        # plan/04:40: re-join the reference as soon as the straight line to it
        # is clear, instead of a fixed +5 m.
        ref_path = np.array([[80.0, 94.5], [140.0, 94.5]])
        # Obstacle 2.5 m north of the centreline triggers tube avoidance, but
        # the straight line to the remaining reference is already clear.
        obstacle = (110.0, 97.0, 0.8, 30.0)
        replanned = self.rf.replan_astar(
            (80.0, 94.5, 0.0), ref_path, obstacle, all_obstacles=[(110.0, 97.0, 0.8)]
        )
        self.assertIsNotNone(replanned)
        pts = np.asarray(replanned, dtype=float)
        joined = np.isclose(pts[:, 0], 110.0) & np.isclose(pts[:, 1], 94.5)
        self.assertEqual(int(joined.sum()), 1)
        fixed_5m = np.isclose(pts[:, 0], 115.0) & np.isclose(pts[:, 1], 94.5)
        self.assertFalse(bool(fixed_5m.any()))

    def test_replan_throttled_to_two_seconds(self):
        # plan/04:41: retry the A* replan at most once every 2 s.
        ref_path = [[80.0, 94.5], [140.0, 94.5]]
        mission = {
            "id": "m_throttle",
            "from": [80.0, 94.5],
            "to": [140.0, 94.5],
            "t_start": 0.0,
            "deadline_s": 500.0,
            "reference_path": ref_path,
        }
        wall = [
            {"x": 110.0, "y": 92.0, "r": 0.8},
            {"x": 110.0, "y": 93.5, "r": 0.8},
            {"x": 110.0, "y": 95.0, "r": 0.8},
            {"x": 110.0, "y": 96.5, "r": 0.8},
        ]
        pose = (80.0, 94.5, 0.0)

        cmd0 = self.rf.step(pose, mission=mission, obstacles=wall, current_time=0.0)
        self.assertEqual(cmd0["note"], "stop_object")
        self.assertAlmostEqual(self.rf.last_replan_t, 0.0)

        cmd1 = self.rf.step(pose, mission=mission, obstacles=wall, current_time=1.0)
        self.assertEqual(cmd1["note"], "stop_object")
        self.assertAlmostEqual(self.rf.last_replan_t, 0.0)  # no new attempt

        cmd2 = self.rf.step(pose, mission=mission, obstacles=wall, current_time=2.0)
        self.assertEqual(cmd2["note"], "stop_object")
        self.assertAlmostEqual(self.rf.last_replan_t, 2.0)  # retried after 2 s

    def test_final_approach_on_deadline_skips_extra_stop(self):
        # plan/04:55: below 8 s to the deadline, within 2 m of the goal and a
        # clear corridor -> dock at the allowed speed without extra stops.
        ref_path = [[80.0, 94.5], [100.0, 94.5], [80.0, 94.5]]
        obstacle = {"x": 90.0, "y": 97.0, "r": 0.8}
        pose = (80.5, 94.5, 0.0)

        far = {
            "id": "m_far",
            "from": [80.0, 94.5],
            "to": [80.0, 94.5],
            "t_start": 0.0,
            "deadline_s": 100.0,
            "reference_path": ref_path,
        }
        cmd_far = self.rf.step(pose, mission=far, obstacles=[obstacle], current_time=0.0)
        self.assertFalse(self.rf.final_approach)
        self.assertTrue(cmd_far["note"].startswith("offset dy="))

        near_rf = RouteFollower(self.map_dict)
        near = {
            "id": "m_near",
            "from": [80.0, 94.5],
            "to": [80.0, 94.5],
            "t_start": 0.0,
            "deadline_s": 5.0,
            "reference_path": ref_path,
        }
        cmd_near = near_rf.step(pose, mission=near, obstacles=[obstacle], current_time=0.0)
        self.assertTrue(near_rf.final_approach)
        self.assertEqual(cmd_near["status"], "moving")
        self.assertIsNone(cmd_near["note"])


class TestRouteCoverage(unittest.TestCase):
    def test_priority_queue_empty_pop(self):
        from team_dreamteam_4_0.route import _PriorityQueue

        pq = _PriorityQueue()
        with self.assertRaises(IndexError):
            pq.get()

    def test_init_grid_empty_drivable(self):
        rf = RouteFollower({"drivable": []})
        self.assertEqual(rf.x_min, 0.0)
        self.assertEqual(rf.y_min, 0.0)
        self.assertEqual(rf.x_max, 250.0)

    def test_resolve_point_formats(self):
        rf = RouteFollower(load_test_map())
        # dict with x, y
        self.assertEqual(rf.get_point_xy({"x": 12.0, "y": 34.0}), (12.0, 34.0))
        # fallback
        self.assertEqual(rf.get_point_xy(None, fallback=(5.0, 6.0)), (5.0, 6.0))
        # default (0, 0)
        self.assertEqual(rf.get_point_xy(None), (0.0, 0.0))

    def test_parse_obstacles_numpy_2d(self):
        rf = RouteFollower(load_test_map())
        obs_arr = np.array([[10.0, 20.0, 0.5], [30.0, 40.0, 0.4]])
        parsed = rf._parse_obstacles(obs_arr)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0], (10.0, 20.0, 0.5))
        self.assertEqual(parsed[1], (30.0, 40.0, 0.4))

    def test_path_progress_edge_cases(self):
        rf = RouteFollower(load_test_map())
        # len < 2
        self.assertEqual(rf._get_path_progress(np.array([[0.0, 0.0]]), 5.0, 5.0), 0.0)
        # degenerate zero-length segment
        path = np.array([[0.0, 0.0], [0.0, 0.0], [10.0, 0.0]])
        prog = rf._get_path_progress(path, 5.0, 0.0)
        self.assertAlmostEqual(prog, 5.0)

    def test_check_obstacles_in_tube_and_lateral_offset_edges(self):
        rf = RouteFollower(load_test_map())
        # len < 2 in apply_lateral_offset
        self.assertIsNone(rf.apply_lateral_offset(np.array([[0.0, 0.0]]), (0, 0, 0, 0), 0.0))

        # Obstacle near dock point (last 3.0m) or behind robot
        path = np.array([[0.0, 0.0], [0.0, 0.0], [10.0, 0.0], [20.0, 0.0]])
        # 1. Zero-length segment (line 548)
        # 2. Obstacle behind current_s (line 555)
        # 3. Obstacle in last 3m (line 558)
        parsed = [(0.0, -10.0, 0.4), (19.0, 0.0, 0.4)]
        obs = rf.check_obstacles_in_tube(path, parsed, current_s=5.0)
        # Should not trigger near terminal dock or behind robot
        self.assertIsNone(obs)

    def test_follow_path_close_to_goal(self):
        rf = RouteFollower(load_test_map())
        path = np.array([[0.0, 0.0], [1.0, 0.0]])
        v, w, target_pt, curr_s, rem_dist = rf.pure_pursuit((0.99, 0.0, 0.0), path, 0.98)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

    def test_step_active_path_short_and_dock_align(self):
        rf = RouteFollower(load_test_map())
        # Empty / short active path (< 2)
        rf.active_path = np.empty((0, 2))
        cmd = rf.step((0.0, 0.0, 0.0))
        self.assertEqual(cmd["status"], "waiting")

        # Arrival dock alignment with goal heading dth > 0.05
        rf.active_path = np.array([[0.0, 0.0], [1.0, 0.0]])
        mission = {
            "id": "m_align",
            "from": [0.0, 0.0],
            "goal": [1.0, 0.0, math.pi / 2],
            "reference_path": [[0.0, 0.0], [1.0, 0.0]],
        }
        cmd_arr = rf.step((1.0, 0.0, 0.0), mission=mission)
        self.assertEqual(cmd_arr["status"], "arrived")
        self.assertGreater(abs(cmd_arr["w"]), 0.0)

    def test_step_replan_window_pass(self):
        rf = RouteFollower(load_test_map())
        rf.active_path = np.array([[0.0, 0.0], [10.0, 0.0]])
        rf.note = "replan"
        rf.last_replan_t = 0.0
        rf.replan_interval = 2.0
        # Obstacle blocking path
        obs = [(5.0, 0.0, 0.5)]
        # Replan attempt prevented by throttle, but note == 'replan' (line 922)
        cmd = rf.step((0.0, 0.0, 0.0), obstacles=obs, current_time=1.0)
        self.assertIn("v", cmd)

    def test_import_fallback(self):
        import sys

        mod_name = "team.route"
        if mod_name in sys.modules:
            orig = sys.modules[mod_name]
            try:
                with open("/Users/yegor/doc-1790342627/team/route.py", "r") as f:
                    code = f.read()
                globs = {
                    "__name__": "__main__",
                    "__file__": "/Users/yegor/doc-1790342627/team/route.py",
                    "__package__": "",
                }
                team_path = "/Users/yegor/doc-1790342627/team"
                if team_path not in sys.path:
                    sys.path.insert(0, team_path)
                exec(compile(code, "/Users/yegor/doc-1790342627/team/route.py", "exec"), globs)
            finally:
                sys.modules[mod_name] = orig


    def test_stanley_controller_tracking(self):
        straight_path = np.array(
            [
                [100.0, 151.0],
                [150.0, 151.0],
                [200.0, 151.0],
            ]
        )
        # 1. On path, heading aligned -> cross error 0, w ~ 0
        v, w, tgt, curr_s, rem_dist = compute_stanley_cmd((100.0, 151.0, 0.0), straight_path)
        self.assertGreater(v, 1.0)
        self.assertAlmostEqual(w, 0.0, delta=1e-3)

        # 2. Offset to the left (y = 151.3 > 151.0) -> steer clockwise (negative w)
        v_l, w_l, _, _, _ = compute_stanley_cmd((100.0, 151.3, 0.0), straight_path)
        self.assertLess(w_l, -0.1)

        # 3. Offset to the right (y = 150.7 < 151.0) -> steer counter-clockwise (positive w)
        v_r, w_r, _, _, _ = compute_stanley_cmd((100.0, 150.7, 0.0), straight_path)
        self.assertGreater(w_r, 0.1)

        # 4. Heading error positive -> negative corrective steering
        v_h, w_h, _, _, _ = compute_stanley_cmd((100.0, 151.0, 0.1), straight_path)
        self.assertLess(w_h, 0.0)

        # 5. Direct standalone compute_stanley_cmd call
        v_s, w_s, tgt_s, curr_s_s, rem_s = compute_stanley_cmd((100.0, 151.0, 0.0), straight_path)
        self.assertGreater(v_s, 1.0)
        self.assertAlmostEqual(w_s, 0.0, delta=1e-3)

        # 6. Cross-track computation directly
        s, cross_e, th_e, idx = compute_cross_track_error(straight_path, 105.0, 151.4, 0.0)
        self.assertAlmostEqual(s, 5.0)
        self.assertAlmostEqual(cross_e, 0.4)
        self.assertAlmostEqual(th_e, 0.0)

    def test_quintic_spline_smoothing(self):
        # Boundary condition validation
        spline = QuinticSpline1D(x0=0.0, v0=0.0, a0=0.0, x1=1.0, v1=0.0, a1=0.0, duration=1.0)
        self.assertAlmostEqual(spline.calc_point(0.0), 0.0)
        self.assertAlmostEqual(spline.calc_point(1.0), 1.0)
        self.assertAlmostEqual(spline.calc_first_derivative(0.0), 0.0)
        self.assertAlmostEqual(spline.calc_first_derivative(1.0), 0.0)
        self.assertAlmostEqual(spline.calc_second_derivative(0.0), 0.0)
        self.assertAlmostEqual(spline.calc_second_derivative(1.0), 0.0)

        # Intermediate smoothness: midpoint value for symmetric quintic is 0.5
        self.assertAlmostEqual(spline.calc_point(0.5), 0.5)

        # Test non-zero initial and terminal conditions:
        spline_dyn = QuinticSpline1D(x0=1.0, v0=2.0, a0=3.0, x1=5.0, v1=-1.0, a1=0.5, duration=2.0)
        self.assertAlmostEqual(spline_dyn.calc_point(0.0), 1.0)
        self.assertAlmostEqual(spline_dyn.calc_point(2.0), 5.0)
        self.assertAlmostEqual(spline_dyn.calc_first_derivative(0.0), 2.0)
        self.assertAlmostEqual(spline_dyn.calc_first_derivative(2.0), -1.0)
        self.assertAlmostEqual(spline_dyn.calc_second_derivative(0.0), 3.0)
        self.assertAlmostEqual(spline_dyn.calc_second_derivative(2.0), 0.5)

        # Function smooth_yaw_rate_quintic limits abrupt jump
        w_smooth = smooth_yaw_rate_quintic(w_curr=0.0, w_target=1.0, dt=0.1, horizon_s=0.3)
        self.assertGreater(w_smooth, 0.0)
        self.assertLess(w_smooth, 0.5)  # significantly smoothed compared to raw jump 1.0

    def test_compute_cross_track_error_degenerate_paths(self):
        # Empty path
        s, cross_e, th_e, idx = compute_cross_track_error(np.empty((0, 2)), 10.0, 20.0, 0.0, last_s=3.5)
        self.assertEqual(s, 3.5)
        self.assertEqual(cross_e, 0.0)
        self.assertEqual(th_e, 0.0)
        self.assertEqual(idx, 0)

        # Single point path
        s1, cross_e1, th_e1, idx1 = compute_cross_track_error(np.array([[10.0, 20.0]]), 10.0, 20.0, 0.0, last_s=5.0)
        self.assertEqual(s1, 5.0)
        self.assertEqual(cross_e1, 0.0)
        self.assertEqual(th_e1, 0.0)
        self.assertEqual(idx1, 0)

    def test_terminal_stopping_priority_over_large_angle(self):
        """Terminal stopping condition must return (0, 0, ..., 0.0) even if angle error > 0.85."""
        path = np.array([[0.0, 0.0], [1.0, 0.0]])
        # Robot sitting directly at goal (1.0, 0.0) with opposite heading th = math.pi
        # Heading to target point produces |alpha| ~ pi > 0.85
        pose = (1.0, 0.0, math.pi)

        # Pure pursuit command must stop with zero velocity and zero remaining distance
        v_pp, w_pp, target_pp, s_pp, rem_pp = compute_pure_pursuit_cmd(pose, path, last_s=0.99)
        self.assertEqual(v_pp, 0.0)
        self.assertEqual(w_pp, 0.0)
        self.assertEqual(rem_pp, 0.0)

        # Stanley command must also stop with zero velocity and zero remaining distance
        v_st, w_st, target_st, s_st, rem_st = compute_stanley_cmd(pose, path, last_s=0.99)
        self.assertEqual(v_st, 0.0)
        self.assertEqual(w_st, 0.0)
        self.assertEqual(rem_st, 0.0)

    def test_is_drivable_empty_inputs(self):
        """Unhandled empty point sequence in is_drivable must not raise IndexError."""
        # Standalone function checks
        res1 = is_drivable(np.zeros((0, 2)))
        self.assertIsInstance(res1, np.ndarray)
        self.assertEqual(len(res1), 0)

        res2 = is_drivable(np.array([]))
        self.assertIsInstance(res2, np.ndarray)
        self.assertEqual(len(res2), 0)

        res3 = is_drivable([])
        self.assertIsInstance(res3, np.ndarray)
        self.assertEqual(len(res3), 0)

        res4 = is_drivable(np.array([]), np.array([]))
        self.assertIsInstance(res4, np.ndarray)
        self.assertEqual(len(res4), 0)

        res5 = is_drivable([], [])
        self.assertIsInstance(res5, np.ndarray)
        self.assertEqual(len(res5), 0)

        # RouteFollower method checks
        rf = RouteFollower(load_test_map())
        rf_res1 = rf.is_drivable(np.zeros((0, 2)))
        self.assertIsInstance(rf_res1, np.ndarray)
        self.assertEqual(len(rf_res1), 0)

        rf_res2 = rf.is_drivable(np.array([]))
        self.assertIsInstance(rf_res2, np.ndarray)
        self.assertEqual(len(rf_res2), 0)


class TestRouteDefectFixes(unittest.TestCase):
    def setUp(self):
        self.map_dict = load_test_map()
        self.rf = RouteFollower(self.map_dict)

    def test_empty_reference_path_update_mission(self):
        """P0: update_mission with empty reference_path should not raise IndexError."""
        mission_empty = {"id": "empty_mission", "reference_path": []}
        # Should not raise IndexError
        self.rf.update_mission(mission_empty, (10.0, 10.0, 0.0))
        self.assertEqual(len(self.rf.active_path), 0)

        # Step should handle empty active_path gracefully
        cmd = self.rf.step((10.0, 10.0, 0.0), mission=mission_empty)
        self.assertEqual(cmd["v"], 0.0)
        self.assertEqual(cmd["w"], 0.0)

    def test_check_speed_zones_non_finite_inputs(self):
        """P0: check_speed_zones with NaN or Inf should return 0.0 safely without ValueError."""
        zones = self.map_dict.get("zones", [])
        self.assertEqual(check_speed_zones(float("nan"), 10.0, 0.0, zones), 0.0)
        self.assertEqual(check_speed_zones(10.0, float("nan"), 0.0, zones), 0.0)
        self.assertEqual(check_speed_zones(10.0, 10.0, float("nan"), zones), 0.0)
        self.assertEqual(check_speed_zones(10.0, 10.0, float("inf"), zones), 0.0)
        self.assertEqual(check_speed_zones(10.0, 10.0, float("-inf"), zones), 0.0)

        # Also via RouteFollower method
        self.assertEqual(self.rf.check_speed_zones(10.0, 10.0, float("nan")), 0.0)
        self.assertEqual(self.rf.check_speed_zones(float("nan"), 10.0, 0.0), 0.0)

    def test_step_goal_representations(self):
        """P1: RouteFollower.step handles dict, 2D list/tuple, and 3D list/tuple goals."""
        path = [[100.0, 151.0], [100.05, 151.0]]
        pose = (100.05, 151.0, 0.0)  # At goal

        # 1. Dict goal with 'heading'
        m_dict_heading = {"id": "m_dh", "reference_path": path, "goal": {"heading": math.pi / 2}}
        cmd1 = self.rf.step(pose, mission=m_dict_heading)
        self.assertTrue(cmd1["arrived"])
        self.assertGreater(cmd1["w"], 0.0)

        # 2. Dict goal with 'th'
        m_dict_th = {"id": "m_dt", "reference_path": path, "goal": {"th": -math.pi / 2}}
        cmd2 = self.rf.step(pose, mission=m_dict_th)
        self.assertTrue(cmd2["arrived"])
        self.assertLess(cmd2["w"], 0.0)

        # 3. 2D list/tuple goal (no heading specified -> w should remain 0.0)
        m_2d_list = {"id": "m_2dl", "reference_path": path, "goal": [100.05, 151.0]}
        cmd3 = self.rf.step(pose, mission=m_2d_list)
        self.assertTrue(cmd3["arrived"])
        self.assertEqual(cmd3["w"], 0.0)

        m_2d_tuple = {"id": "m_2dt", "reference_path": path, "goal": (100.05, 151.0)}
        cmd4 = self.rf.step(pose, mission=m_2d_tuple)
        self.assertTrue(cmd4["arrived"])
        self.assertEqual(cmd4["w"], 0.0)

        # 4. 3D list goal
        m_3d = {"id": "m_3d", "reference_path": path, "goal": [100.05, 151.0, math.pi / 2]}
        cmd5 = self.rf.step(pose, mission=m_3d)
        self.assertTrue(cmd5["arrived"])
        self.assertGreater(cmd5["w"], 0.0)

    def test_pure_pursuit_and_stanley_nan_inf_pose(self):
        """P1: NaN or Inf pose coordinates immediately return zero velocity command."""
        path = np.array([[0.0, 0.0], [5.0, 0.0]])

        # Pure pursuit with NaN/Inf
        v, w, _, _, _ = compute_pure_pursuit_cmd((float("nan"), 0.0, 0.0), path)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

        v, w, _, _, _ = compute_pure_pursuit_cmd((0.0, float("nan"), 0.0), path)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

        v, w, _, _, _ = compute_pure_pursuit_cmd((0.0, 0.0, float("nan")), path)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

        v, w, _, _, _ = compute_pure_pursuit_cmd((float("inf"), 0.0, 0.0), path)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

        # Stanley with NaN
        v, w, _, _, _ = compute_stanley_cmd((float("nan"), 0.0, 0.0), path)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

        v, w, _, _, _ = compute_stanley_cmd((0.0, 0.0, float("nan")), path)
        self.assertEqual(v, 0.0)
        self.assertEqual(w, 0.0)

        # RouteFollower.step with NaN pose
        cmd = self.rf.step((float("nan"), 0.0, 0.0))
        self.assertEqual(cmd["v"], 0.0)
        self.assertEqual(cmd["w"], 0.0)

    def test_build_static_free_grid_empty_polys(self):
        """P2: build_static_free_grid does not crash on empty polygon arrays in drivable_polys."""
        # Empty array inside drivable_polys
        grid1, _, _, _, _, _, _ = build_static_free_grid([np.empty((0, 2))], [])
        self.assertIsInstance(grid1, np.ndarray)

        # Completely empty list
        grid2, _, _, _, _, _, _ = build_static_free_grid([], [])
        self.assertIsInstance(grid2, np.ndarray)

        # Mix of valid polygon and empty arrays
        valid_poly = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
        grid3, _, _, _, _, _, _ = build_static_free_grid(
            [valid_poly, np.empty((0, 2)), np.array([])],
            [np.empty((0, 2))],
        )
        self.assertIsInstance(grid3, np.ndarray)
        self.assertTrue(np.any(grid3))


if __name__ == "__main__":
    unittest.main()
