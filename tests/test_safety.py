"""Unit tests for team.safety module."""
import math
import unittest

import numpy as np

from team.perceive import Track
from team.safety import (
    R_PEDESTRIAN,
    R_PLATFORM,
    SafetyGovernor,
    calculate_clearance,
    determine_status,
    predict_ttc_clearance,
)


class TestSafety(unittest.TestCase):
    def setUp(self):
        self.gov = SafetyGovernor(v_top=1.39, dt=0.1)

    def test_clearance_calculation(self):
        # Point at x=3.0, y=0.0
        pts = np.array([[3.0, 0.0]])

        # 1. Pedestrian / unknown: subtract R_PLATFORM (0.9) and R_PEDESTRIAN (0.3)
        cl_ped = calculate_clearance(pts, is_pedestrian=True)
        self.assertAlmostEqual(cl_ped, 3.0 - 0.9 - 0.3)  # 1.8 m

        # 2. Wall / static object: subtract only R_PLATFORM (0.9)
        cl_wall = calculate_clearance(pts, is_pedestrian=False)
        self.assertAlmostEqual(cl_wall, 3.0 - 0.9)  # 2.1 m

    def test_predictive_ttc(self):
        # AMR at (0, 0) moving at 1.0 m/s towards pedestrian at x=2.5m, y=0.0m
        # Initial clearance = 2.5 - 1.2 = 1.3 m (> 0.8m)
        tr = Track(track_id=1, ox=2.5, oy=0.0)
        tr.pts = np.array([[2.5, 0.0]])
        tr.class_label = "pedestrian"
        tr.dyn = True
        tr.vx_odom = 0.0  # pedestrian static, platform moving at 1.0 m/s

        min_cl, min_t = predict_ttc_clearance(
            track=tr,
            v_platform=1.0,
            oth=0.0,
            horizon_s=2.0,
            dt_step=0.2,
        )
        # At t=1.0s: relative x = 2.5 - 1.0*1.0 = 1.5m -> clearance = 1.5 - 1.2 = 0.3m (< 0.8m)
        self.assertLess(min_cl, 0.8)
        self.assertAlmostEqual(min_t, 2.0)  # decreases monotonically

    def test_speed_limit_person_near(self):
        # 1. Pedestrian at clearance = 2.5 m (< 3.3 m)
        # Expected: safe speed capped at <= 0.22 m/s, status 'moving' while v_odom > 0.05
        tr = Track(track_id=1, ox=3.7, oy=0.0)
        tr.pts = np.array([[3.7, 0.0]])  # dist 3.7 -> clearance 3.7 - 1.2 = 2.5 m
        tr.class_label = "pedestrian"
        tr.dyn = True

        v_safe, w_safe, status, note = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.3,
            w_odom=0.0,
            pose=(10.0, 10.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertLessEqual(v_safe, 0.25)
        self.assertGreater(v_safe, 0.0)
        self.assertEqual(status, "moving")
        self.assertIn("slow_person", note)

        # 2. Pedestrian close: clearance = 0.6 m (< 0.8 m)
        # Expected: stop (v_safe = 0.0)
        tr_close = Track(track_id=2, ox=1.8, oy=0.0)
        tr_close.pts = np.array([[1.8, 0.0]])  # dist 1.8 -> clearance 0.6 m
        tr_close.class_label = "pedestrian"

        v_stop, _, _, note_stop = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.3,
            w_odom=0.0,
            pose=(10.0, 10.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr_close],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertEqual(v_stop, 0.0)
        self.assertIn("stop_person", note_stop)

    def test_swept_corridor_braking_three_rays(self):
        # 3 adjacent rays in swept corridor inside braking reach
        # Robot speed 1.0 m/s -> braking reach ~ 0.9 + 1.0^2/(2*1.2) + 0.1 + 0.25 ≈ 1.67 m
        ranges = np.full(360, 20.0)
        # Put 3 rays in front: beams 359, 0, 1 at 1.2 m
        ranges[359] = 1.2
        ranges[0] = 1.2
        ranges[1] = 1.2

        v_safe, w_safe, _, note = self.gov.evaluate(
            v_cand=1.0,
            w_cand=0.2,
            v_odom=1.0,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=ranges,
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertEqual(v_safe, 0.0)
        self.assertEqual(w_safe, 0.0)  # corridor blocked -> zero out rotation
        self.assertIn("stop_corridor", note)

    def test_fog_speed_limits(self):
        # 1. Fog with unexplained cluster ahead at 4.7 m (< 5.0 m, clearance 3.5 m > 3.3 m)
        tr = Track(track_id=1, ox=4.7, oy=0.0)
        tr.pts = np.array([[4.7, 0.0]])
        tr.class_label = "unknown"

        v_fog_cluster, _, _, note = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.3,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 6.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
            is_fog=True,
        )
        self.assertLessEqual(v_fog_cluster, 0.35)
        self.assertIn("fog_cluster", note)

        # 2. Fog and clear ahead (no clusters)
        v_fog_clear, _, _, note_clear = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.8,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=np.full(360, 6.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
            is_fog=True,
        )
        self.assertAlmostEqual(v_fog_clear, 0.90, delta=0.01)
        self.assertIn("fog_clear", note_clear)

    def test_speed_limit_zone_and_lookahead(self):
        # Speed limit zone: v_max = 0.8 m/s -> commanded v <= 0.8 - 0.05 = 0.75 m/s
        zone_poly = [[50.0, 0.0], [100.0, 0.0], [100.0, 50.0], [50.0, 50.0]]
        zones = [(zone_poly, 0.8)]

        # 1. AMR inside zone at (60, 20)
        v_in_zone, _, _, note = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.5,
            w_odom=0.0,
            pose=(60.0, 20.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=zones,
        )
        self.assertLessEqual(v_in_zone, 0.75)
        self.assertIn("zone v=0.75", note)

        # 2. AMR 2.0m before zone facing zone: at (48, 20, th=0), lookahead at (51, 20) is inside zone!
        v_lookahead, _, _, _ = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.5,
            w_odom=0.0,
            pose=(48.0, 20.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=zones,
        )
        self.assertLessEqual(v_lookahead, 0.75)

    def test_status_determination_scoring_rules(self):
        # 1. While moving at v_odom = 0.2 m/s, status MUST be 'moving' to avoid status_mismatch
        st_moving = determine_status(v_odom=0.2, is_stopped=True)
        self.assertEqual(st_moving, "moving")

        # 2. Stopped at v_odom = 0.0 m/s with obstacle -> 'waiting'
        st_waiting = determine_status(v_odom=0.0, is_stopped=True)
        self.assertEqual(st_waiting, "waiting")

        # 3. Arrived at goal -> 'arrived'
        st_arrived = determine_status(v_odom=0.0, is_arrived=True)
        self.assertEqual(st_arrived, "arrived")

        # 4. Optional allow_slowed mode
        st_slowed = determine_status(v_odom=0.2, is_slowed=True, allow_slowed=True)
        self.assertEqual(st_slowed, "slowed")

    def test_rotation_w_permitted_beside_pedestrian(self):
        # Pedestrian at side: x=0, y=2.0 (outside front corridor)
        tr = Track(track_id=1, ox=0.0, oy=2.0)
        tr.pts = np.array([[0.0, 2.0]])
        tr.class_label = "pedestrian"

        v_safe, w_safe, _, _ = self.gov.evaluate(
            v_cand=0.0,
            w_cand=0.5,  # rotate on spot
            v_odom=0.0,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        # Rotation on spot must NOT be zeroed out
        self.assertAlmostEqual(w_safe, 0.5)


if __name__ == "__main__":
    unittest.main()
