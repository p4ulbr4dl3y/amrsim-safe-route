"""Unit tests for team.localize module."""
import math
import unittest

import numpy as np

from team.geom import box_segs, raycast
from team.localize import Localizer


ANGLES = np.radians(np.arange(360))


def corridor_segs() -> np.ndarray:
    """North/south walls plus pillars that also constrain the along-wall direction."""
    segs = [[80.0, 45.0, 140.0, 45.0], [80.0, 55.0, 140.0, 55.0]]
    for xs in (90.0, 100.0, 110.0, 120.0, 130.0):
        segs.append([xs, 52.0, xs, 55.0])
    return np.array(segs)


def sim_fog_ranges(clear_ranges: np.ndarray, reach: float = 6.0,
                   n_nan: int = 12) -> np.ndarray:
    """Reproduce the simulator's fog model: clamp at `reach`, drop out, then inf -> NaN."""
    r = np.array(clear_ranges, dtype=float)
    r[r > reach] = np.inf
    r[:n_nan] = np.inf
    r[~np.isfinite(r)] = np.nan
    return r


class TestLocalizer(unittest.TestCase):
    def setUp(self):
        self.init_pose = (100.0, 50.0, 0.0)
        self.loc = Localizer(self.init_pose)

    def test_initial_state(self):
        self.assertEqual(self.loc.pose, (100.0, 50.0, 0.0))
        self.assertEqual(self.loc.odom_pose, (0.0, 0.0, 0.0))
        self.assertEqual(self.loc.scale, 1.0)
        self.assertFalse(self.loc.is_lost)
        self.assertFalse(self.loc.blocked_wheels)
        self.assertEqual(self.loc.lost_speed_limit, 1.39)

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
        loc.scan_inliers = 50  # scan corroborates the pose

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

        # 3. invalid flag / coarse hdop guard / shadow are hard vetoes
        self.assertFalse(loc.update_gnss(10.0, 10.0, gnss_valid=False, gnss_hdop=0.8))
        self.assertFalse(loc.update_gnss(10.0, 10.0, gnss_valid=True, gnss_hdop=2.5))

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

    # ------------------------------------------------------------------ plan/02:59

    def test_fog_detection_simulator_style(self):
        """Fog is detected from the simulator's inf/NaN scan, held for 1 s (plan/02:59)."""
        segs = np.array([[-40.0, 12.0, 40.0, 12.0]])
        loc = Localizer((0.0, 0.0, 0.0))
        clear = raycast(0.0, 0.0, ANGLES, segs, max_range=20.0)
        self.assertGreater(int(np.isfinite(clear).sum()), 100)

        # Clear weather: many long returns -> not fog.
        self.assertFalse(loc.detect_fog(clear, expected_ranges=clear))

        # Fog: everything beyond the 6 m reach becomes inf/NaN, while the map still
        # expects a wall at ~12 m.
        foggy = sim_fog_ranges(clear)
        self.assertTrue(loc.detect_fog(foggy, expected_ranges=clear))

        # A single clear tick must not toggle the mode out (1 s hysteresis).
        for _ in range(9):
            self.assertTrue(loc.detect_fog(foggy, expected_ranges=clear))
        self.assertTrue(loc.detect_fog(clear, expected_ranges=clear))
        for _ in range(8):
            self.assertTrue(loc.detect_fog(clear, expected_ranges=clear))
        self.assertFalse(loc.detect_fog(clear, expected_ranges=clear))

    def test_fog_detection_without_map(self):
        """Without a map the NaN share alone is the fallback detector (plan/02:59)."""
        loc = Localizer((0.0, 0.0, 0.0))
        self.assertFalse(loc.detect_fog(np.full(360, 10.0)))
        self.assertTrue(loc.detect_fog(sim_fog_ranges(np.full(360, 10.0))))

    def test_fog_uses_variance_not_long_beams(self):
        """In fog a beam beyond 5.5 m is not an inlier (plan/02:55-59)."""
        segs = np.array([[0.0, 5.0, 40.0, 5.0]])
        loc = Localizer((0.0, 0.0, 0.0))
        clear = raycast(0.0, 0.0, ANGLES, segs, max_range=20.0)
        loc.var_cross = 1.0
        before = loc.var_cross
        # Keep a few spurious long returns: they must not become inliers in fog.
        foggy = sim_fog_ranges(clear, reach=4.0)
        foggy[10:20] = 8.0
        loc.update_scan(foggy, ANGLES, segs, is_fog=True)
        self.assertGreaterEqual(loc.var_cross, before * 0.5)

    # ------------------------------------------------------------------ plan/02:99

    def test_odometry_scale_calibration(self):
        """1.03 odometry error converges over 25 m and is then frozen (plan/02:99-108)."""
        segs = corridor_segs()
        loc = Localizer((100.0, 50.0, 0.0))
        true_x = 100.0
        locked_at = None
        for k in range(420):
            loc.predict(0.103, 0.0, 0.0, 0.0, 0.0, 0.1)  # odom over-reports by 3%
            true_x += 0.1
            ranges = raycast(true_x, 50.0, ANGLES, segs, max_range=20.0)
            loc.update_scan(ranges, ANGLES, segs, is_fog=False)
            if loc.scale_locked:
                locked_at = k
                break

        self.assertIsNotNone(locked_at, "scale was never calibrated")
        self.assertGreaterEqual(locked_at * 0.1, 24.0)
        self.assertAlmostEqual(loc.scale, 1.03, delta=0.01)
        # A measurement in [0.99, 1.01] would mean the calibration did nothing.
        self.assertGreater(loc.scale, 1.01)

        # Frozen: further travel must not move it.
        frozen = loc.scale
        for _ in range(60):
            loc.predict(0.103, 0.0, 0.0, 0.0, 0.0, 0.1)
            true_x += 0.1
            ranges = raycast(true_x, 50.0, ANGLES, segs, max_range=20.0)
            loc.update_scan(ranges, ANGLES, segs, is_fog=False)
        self.assertEqual(loc.scale, frozen)

    def test_scale_ignored_before_calibration(self):
        loc = Localizer((0.0, 0.0, 0.0))
        loc.predict(0.1, 0.0, 0.0, 0.0, 0.0, 0.1)
        # Before the lock the scale is 1, so the odometry step is taken as is.
        self.assertAlmostEqual(loc.x, 0.1)
        self.assertFalse(loc.scale_locked)

    # ------------------------------------------------------------------ plan/02:133

    def test_variance_axes_at_side_wall(self):
        """A side wall collapses sigma_cross but must not shrink sigma_along (plan/02:37)."""
        segs = corridor_segs()
        loc = Localizer((100.0, 50.0, 0.0))
        loc.var_along = 1.0
        loc.var_cross = 1.0
        loc.predict(0.05, 0.0, 0.0, 0.0, 0.0, 0.1)
        along_before = loc.var_along
        cross_before = loc.var_cross

        ranges = raycast(100.05, 50.0, ANGLES, segs, max_range=20.0)
        self.assertTrue(loc.update_scan(ranges, ANGLES, segs, is_fog=False))

        self.assertLess(loc.var_cross, 0.1 * cross_before)
        self.assertGreater(loc.var_along, 0.9 * along_before)

    def test_lost_status_tiers_and_recovery(self):
        """Lost tiers and the grid-search recovery (plan/02:133-147)."""
        # A room constrains both axes, so a sharp grid-search peak exists.
        segs = np.array([
            [90.0, 44.0, 112.0, 44.0],
            [112.0, 44.0, 112.0, 56.0],
            [112.0, 56.0, 90.0, 56.0],
            [90.0, 56.0, 90.0, 44.0],
        ])
        loc = Localizer((98.0, 50.0, 0.0))

        # Narrow across, wide along: keep driving but catch a corner.
        loc.var_along = 3.0 ** 2
        loc.var_cross = 0.1 ** 2
        loc._check_lost_status()
        self.assertFalse(loc.is_lost)
        self.assertLessEqual(loc.lost_speed_limit, 0.6)

        # sigma_cross > 0.4 -> speed limit, still not lost.
        loc.var_along = 1.0
        loc.var_cross = 0.5 ** 2
        loc._check_lost_status()
        self.assertFalse(loc.is_lost)
        self.assertLessEqual(loc.lost_speed_limit, 0.4)

        # sigma_cross > 0.8 -> lost, stop.
        loc.var_cross = 0.9 ** 2
        loc._check_lost_status()
        self.assertTrue(loc.is_lost)
        self.assertEqual(loc.lost_speed_limit, 0.0)

        # sigma_along > 5 -> lost as well.
        loc.var_cross = 0.1 ** 2
        loc.var_along = 5.5 ** 2
        loc._check_lost_status()
        self.assertTrue(loc.is_lost)

        # Search runs only while stopped and lost, and shifts the hypothesis to the peak.
        ranges = raycast(98.0, 50.0, ANGLES, segs, max_range=19.0)
        loc.x, loc.y, loc.th = 99.0, 50.5, 0.04   # drift the hypothesis away
        self.assertFalse(loc.try_recover(ranges, ANGLES, segs, stopped=False))
        self.assertTrue(loc.is_lost)
        loc.var_along = 0.1 ** 2
        loc.var_cross = 0.1 ** 2
        self.assertTrue(loc.try_recover(ranges, ANGLES, segs, stopped=True))
        self.assertFalse(loc.is_lost)
        self.assertEqual(loc.lost_speed_limit, 1.39)
        self.assertAlmostEqual(loc.x, 98.0, delta=0.5)
        self.assertAlmostEqual(loc.y, 50.0, delta=0.5)

    def test_lost_from_low_inliers(self):
        """Inliers < 15 outside fog for more than 1 s -> lost (plan/02:141)."""
        loc = Localizer((100.0, 50.0, 0.0))
        segs = np.array([[0.0, 0.0, 1.0, 0.0]])  # almost nothing to see
        ranges = np.full(360, np.nan)
        for _ in range(11):
            loc.update_scan(ranges, ANGLES, segs, is_fog=False)
        self.assertTrue(loc.is_lost)

    # ------------------------------------------------------------------ plan/02:63

    def test_longitudinal_landmark_moves_along_wall_only(self):
        """A mapped wall end corrects the weak tangential axis only (plan/02:63-81)."""
        # Short wall: its end is 1.8 m from the robot, so it is a usable landmark.
        short = np.array([[0.0, 0.0, 3.0, 0.0]])
        loc = Localizer((1.5, 1.15, 0.0), building_segs=short)
        self.assertEqual(len(loc.landmarks), 2)
        ranges = raycast(1.9, 1.0, ANGLES, short, max_range=20.0)
        self.assertTrue(loc.update_scan(ranges, ANGLES, short, is_fog=False))
        # Longitudinal error (0.4 m along the wall) is corrected, the normal is not smeared.
        self.assertLess(abs(loc.x - 1.9), 0.1)
        self.assertLess(abs(loc.y - 1.0), 0.05)

        # Long wall without an end in reach: the along-wall error cannot be observed.
        long_wall = np.array([[-50.0, 0.0, 50.0, 0.0]])
        loc2 = Localizer((1.5, 1.15, 0.0), building_segs=long_wall)
        ranges2 = raycast(1.9, 1.0, ANGLES, long_wall, max_range=20.0)
        self.assertTrue(loc2.update_scan(ranges2, ANGLES, long_wall, is_fog=False))
        self.assertGreater(abs(loc2.x - 1.9), 0.3)   # still unobservable
        self.assertLess(abs(loc2.y - 1.0), 0.05)     # normal held by the facade

    # ------------------------------------------------------------------ plan/02:149

    def test_blocked_wheels(self):
        """Odometry moves, the walls do not -> the tick is not integrated (plan/02:149)."""
        segs = corridor_segs()
        loc = Localizer((100.0, 50.0, 0.0))
        ranges = raycast(100.0, 50.0, ANGLES, segs, max_range=20.0)

        blocked_seen = False
        for _ in range(6):
            loc.predict(0.06, 0.0, 0.0, 0.0, 0.0, 0.1)  # wheels turn
            loc.update_scan(ranges, ANGLES, segs, is_fog=False)  # walls stay put
            blocked_seen = blocked_seen or loc.blocked_wheels
            # The stationary odometry tick must not be integrated.
            self.assertAlmostEqual(loc.x, 100.0, delta=0.02)
            self.assertAlmostEqual(loc.y, 50.0, delta=0.02)
        self.assertTrue(blocked_seen)

    def test_blocked_wheels_not_raised_when_moving(self):
        """Real motion must not be reported as a wheel block (plan/02:157)."""
        segs = corridor_segs()
        loc = Localizer((100.0, 50.0, 0.0))
        true_x = 100.0
        for _ in range(30):
            loc.predict(0.1, 0.0, 0.0, 0.0, 0.0, 0.1)
            true_x += 0.1
            ranges = raycast(true_x, 50.0, ANGLES, segs, max_range=20.0)
            loc.update_scan(ranges, ANGLES, segs, is_fog=False)
            self.assertFalse(loc.blocked_wheels)


if __name__ == "__main__":
    unittest.main()
