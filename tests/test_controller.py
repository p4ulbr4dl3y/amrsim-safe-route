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

from team_dreamteam_4_0.controller import Controller
from team_dreamteam_4_0.geom import raycast

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
    "lidar": {"beams": 360, "angle_min_deg": 0.0, "angle_increment_deg": 1.0, "max_range": 20.0},
}

SYNTH_MISSION = {
    "id": "m1",
    "index": 0,
    "count": 1,
    "from": "a",
    "to": "b",
    "goal": [110.0, 2.0, 0.0],
    "tol": 0.2,
    "t_start": 0.0,
    "deadline_s": 300.0,
    "reference_path": [[5.0, 2.0], [110.0, 2.0]],
}

START = (5.0, 2.0, 0.0)


def make_obs(ctrl, t=0.0):
    """One clean observation for the standing platform at the start pose."""
    ranges = raycast(
        START[0], START[1], START[2] + ctrl.rel_angles, ctrl.building_segs, max_range=20.0
    )
    ranges = np.where(np.isfinite(ranges), ranges, np.nan)
    return {
        "t": t,
        "lidar": {"ranges": ranges},
        "odom": {"dx": 0.0, "dy": 0.0, "dtheta": 0.0},
        "imu": {"heading": START[2], "yaw_rate": 0.0},
        "gnss": {"valid": False},
        "mission": SYNTH_MISSION,
    }


def drive_with_uncertainty(var_along, var_cross, var_theta=0.01**2, ticks=3):
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
        cmd, loc = drive_with_uncertainty(var_along=2.5**2, var_cross=0.1**2)
        self.assertFalse(loc.is_lost, "a wide along bound with a narrow cross axis is not lost")
        self.assertGreater(loc.sigma_along, 2.0)
        self.assertAlmostEqual(loc.lost_speed_limit, 0.6)
        self.assertAlmostEqual(cmd["v"], 0.6)
        self.assertGreater(cmd["v"], 0.0, "the platform must keep driving, not stop")
        self.assertNotEqual(cmd["status"], "lost")

    def test_sigma_cross_over_0_4m_caps_to_0_4(self):
        """sigma_cross > 0.4 m -> v <= 0.4, still not lost."""
        cmd, loc = drive_with_uncertainty(var_along=0.5**2, var_cross=0.5**2)
        self.assertFalse(loc.is_lost)
        self.assertGreater(loc.sigma_cross, 0.4)
        self.assertAlmostEqual(loc.lost_speed_limit, 0.4)
        self.assertAlmostEqual(cmd["v"], 0.4)
        self.assertGreater(cmd["v"], 0.0)

    def test_sigma_theta_over_5deg_caps_to_0_4(self):
        """sigma_theta > 5 deg also selects the 0.4 tier (plan/02:137)."""
        cmd, loc = drive_with_uncertainty(
            var_along=0.5**2, var_cross=0.1**2, var_theta=math.radians(6.0) ** 2
        )
        self.assertFalse(loc.is_lost)
        self.assertGreater(math.degrees(loc.sigma_th), 5.0)
        self.assertAlmostEqual(loc.lost_speed_limit, 0.4)
        self.assertAlmostEqual(cmd["v"], 0.4)

    def test_sigma_cross_over_0_8m_stops_and_reports_lost(self):
        """sigma_cross > 0.8 m -> stop, status `lost` (existing behaviour preserved)."""
        cmd, loc = drive_with_uncertainty(var_along=0.5**2, var_cross=0.9**2)
        self.assertTrue(loc.is_lost)
        self.assertEqual(loc.lost_speed_limit, 0.0)
        self.assertEqual(cmd["v"], 0.0)
        self.assertEqual(cmd["status"], "lost")
        self.assertIn("lost", cmd["note"])

    def test_healthy_pose_leaves_the_command_untouched(self):
        """The 1.39 healthy export is a no-op: the route candidate survives."""
        cmd, loc = drive_with_uncertainty(var_along=0.1**2, var_cross=0.1**2)
        self.assertFalse(loc.is_lost)
        self.assertEqual(loc.lost_speed_limit, 1.39)
        self.assertGreater(cmd["v"], 1.0)

    def test_cap_never_raises_a_slower_candidate(self):
        """min() semantics: a tier above the candidate must not speed it up."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        loc = ctrl.localizer
        original = loc._check_lost_status

        def healthy_check():
            loc.var_along = 0.1**2
            loc.var_cross = 0.1**2
            loc.var_th = 0.01**2
            loc._unconfirmed_dist = 0.0
            original()

        loc._check_lost_status = healthy_check
        ctrl.route.step = lambda **kwargs: {
            "v": 0.2,
            "w": 0.0,
            "remaining_dist": 50.0,
            "arrived": False,
            "status": "moving",
            "note": "",
        }
        cmd = ctrl.step(make_obs(ctrl, t=0.0))
        self.assertLessEqual(cmd["v"], 0.2 + 1e-9)


class TestControllerUnits(unittest.TestCase):
    """Targeted coverage for Controller branches."""

    def test_extract_pole_centers_edge_cases(self):
        """_extract_pole_centers handles various valid and invalid building inputs."""
        # Empty/None
        self.assertEqual(Controller._extract_pole_centers(None).shape, (0, 2))
        self.assertEqual(Controller._extract_pole_centers([]).shape, (0, 2))

        # Buildings with invalid/short poly or bad shapes
        b_invalid = [
            {"polygon": None},
            {"polygon": [[0, 0], [1, 1]]},  # len < 3
            {"polygon": "not a list"},  # ValueError/TypeError
            {"polygon": [[[0, 0], [1, 1], [1, 0]]]},  # ndim == 3 != 2
            {"polygon": [[0], [1], [2]]},  # shape[1] < 2
            {"id": "no polygon key"},
        ]
        res = Controller._extract_pole_centers(b_invalid)
        self.assertEqual(res.shape, (0, 2))

        # A small polygon (pole): sides < 1.0 m
        pole = [[10.0, 10.0], [10.2, 10.0], [10.2, 10.2], [10.0, 10.2]]
        # A large building: sides >= 1.0 m
        large = [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]
        res = Controller._extract_pole_centers([{"polygon": pole}, {"polygon": large}])
        self.assertEqual(res.shape, (1, 2))
        self.assertAlmostEqual(res[0, 0], 10.1)
        self.assertAlmostEqual(res[0, 1], 10.1)

    def test_track_world_xy(self):
        """_track_world_xy converts odom-frame track to world coordinates."""

        class DummyTrack:
            ox = 10.0
            oy = 5.0

        trk = DummyTrack()
        pose = (20.0, 30.0, math.pi / 2)
        odom_pose = (5.0, 5.0, 0.0)
        # dx_o = 5, dy_o = 0. In robot frame: rx = 5, ry = 0.
        # In world frame with pose (20, 30, pi/2): cos=0, sin=1
        # wx = 20 + 0*5 - 1*0 = 20
        # wy = 30 + 1*5 + 0*0 = 35
        wx, wy = Controller._track_world_xy(trk, pose, odom_pose)
        self.assertAlmostEqual(wx, 20.0)
        self.assertAlmostEqual(wy, 35.0)

    def test_truth_pose_override(self):
        """set_truth overrides pose and zeroes variances during step."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        ctrl.set_truth([42.0, 24.0, 1.23])
        obs = make_obs(ctrl)
        res = ctrl.step(obs)
        self.assertAlmostEqual(res["pose_est"][0], 42.0)
        self.assertAlmostEqual(res["pose_est"][1], 24.0)
        self.assertAlmostEqual(res["pose_est"][2], 1.23)
        self.assertEqual(ctrl.localizer.var_along, 0.0)
        self.assertEqual(ctrl.localizer.var_cross, 0.0)

    def test_mission_from_formats_and_arrival(self):
        """Mission 'from' as tuple/list and arrival state machine."""
        map_with_zones = dict(SYNTH_MAP)
        map_with_zones["zones"] = [
            {"type": "speed_limit", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]], "v_max": 0.5}
        ]
        ctrl = Controller(map_with_zones, SYNTH_CONFIG, [5.0, 2.0, 0.0])

        # Step 1: mission with 'from' as list [5.0, 2.0]
        mission = dict(SYNTH_MISSION)
        mission["from"] = [5.0, 2.0]
        mission["goal"] = [5.05, 2.0, 0.0]
        obs = make_obs(ctrl)
        obs["mission"] = mission
        ctrl.step(obs)
        self.assertTrue(ctrl.visited_from)

        # Arrive: close to goal, v_odom < 0.04
        ctrl.localizer.x = 5.05
        ctrl.localizer.y = 2.0
        ctrl.route.active_path = np.array([[5.0, 2.0], [5.05, 2.0]])
        res = ctrl.step(obs)
        self.assertEqual(res["status"], "arrived")
        self.assertTrue(ctrl.arrived)

        # Subsequent step when already arrived returns dock immediately
        res2 = ctrl.step(obs)
        self.assertEqual(res2["status"], "arrived")
        self.assertEqual(res2["note"], "dock")

    def test_perception_removed_segments_and_obstacles(self):
        """Removed segments mask and confirmed tracks feeding static obstacles."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))

        # Add removed segment id
        ctrl.perception.removed_segment_ids.add(0)

        # Add mock tracks
        class MockPedTrack:
            is_pedestrian = True
            is_unknown = False
            is_static_object = False
            is_wall = False
            ox, oy = 10.0, 2.0
            length = 0.5
            seen = [1, 1]
            pts = np.array([[10.0, 2.0]])
            vx_odom = 0.0
            vy_odom = 0.0

        class MockStaticTrack1:
            is_pedestrian = False
            is_unknown = False
            is_static_object = True
            is_wall = False
            ox, oy = 15.0, 2.0
            length = 1.0
            seen = [1, 1]
            pts = np.array([[15.0, 2.0]])
            vx_odom = 0.0
            vy_odom = 0.0

        class MockStaticTrack2:
            is_pedestrian = False
            is_unknown = False
            is_static_object = False  # Not added to static_obs initially!
            is_wall = False
            ox, oy = 25.0, 2.0
            length = 1.0
            seen = [1, 1]
            pts = np.array([[25.0, 2.0]])
            vx_odom = 0.0
            vy_odom = 0.0

        ctrl._active_tracks = lambda: [MockPedTrack(), MockStaticTrack1(), MockStaticTrack2()]

        # Compute world xy for MockStaticTrack1 and MockStaticTrack2
        pose = ctrl.localizer.pose
        odom_pose = ctrl.localizer.odom_pose
        w1_x, w1_y = Controller._track_world_xy(MockStaticTrack1(), pose, odom_pose)
        w2_x, w2_y = Controller._track_world_xy(MockStaticTrack2(), pose, odom_pose)

        # get_extra_obstacles returns:
        # 1. obstacle far from confirmed_xy -> skipped (line 295)
        # 2. obstacle matching w1 (already in static_obs) -> skipped (line 297)
        # 3. obstacle matching w2 (not in static_obs) -> appended (line 298)
        ctrl.perception.get_extra_obstacles = lambda: [
            (99.0, 99.0, 0.5),
            (w1_x, w1_y, 0.5),
            (w2_x, w2_y, 0.5),
        ]

        obs = make_obs(ctrl)
        res = ctrl.step(obs)
        self.assertIn("v", res)

    def test_import_fallback(self):
        """Import fallback executes cleanly."""
        import sys

        # Emulate importing controller without parent package
        mod_name = "team.controller"
        if mod_name in sys.modules:
            orig = sys.modules[mod_name]
            try:
                # Compile and exec with __package__ = ""
                with open("/Users/yegor/doc-1790342627/team/controller.py", "r") as f:
                    code = f.read()
                globs = {
                    "__name__": "__main__",
                    "__file__": "/Users/yegor/doc-1790342627/team/controller.py",
                    "__package__": "",
                }
                # sys.path has team directory
                team_path = "/Users/yegor/doc-1790342627/team"
                if team_path not in sys.path:
                    sys.path.insert(0, team_path)
                exec(compile(code, "/Users/yegor/doc-1790342627/team/controller.py", "exec"), globs)
            finally:
                sys.modules[mod_name] = orig

    def test_lost_recovery_invocation(self):
        """Lost status triggers try_recover when stopped."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        recovered = []
        ctrl.localizer.try_recover = lambda **kwargs: recovered.append(kwargs)
        # Ensure is_lost remains True during update_scan/gnss

        def force_lost():
            ctrl.localizer.is_lost = True

        ctrl.localizer._check_lost_status = force_lost
        ctrl.localizer.is_lost = True

        obs = make_obs(ctrl, t=2.0)
        for _ in range(9):
            ctrl.step(obs)
        self.assertEqual(len(recovered), 1)
        self.assertTrue(recovered[0]["stopped"])


    def test_combined_note_override(self):
        """route_note overrides map_missing or map_extra safety note."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        ctrl.route.step = lambda **kwargs: {
            "v": 0.5,
            "w": 0.0,
            "remaining_dist": 10.0,
            "note": "offset dy=0.3",
        }
        ctrl.safety.evaluate = lambda **kwargs: (0.5, 0.0, "moving", "map_extra")

        obs = make_obs(ctrl)
        res = ctrl.step(obs)
        self.assertEqual(res["note"], "offset dy=0.3")

    def test_estop_status_preserved_while_moving(self):
        """Статус estop сохраняется даже при ненулевой скорости одометрии."""
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        ctrl.safety.evaluate = lambda **kwargs: (0.0, 0.0, "estop", "estop close_gap")

        obs = make_obs(ctrl)
        obs["odom"]["dx"] = 0.08  # v_odom = dx / dt = 0.8 м/с (> 0.04 м/с)
        res = ctrl.step(obs)
        self.assertEqual(res["status"], "estop")
        self.assertEqual(res["v"], 0.0)

    def test_arrived_rejected_while_dock_distance_over_0_2m(self):
        """'arrived' не выставляется, пока оценка расстояния до дока больше 0.2 м.

        Дефект P1: контроллер закрывал миссию как доставленную при истинном
        расстоянии до дока 0.29-0.48 м (04_busy_yard s10/s23, m2 off_target),
        потому что дистанция прибытия считалась до концевой точки маршрута, а не
        до цели миссии. Порог прибытия - 0.2 м.
        """
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, [5.0, 2.0, 0.0])
        # Маршрут сообщает о прибытии, но цель миссии (док) все еще в 0.35 м.
        ctrl.route.step = lambda **kwargs: {
            "v": 0.0,
            "w": 0.0,
            "remaining_dist": 0.0,
            "arrived": True,
            "status": "arrived",
            "note": "",
        }
        # Концевая точка маршрута совпадает с текущей позой, поэтому старая проверка
        # (расстояние до конца active_path) объявила бы прибытие; цель миссии в 0.35 м.
        ctrl.route.active_path = np.array([[5.0, 2.0], [5.05, 2.0]])
        mission = dict(SYNTH_MISSION)
        mission["from"] = [5.0, 2.0]  # совпадает со стартом -> visited_from
        mission["goal"] = [5.35, 2.0, 0.0]  # расстояние до дока 0.35 м
        obs = make_obs(ctrl)
        obs["mission"] = mission

        res = ctrl.step(obs)
        self.assertTrue(ctrl.visited_from)
        self.assertFalse(ctrl.arrived, "док в 0.35 м не считается достигнутым")
        self.assertNotEqual(res["status"], "arrived")

        # После сближения до 0.15 м прибытие разрешено.
        mission_close = dict(mission)
        mission_close["goal"] = [5.15, 2.0, 0.0]
        ctrl.route.active_path = np.array([[5.0, 2.0], [5.15, 2.0]])
        obs2 = make_obs(ctrl, t=0.1)
        obs2["mission"] = mission_close
        res2 = ctrl.step(obs2)
        self.assertTrue(ctrl.arrived)
        self.assertEqual(res2["status"], "arrived")

    def test_visited_from_dict_and_omitted(self):
        """Coordinate dict or omitted/None 'from' key sets visited_from = True and enables arrival."""
        # 1. Mission with coordinate dict matching start pose
        ctrl = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        mission_dict = dict(SYNTH_MISSION)
        mission_dict["from"] = {"x": START[0], "y": START[1]}
        obs = make_obs(ctrl)
        obs["mission"] = mission_dict
        ctrl.step(obs)
        self.assertTrue(ctrl.visited_from)

        # 2. Mission with coordinate dict far away
        ctrl2 = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        mission_far = dict(SYNTH_MISSION)
        mission_far["from"] = {"x": 80.0, "y": 80.0}
        obs2 = make_obs(ctrl2)
        obs2["mission"] = mission_far
        ctrl2.step(obs2)
        self.assertFalse(ctrl2.visited_from)

        # 3. Mission with 'from' set to None
        ctrl3 = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        mission_none = dict(SYNTH_MISSION)
        mission_none["from"] = None
        obs3 = make_obs(ctrl3)
        obs3["mission"] = mission_none
        ctrl3.step(obs3)
        self.assertTrue(ctrl3.visited_from)

        # 4. Mission with 'from' key completely omitted
        ctrl4 = Controller(SYNTH_MAP, SYNTH_CONFIG, list(START))
        mission_omitted = dict(SYNTH_MISSION)
        mission_omitted.pop("from", None)
        obs4 = make_obs(ctrl4)
        obs4["mission"] = mission_omitted
        ctrl4.step(obs4)
        self.assertTrue(ctrl4.visited_from)


if __name__ == "__main__":
    unittest.main()
