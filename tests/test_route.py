"""Unit tests for team.route module (RouteFollower and Planner).

Verifies Pure Pursuit tracking, speed zones, FB_HAZ forbidden zone exclusion,
mission 'from' distance leg generation, lateral offset, A* replan, and obstacle stop.
Conforms strictly to plan/04-marshrut-i-missii.md and isolation requirements.
"""
import json
import math
import os
import unittest

import numpy as np

from team.geom import inside_polygon
from team.route import Planner, RouteFollower


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
            {"id": "FB_HAZ", "type": "forbidden", "polygon": [[68.0, 154.0], [75.0, 154.0], [75.0, 160.0], [68.0, 160.0]]},
            {"id": "SL_CROSS", "type": "speed_limit", "v_max": 0.8, "polygon": [[60.0, 108.0], [70.0, 108.0], [70.0, 128.0], [60.0, 128.0]]},
            {"id": "SL_YARD", "type": "speed_limit", "v_max": 1.0, "polygon": [[105.0, 145.0], [160.0, 145.0], [160.0, 155.0], [105.0, 155.0]]},
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
        straight_path = np.array([
            [100.0, 151.0],
            [150.0, 151.0],
            [200.0, 151.0],
        ])

        # 1. In-place rotation when |alpha| > 0.8 rad:
        # Robot at (100, 151), path goes East (+X, angle 0), robot points North (th = pi/2 ~ 1.57 rad)
        # alpha = 0 - pi/2 = -1.57 rad (|alpha| > 0.8)
        pose_rot = (100.0, 151.0, math.pi / 2)
        v, w, tgt, curr_s, rem_dist = self.rf.pure_pursuit(pose_rot, straight_path)
        self.assertEqual(v, 0.0)
        self.assertLessEqual(abs(w), 0.8)
        self.assertLess(w, 0.0)  # should rotate clockwise (negative)

        # 2. Turning speed limit: |alpha| > 0.35 rad -> v <= 0.5 m/s
        pose_turn = (100.0, 151.0, 0.5)  # alpha = -0.5 rad
        v_turn, w_turn, tgt_turn, _, _ = self.rf.pure_pursuit(pose_turn, straight_path)
        self.assertLessEqual(v_turn, 0.5)
        self.assertGreater(v_turn, 0.0)

        # 3. Straight course -> nominal speed (up to v_max)
        pose_str = (100.0, 151.0, 0.0)
        v_str, w_str, _, _, _ = self.rf.pure_pursuit(pose_str, straight_path)
        self.assertGreater(v_str, 1.0)
        self.assertAlmostEqual(w_str, 0.0, delta=1e-3)

    def test_pure_pursuit_braking_and_dock(self):
        dock_path = np.array([
            [217.5, 151.0],
            [220.0, 158.5],
        ])

        # 1. Lookahead in dock zone (remaining distance <= 1.5m):
        # Target must be strictly the dock goal (220.0, 158.5) and v <= 0.15 m/s
        pose_dock = (220.0, 157.5, math.pi / 2)  # 1.0m to goal
        v_dock, w_dock, tgt_dock, _, rem_dock = self.rf.pure_pursuit(pose_dock, dock_path)
        self.assertLessEqual(v_dock, 0.15)
        self.assertAlmostEqual(tgt_dock[0], 220.0)
        self.assertAlmostEqual(tgt_dock[1], 158.5)

        # 2. Terminal arrival within 0.10m:
        cmd = self.rf.step((220.0, 158.45, math.pi / 2), mission={
            "id": "dock_test",
            "from": "warehouse",
            "to": "shop_a",
            "goal": [220.0, 158.5, math.pi / 2],
            "reference_path": dock_path.tolist(),
        })
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
        pts = np.column_stack([rf.x_min + xs * rf.grid_res,
                               rf.y_min + ys * rf.grid_res])
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
        replanned = self.rf.replan_astar((80.0, 94.5, 0.0), ref_path, obstacle,
                                         all_obstacles=[(110.0, 97.0, 0.8)])
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


if __name__ == "__main__":
    unittest.main()
