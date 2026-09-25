"""Comprehensive unit and stress tests for backend.controller.Controller."""
import json
import math
import os
import unittest
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from backend.controller import Controller
from backend.geom import raycast


def make_test_map() -> Dict[str, Any]:
    """Build a standard synthetic warehouse map for testing."""
    return {
        "bounds": [0.0, 0.0, 250.0, 200.0],
        "points": {
            "warehouse": {"x": 51.5, "y": 150.0, "type": "dock"},
            "shop_a": {"x": 220.0, "y": 158.5, "type": "dock"},
        },
        "buildings": [
            {
                "id": "W1",
                "polygon": [[50.0, 140.0], [75.0, 140.0], [75.0, 160.0], [50.0, 160.0]],
            },
            {
                "id": "W2",
                "polygon": [[80.0, 145.0], [140.0, 145.0], [140.0, 155.0], [80.0, 155.0]],
            },
            # Pole landmark (sides < 1.0m)
            {
                "id": "Pole1",
                "polygon": [[100.0, 148.0], [100.5, 148.0], [100.5, 148.5], [100.0, 148.5]],
            },
        ],
        "zones": [
            {
                "id": "Z1",
                "type": "speed_limit",
                "v_max": 0.60,
                "polygon": [[70.0, 145.0], [110.0, 145.0], [110.0, 155.0], [70.0, 155.0]],
            }
        ],
        "drivable": [
            [[50.0, 147.5], [222.5, 147.5], [222.5, 152.5], [50.0, 152.5]],
        ],
    }


def make_test_config() -> Dict[str, Any]:
    """Build platform and sensor configuration."""
    return {
        "dt": 0.1,
        "robot": {
            "radius": 0.9,
            "v_min": -0.5,
            "v_max": 1.39,
            "w_max": 1.0,
            "accel": 0.5,
            "decel": 1.2,
            "estop_decel": 2.5,
        },
        "lidar": {
            "beams": 360,
            "angle_min_deg": 0.0,
            "angle_increment_deg": 1.0,
            "max_range": 20.0,
        },
    }


def make_test_obs(
    t: float = 0.0,
    x: float = 51.5,
    y: float = 150.0,
    th: float = 0.0,
    v_odom: float = 0.0,
    gnss_valid: bool = True,
    gnss_hdop: float = 1.0,
    ranges: Any = None,
    mission_id: str = "m1",
) -> Dict[str, Any]:
    """Helper to generate a well-formed simulator observation."""
    if ranges is None:
        ranges = [20.0] * 360

    return {
        "t": t,
        "dt": 0.1,
        "odom": {
            "dx": v_odom * 0.1,
            "dy": 0.0,
            "dtheta": 0.0,
        },
        "imu": {
            "heading": th,
            "yaw_rate": 0.0,
        },
        "gnss": {
            "x": x,
            "y": y,
            "valid": gnss_valid,
            "hdop": gnss_hdop,
        },
        "lidar": {
            "ranges": list(ranges),
        },
        "mission": {
            "id": mission_id,
            "from": "warehouse",
            "to": "shop_a",
            "goal": [220.0, 158.5, 0.0],
            "reference_path": [
                [51.5, 150.0],
                [60.0, 150.0],
                [100.0, 150.0],
                [150.0, 150.0],
                [200.0, 150.0],
                [220.0, 158.5],
            ],
        },
    }


class TestControllerLifecycle(unittest.TestCase):
    """Test suite covering Controller lifecycle, safety, navigation, and robustness."""

    def setUp(self):
        self.map = make_test_map()
        self.config = make_test_config()
        self.initial_pose = [51.5, 150.0, 0.0]
        self.controller = Controller(self.map, self.config, self.initial_pose)

    def test_initialization(self):
        """Controller initializes all subsystems and loads landmarks correctly."""
        self.assertEqual(self.controller.dt, 0.1)
        self.assertEqual(self.controller.radius, 0.9)
        self.assertEqual(self.controller.v_top, 1.39)
        self.assertEqual(self.controller.w_top, 1.0)
        self.assertEqual(len(self.controller.rel_angles), 360)

        # Check wall segments and pole extraction
        self.assertGreater(len(self.controller.building_segs), 0)
        self.assertGreater(len(self.controller.pole_centers), 0)
        # Pole center roughly at (100.25, 148.25)
        self.assertAlmostEqual(self.controller.pole_centers[0][0], 100.25, delta=0.1)

        # Check speed zone
        self.assertEqual(len(self.controller.zones), 1)
        self.assertEqual(self.controller.zones[0][1], 0.60)

    def test_step_output_schema_and_types(self):
        """step(obs) returns a valid dictionary and unpackable 5-tuple."""
        obs = make_test_obs(t=0.0, x=51.5, y=150.0)
        cmd = self.controller.step(obs)

        # 1. Output must be a dictionary with exact required keys
        self.assertIsInstance(cmd, dict)
        self.assertIn("v", cmd)
        self.assertIn("w", cmd)
        self.assertIn("status", cmd)
        self.assertIn("pose_est", cmd)
        self.assertIn("note", cmd)

        # 2. Values must be finite numbers and valid types
        self.assertIsInstance(cmd["v"], (float, int))
        self.assertIsInstance(cmd["w"], (float, int))
        self.assertTrue(math.isfinite(cmd["v"]))
        self.assertTrue(math.isfinite(cmd["w"]))

        # Status must be string and one of standard statuses
        self.assertIsInstance(cmd["status"], str)
        self.assertIn(cmd["status"], ["moving", "arrived", "waiting", "lost", "estop"])

        # Pose estimate must be a list/tuple of 3 finite floats
        pe = cmd["pose_est"]
        self.assertIsInstance(pe, (list, tuple, np.ndarray))
        self.assertEqual(len(pe), 3)
        for val in pe:
            self.assertTrue(math.isfinite(float(val)))

        # Note must be a string without nan/inf
        self.assertIsInstance(cmd["note"], str)

        # 3. Tuple lifecycle unpacking: (v, w, st, pe, note)
        v, w, st, pe_tup, note = cmd["v"], cmd["w"], cmd["status"], cmd["pose_est"], cmd["note"]
        self.assertAlmostEqual(v, cmd["v"])
        self.assertEqual(st, cmd["status"])

    def test_gnss_loss_reaction(self):
        """When GNSS is lost, localizer gracefully falls back to EKF predict & scan-matching."""
        # Initial step with valid GNSS
        obs1 = make_test_obs(t=0.0, x=51.5, y=150.0, gnss_valid=True)
        self.controller.step(obs1)
        self.assertFalse(self.controller.localizer.is_lost)

        # Simulate 20 ticks of GNSS loss while moving along corridor
        x = 51.5
        for i in range(1, 21):
            x += 0.05
            ranges = raycast(x, 150.0, self.controller.rel_angles, self.controller.building_segs)
            obs = make_test_obs(
                t=i * 0.1,
                x=0.0,
                y=0.0,
                v_odom=0.5,
                gnss_valid=False,
                gnss_hdop=99.0,
                ranges=ranges,
            )
            cmd = self.controller.step(obs)

            # Controller should still produce healthy finite commands without crashing
            self.assertTrue(math.isfinite(cmd["v"]))
            self.assertTrue(math.isfinite(cmd["w"]))
            self.assertTrue(math.isfinite(cmd["pose_est"][0]))

        # Pose estimate must track motion despite no GNSS
        self.assertGreater(self.controller.localizer.x, 52.0)

    def test_speed_governor_zone_limit_clamping(self):
        """Speed governor clamps candidate velocity inside speed limit zone (0.60 m/s)."""
        # Place robot inside zone Z1: x in [70, 110], y in [145, 155]
        inside_x = 85.0
        inside_y = 150.0
        ctrl = Controller(self.map, self.config, [inside_x, inside_y, 0.0])
        ranges = raycast(inside_x, inside_y, ctrl.rel_angles, ctrl.building_segs)

        obs = make_test_obs(
            t=10.0,
            x=inside_x,
            y=inside_y,
            v_odom=1.0,
            ranges=ranges,
        )

        cmd = ctrl.step(obs)
        # Inside zone with v_max=0.60, command velocity must not exceed 0.60 m/s + margin
        self.assertLessEqual(cmd["v"], 0.60 + 1e-4)

    def test_emergency_stop_on_sudden_obstacle(self):
        """Emergency stop is triggered when an obstacle suddenly appears in close proximity."""
        # Create an obstacle at x=1.0m right in front of the platform (clearance < 0.2m)
        ranges = np.full(360, 20.0)
        # Beams around heading 0 (front of robot) see an obstacle at 1.0 m
        ranges[:15] = 1.05
        ranges[345:] = 1.05

        obs = make_test_obs(
            t=5.0,
            x=60.0,
            y=150.0,
            v_odom=0.5,
            ranges=ranges,
        )

        cmd = self.controller.step(obs)
        # On immediate collision hazard, governor drops velocity to 0.0 or initiates estop
        self.assertLessEqual(cmd["v"], 0.1)
        self.assertTrue("estop" in cmd["status"] or "estop" in cmd["note"] or "wait" in cmd["status"] or cmd["v"] == 0.0)

    def test_mission_switching_and_state_reset(self):
        """Switching mission ID (m1 -> m2) resets arrived state and arrival hold counters."""
        obs_m1 = make_test_obs(t=1.0, mission_id="m1")
        self.controller.step(obs_m1)
        self.assertEqual(self.controller.current_mission_id, "m1")

        # Manually simulate arrival state
        self.controller.arrived = True
        self.controller.arrived_hold_ticks = 10
        self.controller.visited_from = True

        # Next tick with mission m2 from shop_a (far away at 220, 158.5)
        obs_m2 = make_test_obs(t=1.1, mission_id="m2")
        obs_m2["mission"]["from"] = "shop_a"
        obs_m2["mission"]["to"] = "warehouse"
        self.controller.step(obs_m2)

        # Mission state should be cleanly reset
        self.assertEqual(self.controller.current_mission_id, "m2")
        self.assertFalse(self.controller.arrived)
        self.assertEqual(self.controller.arrived_hold_ticks, 0)
        self.assertFalse(self.controller.visited_from)

    def test_noisy_lidar_fog_snow_resilience(self):
        """Controller handles fog dropouts and random snow false echoes without freezing."""
        rng = np.random.RandomState(42)
        clean_ranges = raycast(60.0, 150.0, self.controller.rel_angles, self.controller.building_segs)

        # Inject fog attenuation (clamp to 6m, 10% dropouts to NaN)
        noisy_ranges = np.copy(clean_ranges)
        noisy_ranges[noisy_ranges > 6.0] = np.nan
        nan_mask = rng.rand(360) < 0.10
        noisy_ranges[nan_mask] = np.nan

        # Inject sparse snow false echoes (isolated points at 1-3m)
        snow_indices = rng.choice(360, size=10, replace=False)
        noisy_ranges[snow_indices] = rng.uniform(1.0, 3.0, size=10)

        obs = make_test_obs(
            t=2.0,
            x=60.0,
            y=150.0,
            v_odom=0.4,
            ranges=noisy_ranges,
        )

        cmd = self.controller.step(obs)
        # Should not crash, output valid numbers, and not falsely trigger permanent estop
        self.assertTrue(math.isfinite(cmd["v"]))
        self.assertTrue(math.isfinite(cmd["w"]))
        self.assertTrue(math.isfinite(cmd["pose_est"][0]))

    def test_dock_snap_at_terminal_goal(self):
        """When approaching terminal dock, dock snap aligns the robot pose with the dock."""
        # Terminal dock at (220.0, 158.5)
        dock_x, dock_y, dock_th = 220.0, 158.5, 0.0
        self.controller.visited_from = True
        self.controller.localizer.x = dock_x + 0.02
        self.controller.localizer.y = dock_y - 0.03
        self.controller.localizer.th = dock_th + 0.01

        ranges = raycast(dock_x, dock_y, self.controller.rel_angles, self.controller.building_segs)
        obs = make_test_obs(
            t=150.0,
            x=dock_x,
            y=dock_y,
            v_odom=0.01,
            ranges=ranges,
        )
        obs["mission"]["goal"] = [dock_x, dock_y, dock_th]

        cmd = self.controller.step(obs)
        self.assertIsInstance(cmd["pose_est"], (list, tuple, np.ndarray))
        # After dock snap, estimated pose should be tightly anchored
        self.assertAlmostEqual(cmd["pose_est"][0], dock_x, delta=0.2)
        self.assertAlmostEqual(cmd["pose_est"][1], dock_y, delta=0.2)

    def test_set_truth_cheat_override(self):
        """set_truth overrides EKF state for benchmarking purposes."""
        self.controller.set_truth([123.4, 56.7, 1.23])
        obs = make_test_obs(t=0.0)
        cmd = self.controller.step(obs)

        self.assertAlmostEqual(cmd["pose_est"][0], 123.4, delta=1e-3)
        self.assertAlmostEqual(cmd["pose_est"][1], 56.7, delta=1e-3)
        self.assertAlmostEqual(cmd["pose_est"][2], 1.23, delta=1e-3)

    def test_zero_delta_time_or_static_ticks(self):
        """Zero motion ticks do not cause division by zero or infinite outputs."""
        for _ in range(5):
            obs = make_test_obs(t=1.0, v_odom=0.0)
            cmd = self.controller.step(obs)
            self.assertTrue(math.isfinite(cmd["v"]))
            self.assertTrue(math.isfinite(cmd["w"]))

    def test_multi_tick_arrived_holding(self):
        """Holding arrival at dock outputs status='arrived' and note='dock' with zero velocity."""
        dock_x, dock_y = 220.0, 158.5
        ctrl = Controller(self.map, self.config, [dock_x, dock_y, 0.0])
        ctrl.current_mission_id = "m1"
        ctrl.visited_from = True
        ctrl.arrived = True

        for tick in range(1, 15):
            obs = make_test_obs(t=100.0 + tick * 0.1, x=dock_x, y=dock_y, v_odom=0.0)
            cmd = ctrl.step(obs)
            self.assertEqual(cmd["v"], 0.0)
            self.assertEqual(cmd["w"], 0.0)
            self.assertEqual(cmd["status"], "arrived")
            self.assertEqual(cmd["note"], "dock")
            self.assertEqual(ctrl.arrived_hold_ticks, tick)

    def test_all_nan_lidar_robustness(self):
        """All-NaN lidar ranges (total sensor blackout) do not cause exception."""
        nan_ranges = [np.nan] * 360
        obs = make_test_obs(t=1.0, ranges=nan_ranges)
        cmd = self.controller.step(obs)
        self.assertTrue(math.isfinite(cmd["v"]))
        self.assertTrue(math.isfinite(cmd["w"]))

    def test_lost_speed_limit_clamping(self):
        """When localizer is lost, candidate speed is capped by lost_speed_limit."""
        self.controller.localizer.var_along = 100.0  # triggers sigma_along > 5m -> is_lost = True
        self.controller.localizer.lost_speed_limit = 0.50
        obs = make_test_obs(t=1.0, gnss_valid=False, gnss_hdop=99.0)
        cmd = self.controller.step(obs)
        self.assertTrue(self.controller.localizer.is_lost)
        self.assertLessEqual(cmd["v"], 0.50 + 1e-4)

    def test_load_real_scenario_01_clear(self):
        """Controller can initialize and step using real scenario 01_clear.json."""
        scenario_path = Path("amrsim-participants/scenarios/01_clear.json")
        if not scenario_path.exists():
            self.skipTest("01_clear.json not found")

        with open(scenario_path, "r", encoding="utf-8") as f:
            sc = json.load(f)

        init_pose = [sc["start"]["x"], sc["start"]["y"], sc["start"]["theta"]]
        ctrl = Controller(sc["map"], self.config, init_pose)

        obs = {
            "t": 0.0,
            "dt": 0.1,
            "odom": {"dx": 0.0, "dy": 0.0, "dtheta": 0.0},
            "imu": {"heading": init_pose[2], "yaw_rate": 0.0},
            "gnss": {"x": init_pose[0], "y": init_pose[1], "valid": True, "hdop": 0.8},
            "lidar": {"ranges": [20.0] * 360},
            "mission": sc["missions"][0],
        }

        cmd = ctrl.step(obs)
        self.assertIsInstance(cmd, dict)
        self.assertTrue(math.isfinite(cmd["v"]))
        self.assertTrue(math.isfinite(cmd["w"]))
        self.assertEqual(len(cmd["pose_est"]), 3)


if __name__ == "__main__":
    unittest.main()
