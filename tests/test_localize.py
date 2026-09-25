"""Unit tests for team.localize module."""
import math
import unittest

import numpy as np

from team.geom import box_segs, raycast
from team.localize import Localizer


class TestLocalizer(unittest.TestCase):
    def setUp(self):
        self.init_pose = (100.0, 50.0, 0.0)
        self.loc = Localizer(self.init_pose)

    def test_initial_state(self):
        self.assertEqual(self.loc.pose, (100.0, 50.0, 0.0))
        self.assertEqual(self.loc.odom_pose, (0.0, 0.0, 0.0))
        self.assertEqual(self.loc.scale, 1.0)
        self.assertFalse(self.loc.is_lost)

    def test_predict_and_pure_odometry(self):
        # Move forward 1.0m, odom dx=1.0, dy=0.0
        self.loc.predict(
            odom_dx=1.0,
            odom_dy=0.0,
            odom_dth=0.0,
            imu_heading=0.0,
            imu_yaw_rate=0.0,
            dt=0.1,
        )
        self.assertAlmostEqual(self.loc.x, 101.0)
        self.assertAlmostEqual(self.loc.y, 50.0)
        self.assertAlmostEqual(self.loc.ox, 1.0)
        self.assertAlmostEqual(self.loc.oy, 0.0)

    def test_odometry_scale_application(self):
        loc = Localizer((0.0, 0.0, 0.0))
        loc.scale = 1.02  # measured 1.02m means true 1.00m
        loc.predict(
            odom_dx=1.02,
            odom_dy=0.0,
            odom_dth=0.0,
            imu_heading=0.0,
            imu_yaw_rate=0.0,
            dt=0.1,
        )
        self.assertAlmostEqual(loc.x, 1.0)
        self.assertAlmostEqual(loc.ox, 1.02)

    def test_heading_watchdog(self):
        loc = Localizer((0.0, 0.0, 0.0))
        # Initial step to set bias
        loc.predict(0.0, 0.0, 0.0, imu_heading=0.0, imu_yaw_rate=0.0, dt=0.1)

        # Huge sudden jump in imu_heading (> 0.05 rad) with 0 yaw_rate
        loc.predict(0.0, 0.0, 0.0, imu_heading=0.5, imu_yaw_rate=0.0, dt=0.1)
        # Should reject jump and integrate yaw_rate (0.0)
        self.assertAlmostEqual(loc.th, 0.0)

    def test_gnss_gating_and_filtering(self):
        loc = Localizer((10.0, 10.0, 0.0))
        loc.var_along = 0.5
        loc.var_cross = 0.5

        # 1. Normal measurement within 1.5m gate
        accepted = loc.update_gnss(gnss_x=10.2, gnss_y=10.1, gnss_valid=True, gnss_hdop=0.9)
        self.assertTrue(accepted)
        # Verify blended update, not raw overwrite
        self.assertNotEqual(loc.x, 10.2)
        self.assertGreater(loc.x, 10.0)
        self.assertLess(loc.x, 10.2)

        # 2. Outlier GNSS jump (6.0m)
        accepted_outlier = loc.update_gnss(gnss_x=16.0, gnss_y=10.0, gnss_valid=True, gnss_hdop=1.0)
        self.assertFalse(accepted_outlier)
        # Pose must not jump
        self.assertLess(loc.x, 10.5)

    def test_scan_matching_gauss_newton(self):
        # Setup corridor with cross and along constraints:
        # North wall at y=55.0, South wall at y=45.0, East wall at x=115.0
        # Robot true pose: (100.0, 50.0, 0.0)
        wall_north = np.array([[0.0, 55.0, 200.0, 55.0]])
        wall_south = np.array([[0.0, 45.0, 200.0, 45.0]])
        wall_east = np.array([[115.0, 45.0, 115.0, 55.0]])  # East wall at x=115 (15m ahead)
        segs = np.vstack([wall_north, wall_south, wall_east])

        # Generate synthetic lidar ranges for 360 rays from true pose (100, 50, 0)
        angles_rel = np.radians(np.arange(360))
        ranges = raycast(100.0, 50.0, angles_rel, segs)

        # Perturb localizer pose by dx=0.15m, dy=-0.12m, dth=0.03 rad
        loc = Localizer((100.15, 49.88, 0.03))
        matched = loc.update_scan(ranges, angles_rel, segs, is_fog=False)

        self.assertTrue(matched)
        self.assertAlmostEqual(loc.x, 100.0, delta=0.03)
        self.assertAlmostEqual(loc.y, 50.0, delta=0.03)
        self.assertAlmostEqual(loc.th, 0.0, delta=0.01)

    def test_dock_snap(self):
        # Dock bay: front wall at x=225, side walls at y=92.0 and y=97.0
        # Goal at (223.5, 94.5, 0.0)
        dock_segs = np.array([
            [225.0, 92.0, 225.0, 97.0],  # front wall
            [220.0, 97.0, 225.0, 97.0],  # left wall (y=97)
            [220.0, 92.0, 225.0, 92.0],  # right wall (y=92)
        ])
        goal = (223.5, 94.5, 0.0)

        # True pose at goal: front range = 1.5m, left = 2.5m, right = 2.5m
        angles_rel = np.radians(np.arange(360))
        ranges = raycast(223.5, 94.5, angles_rel, dock_segs)

        # Robot slightly off: x=223.4 (front dist 1.6m), y=94.6
        loc = Localizer((223.4, 94.6, 0.0))
        snapped = loc.dock_snap(ranges, angles_rel, goal, dock_segs)

        self.assertTrue(snapped)
        # Should adjust closer to 223.5, 94.5
        self.assertAlmostEqual(loc.x, 223.45, delta=0.03)
        self.assertAlmostEqual(loc.y, 94.55, delta=0.03)

    def test_fog_detection(self):
        loc = Localizer((0.0, 0.0, 0.0))
        # Normal ranges
        ranges = np.full(360, 10.0)
        self.assertFalse(loc.detect_fog(ranges))

        # Fog: 15% NaNs
        ranges[:60] = np.nan
        self.assertTrue(loc.detect_fog(ranges))


if __name__ == "__main__":
    unittest.main()
