"""Controller-level tests for the lost-orientation speed cap (plan/02:133-147).

The plan defines four tiers of pose uncertainty and their commanded speed:

    | sigma_cross > 0.4 m or sigma_theta > 5 deg | v <= 0.4            |
    | sigma_cross > 0.8 m or sigma_theta > 10 deg| stop, status `lost` |
    | sigma_along > 2 m, cross narrow            | v <= 0.6, keep going|
    | healthy                                    | v unchanged (1.39)  |

`team/localize.py::_check_lost_status` computes all four and exports them through
`localizer.lost_speed_limit` (1.39 / 0.6 / 0.4 / 0.0).  These tests drive the real
`Controller.step()` with synthetic observations on a synthetic straight corridor
(stdlib + numpy only, no simulator) and assert that the *exported* tier actually
reaches the command.  The tier is produced by the production
`_check_lost_status()` -- the test only sets the variances it reads immediately
before calling it -- so the assertion covers the whole chain:

    sigma -> lost_speed_limit -> Controller command v

This is the regression guard for the bug where the clamp was applied only inside
`if self.localizer.is_lost:`: the `lost` branch always exports 0.0, which made the
0.6 and 0.4 tiers dead code.
"""
import math
import unittest

import numpy as np

from team.controller import Controller
from team.geom import raycast


# A 120 m straight corridor: south wall at y = 0, north wall at y = 4.  The
# mission sends the platform from x = 5 to x = 110 along the centre line, so the
# route follower asks for a large candidate speed and the safety governor has no
# obstacle to brake for.
SYNTH_MAP = {
    "frame": "synthetic corridor",
    "bounds": [0.0, 0.0, 120.0, 8.0],
    "drivable": [[[0.0, 0.0], [120.0, 0.0], [120.0, 4.0], [0.0, 4.0]]],
    "buildings": [
        {"id": "S", "polygon": [[0.0, -0.5], [120.0, -0.5], [120.0, 0.0], [0.0, 0.0]]},
        {"id": "N", "polygon": [[0.0, 4.0], [120.0, 4.0], [120.0, 4.5], [0.0, 4.5]]},
    ],
    "points": {
        "a": {"x": 5.0, "y": 2.0, "heading": 0.0, "tol": 0.2},
        "b": {"x": 110.0, "y": 2.0, "heading": 0.0, "tol": 0.2},
    },
    "zones": [],
    "gates": [],
    "crossing": [],
}

SYNTH_CONFIG = {
    "dt": 0.1,
    "robot": {"v_max": 1.39, "w_max": 0.8},
    "lidar": {"beams": 360, "angle_min_deg": 0.0, "angle_increment_deg": 1.0,
              "max_range": 20.0},
}

SYNTH_MISSION = {
    "id": "m1", "index": 0, "count": 1,
    "from": "a", "to": "b",
    "goal": [110.0, 2.0, 0.0], "tol": 0.2,
    "t_start": 0.0, "deadline_s": 300.0,
    "reference_path": [[5.0, 2.0], [110.0, 2.0]],
}

START = (5.0, 2.0, 0.0)


def make_obs(ctrl, t=0.0):
    """One clean observation for the standing platform at the start pose."""
    ranges = raycast(START[0], START[1], START[2] + ctrl.rel_angles,
                     ctrl.building_segs, max_range=20.0)
    ranges = np.where(np.isfinite(ranges), ranges, np.nan)
    return {
        "t": t,
        "lidar": {"ranges": ranges},
        "odom": {"dx": 0.0, "dy": 0.0, "dtheta": 0.0},
        "imu": {"heading": START[2], "yaw_rate": 0.0},
        "gnss": {"valid": False},
        "mission": SYNTH_MISSION,
    }


def drive_with_uncertainty(var_along, var_cross, var_theta=0.01 ** 2, ticks=3):
    """Run `ticks` controller steps with the requested pose variances.

    The wrapper sets the variances right before the production
    `Localizer._check_lost_status()` runs, so the exported `lost_speed_limit` is
    the genuine tier for those sigmas.  Returns (command, localizer).
    """
    ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
    loc = ctrl.localizer
    original = loc._check_lost_status
    forced = {
        "var_along": var_along,
        "var_cross": var_cross,
        "var_th": var_theta,
        # A narrow along axis must not be mistaken for a stale wide bound.
        "_unconfirmed_dist": 0.0,
    }

    def tiered_check():
        for name, value in forced.items():
            setattr(loc, name, value)
        original()

    loc._check_lost_status = tiered_check

    cmd = None
    for i in range(ticks):
        cmd = ctrl.step(make_obs(ctrl, t=0.1 * i))
    return cmd, loc


class TestLostSpeedCap(unittest.TestCase):
    """The exported lost tier must reach the command on every tick."""

    def test_sigma_along_over_2m_caps_to_0_6(self):
        """sigma_along > 2 m (cross narrow) -> v <= 0.6 while still driving."""
        cmd, loc = drive_with_uncertainty(var_along=2.5 ** 2, var_cross=0.1 ** 2)
        self.assertFalse(loc.is_lost, "a wide along bound with a narrow cross axis is not lost")
        self.assertGreater(loc.sigma_along, 2.0)
        self.assertAlmostEqual(loc.lost_speed_limit, 0.6)
        self.assertAlmostEqual(cmd["v"], 0.6)
        self.assertGreater(cmd["v"], 0.0, "the platform must keep driving, not stop")
        self.assertNotEqual(cmd["status"], "lost")

    def test_sigma_cross_over_0_4m_caps_to_0_4(self):
        """sigma_cross > 0.4 m -> v <= 0.4, still not lost."""
        cmd, loc = drive_with_uncertainty(var_along=0.5 ** 2, var_cross=0.5 ** 2)
        self.assertFalse(loc.is_lost)
        self.assertGreater(loc.sigma_cross, 0.4)
        self.assertAlmostEqual(loc.lost_speed_limit, 0.4)
        self.assertAlmostEqual(cmd["v"], 0.4)
        self.assertGreater(cmd["v"], 0.0)

    def test_sigma_theta_over_5deg_caps_to_0_4(self):
        """sigma_theta > 5 deg also selects the 0.4 tier (plan/02:137)."""
        cmd, loc = drive_with_uncertainty(
            var_along=0.5 ** 2, var_cross=0.1 ** 2, var_theta=math.radians(6.0) ** 2)
        self.assertFalse(loc.is_lost)
        self.assertGreater(math.degrees(loc.sigma_th), 5.0)
        self.assertAlmostEqual(loc.lost_speed_limit, 0.4)
        self.assertAlmostEqual(cmd["v"], 0.4)

    def test_sigma_cross_over_0_8m_stops_and_reports_lost(self):
        """sigma_cross > 0.8 m -> stop, status `lost` (existing behaviour preserved)."""
        cmd, loc = drive_with_uncertainty(var_along=0.5 ** 2, var_cross=0.9 ** 2)
        self.assertTrue(loc.is_lost)
        self.assertEqual(loc.lost_speed_limit, 0.0)
        self.assertEqual(cmd["v"], 0.0)
        self.assertEqual(cmd["status"], "lost")
        self.assertIn("lost", cmd["note"])

    def test_healthy_pose_leaves_the_command_untouched(self):
        """The 1.39 healthy export is a no-op: the route candidate survives."""
        cmd, loc = drive_with_uncertainty(var_along=0.1 ** 2, var_cross=0.1 ** 2)
        self.assertFalse(loc.is_lost)
        self.assertEqual(loc.lost_speed_limit, 1.39)
        self.assertGreater(cmd["v"], 1.0)

    def test_cap_never_raises_a_slower_candidate(self):
        """min() semantics: a tier above the candidate must not speed it up."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        loc = ctrl.localizer
        original = loc._check_lost_status

        def healthy_check():
            loc.var_along = 0.1 ** 2
            loc.var_cross = 0.1 ** 2
            loc.var_th = 0.01 ** 2
            loc._unconfirmed_dist = 0.0
            original()

        loc._check_lost_status = healthy_check
        ctrl.route.step = lambda **kwargs: {
            "v": 0.2, "w": 0.0, "remaining_dist": 50.0,
            "arrived": False, "status": "moving", "note": "",
        }
        cmd = ctrl.step(make_obs(ctrl, t=0.0))
        self.assertLessEqual(cmd["v"], 0.2 + 1e-9)


if __name__ == "__main__":
    unittest.main()
