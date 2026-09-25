"""Unit tests for team.safety module."""
import math
import unittest

import numpy as np

from backend.perceive import Track
from backend.safety import (
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
        # plan/03:55: current clearance < 3.3 m -> v <= 0.22 (scoring penalty starts at 3.0 m)
        self.assertLessEqual(v_safe, 0.22)
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

    def test_slow_person_side_gap_3_3(self):
        # plan/03:55: clearance < 3.3 m caps v at 0.22 even when the person is outside the
        # old |y| < 1.8 corridor (previously neither branch triggered -> full speed).
        tr = Track(track_id=1, ox=3.5, oy=2.0)
        tr.pts = np.array([[3.5, 2.0]])  # dist hypot(3.5, 2.0) = 4.03 -> clearance 2.83 m
        tr.class_label = "pedestrian"
        tr.dyn = True

        v_safe, _, status, note = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.1,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertLessEqual(v_safe, 0.22)
        self.assertGreater(v_safe, 0.0)
        self.assertIn("slow_person", note)

    def test_person_stop_has_no_timeout(self):
        # plan/03:72-73: after stopping for a person, v stays 0 until the predicted clearance
        # exceeds 3.3 m. The forbidden "waited 8 s then crawled" behaviour must not appear.
        tr = Track(track_id=1, ox=1.9, oy=0.0)
        tr.pts = np.array([[1.9, 0.0]])  # clearance 0.7 m
        tr.class_label = "pedestrian"
        tr.dyn = True

        notes = set()
        for _ in range(150):  # 15 s: well past the old 8 s timeout
            v_safe, _, _, note = self.gov.evaluate(
                v_cand=1.39,
                w_cand=0.0,
                v_odom=0.0,
                w_odom=0.0,
                pose=(0.0, 0.0, 0.0),
                odom_pose=(0.0, 0.0, 0.0),
                tracks=[tr],
                ranges=np.full(360, 20.0),
                rel_angles=np.radians(np.arange(360)),
                zones=[],
            )
            self.assertEqual(v_safe, 0.0)
            self.assertIn("stop_person", note)
            notes.add(note)
        # One and the same note for the whole cause (no flicker).
        self.assertEqual(len(notes), 1)

        # Person walks away: predicted clearance 3.8 m > 3.3 m releases the hold.
        tr.pts = np.array([[5.0, 0.0]])
        v_go, _, _, note_go = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.0,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertGreater(v_go, 0.0)
        self.assertNotIn("stop_person", note_go)

    def test_lost_zeroes_speed_and_status_after_stop(self):
        # plan/02:145: while lost, v = 0; status 'lost' only once |v_odom| <= 0.04, else 'moving'.
        v_move, _, st_move, note_move = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.3,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
            is_lost=True,
            sigma_cross=1.1,
        )
        self.assertEqual(v_move, 0.0)
        self.assertEqual(st_move, "moving")
        self.assertIn("lost s_lat=1.1", note_move)

        v_stop, _, st_stop, note_stop = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.0,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
            is_lost=True,
            sigma_cross=1.1,
        )
        self.assertEqual(v_stop, 0.0)
        self.assertEqual(st_stop, "lost")
        self.assertIn("lost s_lat=1.1", note_stop)

    def test_estop_only_when_normal_brake_fails(self):
        # plan/03:78-84: estop only for a confirmed cluster closer than 1.2 m while closing
        # and when the normal 1.2 m/s^2 brake can no longer stop in time.
        tr = Track(track_id=1, ox=2.0, oy=0.0)
        tr.pts = np.array([[2.0, 0.0]])  # clearance 0.8 m < 1.2 m
        tr.class_label = "pedestrian"
        tr.dyn = True

        v_estop, w_estop, st_estop, _ = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.3,
            v_odom=1.3,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertEqual(v_estop, 0.0)
        self.assertEqual(w_estop, 0.0)
        self.assertEqual(st_estop, "estop")

        # False estop at gap >= 1.5 m is penalised: never trigger it here.
        tr_far = Track(track_id=1, ox=2.8, oy=0.0)
        tr_far.pts = np.array([[2.8, 0.0]])  # clearance 1.6 m
        tr_far.class_label = "pedestrian"
        tr_far.dyn = True
        gov_far = SafetyGovernor(v_top=1.39, dt=0.1)
        _, _, st_far, _ = gov_far.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=1.3,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr_far],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertNotEqual(st_far, "estop")

    def test_wall_outside_map_counts_as_obstacle(self):
        # plan/03:26,39: an unmapped wall (is_wall=True, map_extra) is an obstacle: it must
        # enter the clearance/stop logic, never be skipped.
        wall = Track(track_id=1, ox=1.5, oy=0.0)
        wall.pts = np.array([[1.5, 0.0]])
        wall.class_label = "wall_extra"
        wall.dyn = False
        self.assertTrue(wall.is_wall)

        v_safe, w_safe, _, _ = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.4,
            v_odom=1.3,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[wall],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertEqual(v_safe, 0.0)
        self.assertEqual(w_safe, 0.0)

        # A wall beside the path (outside the front corridor) must not force a stop/estop.
        wall_side = Track(track_id=1, ox=1.5, oy=1.5)
        wall_side.pts = np.array([[1.5, 1.5]])
        wall_side.class_label = "wall_extra"
        wall_side.dyn = False
        gov_side = SafetyGovernor(v_top=1.39, dt=0.1)
        v_side, _, st_side, _ = gov_side.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=1.3,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[wall_side],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertGreater(v_side, 0.0)
        self.assertNotEqual(st_side, "estop")

    def test_slow_person_visible_next_to_perception_note(self):
        # plan/03:102-120: the reason must be written explicitly; slow_person must not be
        # hidden by a map_missing/map_extra note.
        tr = Track(track_id=1, ox=3.7, oy=0.0)
        tr.pts = np.array([[3.7, 0.0]])  # clearance 2.5 m
        tr.class_label = "pedestrian"
        tr.dyn = True

        _, _, _, note = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.1,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
            perception_note="map_extra",
        )
        self.assertIn("slow_person", note)
        self.assertIn("map_extra", note)

    def test_blocked_wheels_and_zone_notes(self):
        zone_poly = [[50.0, 0.0], [100.0, 0.0], [100.0, 50.0], [50.0, 50.0]]
        v_safe, _, status, note = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.0,
            v_odom=0.0,
            w_odom=0.0,
            pose=(60.0, 20.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[(zone_poly, 0.8)],
            blocked_wheels=True,
        )
        self.assertEqual(v_safe, 0.0)
        self.assertEqual(status, "waiting")
        self.assertIn("blocked_wheels", note)
        self.assertIn("zone v=0.75", note)

    def test_w_zeroed_when_cluster_inside_braking_path(self):
        # plan/03:76: if a cluster ahead is closer than the braking path, w is zeroed too.
        tr = Track(track_id=1, ox=1.0, oy=0.0)
        tr.pts = np.array([[1.0, 0.0]])
        tr.class_label = "pedestrian"
        tr.dyn = True

        _, w_safe, _, _ = self.gov.evaluate(
            v_cand=1.39,
            w_cand=0.5,
            v_odom=1.39,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=[tr],
            ranges=np.full(360, 20.0),
            rel_angles=np.radians(np.arange(360)),
            zones=[],
        )
        self.assertEqual(w_safe, 0.0)


    # --- D2: human limits are scoped to is_human = is_pedestrian or is_unknown ---

    def _eval(self, tracks, v_cand=1.39, v_odom=0.3, w_cand=0.0, gov=None, ranges=None, **kw):
        """Run one SafetyGovernor.evaluate with a clear 20 m lidar unless overridden."""
        gov = gov if gov is not None else SafetyGovernor(v_top=1.39, dt=0.1)
        return gov.evaluate(
            v_cand=v_cand,
            w_cand=w_cand,
            v_odom=v_odom,
            w_odom=0.0,
            pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0),
            tracks=tracks,
            ranges=np.full(360, 20.0) if ranges is None else ranges,
            rel_angles=np.radians(np.arange(360)),
            zones=[],
            **kw,
        )

    def _track(self, ox, oy, label, dyn):
        tr = Track(track_id=1, ox=ox, oy=oy)
        tr.pts = np.array([[ox, oy]], dtype=float)
        tr.class_label = label
        tr.dyn = dyn
        return tr

    def test_object_side_gap_two_meters_does_not_limit_speed(self):
        # (a) Confirmed static object to the side with a 2.0 m honest gap: it is outside the
        # swept corridor and further than the braking path, so it must not limit v at all.
        obj = self._track(0.6, 2.837, "static_object", False)  # hypot = 2.9 -> gap 2.0
        self.assertAlmostEqual(calculate_clearance(obj.pts, is_pedestrian=False), 2.0, places=3)
        v_safe, _, _, note = self._eval([obj])
        self.assertAlmostEqual(v_safe, 1.39)
        self.assertNotIn("slow_person", note)
        self.assertNotIn("stop_person", note)
        self.assertNotIn("stop_object", note)

    def test_object_in_swept_corridor_stops(self):
        # (b) Confirmed static object inside the swept corridor: v = 0 and rotation is zeroed.
        obj = self._track(1.2, 0.0, "static_object", False)
        v_safe, w_safe, _, note = self._eval([obj], v_cand=1.39, v_odom=0.3, w_cand=0.4)
        self.assertEqual(v_safe, 0.0)
        self.assertEqual(w_safe, 0.0)
        self.assertIn("stop_object", note)

    def test_human_gap_three_meters_caps_speed(self):
        # (c) Person with a 3.0 m clearance (< 3.3 m) -> v <= 0.22, not a full stop.
        human = self._track(4.2, 0.0, "pedestrian", True)  # 4.2 - 0.9 - 0.3 = 3.0
        v_safe, _, _, note = self._eval([human], v_cand=1.39, v_odom=0.1)
        self.assertLessEqual(v_safe, 0.22)
        self.assertGreater(v_safe, 0.0)
        self.assertIn("slow_person", note)

    def test_human_gap_below_stop_gap_stops(self):
        # (d) Person with a 0.7 m clearance (< 0.8 m) -> v = 0.
        human = self._track(1.9, 0.0, "pedestrian", True)  # 1.9 - 1.2 = 0.7
        v_safe, _, _, note = self._eval([human], v_cand=1.39, v_odom=0.3)
        self.assertEqual(v_safe, 0.0)
        self.assertIn("stop_person", note)

    def test_human_limits_not_applied_to_static_object(self):
        # A confirmed static object at the same geometry where a person would be capped at
        # 0.22 m/s must stay unrestricted: the 3.0 m human gap rule does not apply to objects.
        obj = self._track(3.7, 0.0, "static_object", False)  # honest gap 2.8 m
        v_obj, _, _, note_obj = self._eval([obj], v_cand=1.39, v_odom=0.3)
        self.assertGreater(v_obj, 0.22)
        self.assertAlmostEqual(v_obj, 1.39)
        self.assertNotIn("slow_person", note_obj)
        self.assertNotIn("stop_person", note_obj)

        human = self._track(3.7, 0.0, "pedestrian", True)  # clearance 2.5 m -> human cap
        v_hum, _, _, note_hum = self._eval([human], v_cand=1.39, v_odom=0.3)
        self.assertLessEqual(v_hum, 0.22)
        self.assertIn("slow_person", note_hum)

    def test_human_limits_not_applied_to_wall(self):
        # An unmapped wall with the same clearance as a person is an obstacle only through the
        # corridor/braking rule, never through the 3.3 m/0.22 m/s human rule.
        wall = self._track(3.7, 0.0, "wall_extra", False)  # honest gap 2.8 m
        self.assertTrue(wall.is_wall)
        v_wall, _, _, note_wall = self._eval([wall], v_cand=1.39, v_odom=0.3)
        self.assertAlmostEqual(v_wall, 1.39)
        self.assertNotIn("slow_person", note_wall)
        self.assertNotIn("stop_person", note_wall)

        # The same wall inside the corridor is still a hard stop with the object note.
        wall_close = self._track(1.5, 0.0, "wall_extra", False)
        v_close, w_close, _, note_close = self._eval(
            [wall_close], v_cand=1.39, v_odom=0.3, w_cand=0.4
        )
        self.assertEqual(v_close, 0.0)
        self.assertEqual(w_close, 0.0)
        self.assertIn("stop_object", note_close)
        self.assertNotIn("stop_person", note_close)

    def test_object_front_honest_gap_below_stop_gap_stops(self):
        # plan/03:56: a confirmed object straight ahead in the swept frontal band whose honest
        # gap (no 0.3 m pedestrian radius) is below 0.8 m must stop the platform even from rest
        # and even though the braking-reach corridor test does not reach it yet.
        obj = self._track(1.6, 0.4, "static_object", False)  # hypot 1.649 -> gap 0.749
        self.assertLess(calculate_clearance(obj.pts, is_pedestrian=False), 0.8)
        v_safe, w_safe, _, note = self._eval(
            [obj], v_cand=1.39, v_odom=0.0, w_cand=0.3
        )
        self.assertEqual(v_safe, 0.0)
        self.assertEqual(w_safe, 0.0)
        self.assertIn("stop_object", note)

        # Just above the threshold the object stays permissive (gap 0.824 m > 0.8 m).
        obj_ok = self._track(1.65, 0.5, "static_object", False)
        v_ok, _, _, _ = self._eval([obj_ok], v_cand=1.39, v_odom=0.0)
        self.assertGreater(v_ok, 0.0)

    def test_object_does_not_hold_person_latch(self):
        # The person-stop latch is human-only: once the person is gone, a static object ahead
        # must not keep the human hold alive beyond the short dropout guard.
        human = self._track(1.9, 0.0, "pedestrian", True)  # clearance 0.7 m -> latch
        gov = SafetyGovernor(v_top=1.39, dt=0.1)
        v_first, _, _, note_first = self._eval([human], v_odom=0.0, gov=gov)
        self.assertEqual(v_first, 0.0)
        self.assertIn("stop_person", note_first)

        obj = self._track(3.7, 0.0, "static_object", False)  # honest gap 2.8 m, not in corridor
        v_last, note_last = None, None
        for _ in range(12):
            v_last, _, _, note_last = self._eval([obj], v_odom=0.0, gov=gov)
        self.assertGreater(v_last, 0.22)
        self.assertNotIn("stop_person", note_last)
        self.assertNotIn("slow_person", note_last)

    def test_static_object_one_metre_gap_limits_speed(self):
        # Task I.5: a static object at an honest gap of 1.0 m (< 1.5 m guard) gets the
        # human speed cap. At rest the 2 s prediction stays above STOP_GAP, so v <= 0.22.
        obj = self._track(1.9, 0.0, "static_object", False)  # honest gap 1.0 m
        self.assertAlmostEqual(calculate_clearance(obj.pts, is_pedestrian=False), 1.0, places=3)
        v_safe, _, _, note = self._eval([obj], v_cand=1.39, v_odom=0.0)
        self.assertGreater(v_safe, 0.0)
        self.assertLessEqual(v_safe, 0.22)
        self.assertNotIn("stop_person", note)

        # The same 1.0 m object while the platform is still rolling: the 2 s prediction
        # closes the gap below 0.8 m, so the guard stops instead of crawling.
        v_moving, _, _, _ = self._eval([obj], v_cand=1.39, v_odom=0.3)
        self.assertEqual(v_moving, 0.0)

    def test_static_object_inside_guard_below_stop_gap_stops(self):
        # Honest gap 0.7 m < STOP_GAP: even from rest the platform must hold v = 0.
        obj = self._track(1.6, 0.0, "static_object", False)  # honest gap 0.7 m
        v_safe, _, _, note = self._eval([obj], v_cand=1.39, v_odom=0.0)
        self.assertEqual(v_safe, 0.0)
        self.assertIn("stop_object", note)

    def test_static_object_guard_edge_and_walls(self):
        # Just outside the 1.5 m guard the object stays permissive (1.6 m honest gap).
        obj_ok = self._track(2.5, 0.0, "static_object", False)  # honest gap 1.6 m
        v_ok, _, _, _ = self._eval([obj_ok], v_cand=1.39, v_odom=0.0)
        self.assertGreater(v_ok, 0.22)

        # The near-miss guard is object-only: a wall with the same honest gap keeps the
        # object rules (outside the swept corridor and the braking reach -> permissive).
        wall = self._track(1.8, 0.4, "wall_extra", False)  # honest gap 0.944 m < 1.5 m
        v_wall, _, _, _ = self._eval([wall], v_cand=1.39, v_odom=0.0)
        self.assertAlmostEqual(v_wall, 1.39)

    def test_sigma_cross_optional_and_reported(self):
        # sigma_cross is an optional keyword (default 0.0) reported in the lost note; controller
        # passes the lateral pose sigma for 'lost s_lat='.
        _, _, _, note = self._eval([], v_odom=0.0, is_lost=True)
        self.assertIn("lost s_lat=0.0", note)
        _, _, _, note_sig = self._eval([], v_odom=0.0, is_lost=True, sigma_cross=0.4)
        self.assertIn("lost s_lat=0.4", note_sig)

    def test_early_slowdown_oncoming_pedestrian(self):
        # 1. Oncoming pedestrian 7.0m ahead moving towards robot at -1.0 m/s: early deceleration
        ped_far = self._track(7.0, 0.0, "pedestrian", True)
        ped_far.vx_odom = -1.0
        v_far, _, _, note_far = self._eval([ped_far], v_cand=1.39, v_odom=0.8)
        self.assertLessEqual(v_far, 0.85)
        self.assertGreater(v_far, 0.0)

        # 2. Oncoming pedestrian 5.0m ahead moving towards robot: decelerates further
        ped_mid = self._track(5.0, 0.0, "pedestrian", True)
        ped_mid.vx_odom = -1.0
        v_mid, _, _, _ = self._eval([ped_mid], v_cand=1.39, v_odom=0.5)
        self.assertLessEqual(v_mid, 0.50)
        self.assertGreater(v_mid, 0.0)

        # 3. Oncoming pedestrian 2.0m ahead (closing fast): safe stop
        ped_close = self._track(2.0, 0.0, "pedestrian", True)
        ped_close.vx_odom = -1.0
        v_close, _, _, note_close = self._eval([ped_close], v_cand=1.39, v_odom=0.3)
        self.assertEqual(v_close, 0.0)
        self.assertIn("stop_person", note_close)

    def test_same_way_pedestrian_speed_matching(self):
        # 1. Same-way pedestrian 4.5m ahead walking at 0.8 m/s: robot matches speed with safe buffer
        ped_ahead = self._track(4.5, 0.0, "pedestrian", True)
        ped_ahead.vx_odom = 0.8
        v_match, _, _, _ = self._eval([ped_ahead], v_cand=1.39, v_odom=0.8)
        self.assertLessEqual(v_match, 1.05)
        self.assertGreaterEqual(v_match, 0.70)

        # 2. Same-way pedestrian 3.5m ahead (clearance < 3.0m): caps at <= 0.22 to prevent proximity penalty
        ped_near = self._track(3.5, 0.0, "pedestrian", True)
        ped_near.vx_odom = 0.8
        v_near, _, _, _ = self._eval([ped_near], v_cand=1.39, v_odom=0.5)
        self.assertLessEqual(v_near, 0.22)
        self.assertGreater(v_near, 0.0)

        # 3. Same-way pedestrian <= 2.2m: safe stop behind
        ped_stop = self._track(2.0, 0.0, "pedestrian", True)
        ped_stop.vx_odom = 0.8
        v_stop, _, _, _ = self._eval([ped_stop], v_cand=1.39, v_odom=0.2)
        self.assertEqual(v_stop, 0.0)

    def test_standing_pedestrian_safe_side_pass(self):
        # 1. Standing pedestrian at lateral distance 2.0m (clearance ~2.0m < 3.3m):
        # Robot continues moving smoothly at safe crawl without stopping!
        ped_side = self._track(2.5, 2.0, "pedestrian", True)
        ped_side.vx_odom = 0.0
        ped_side.vy_odom = 0.0
        v_side, _, status, note = self._eval([ped_side], v_cand=1.39, v_odom=0.2)
        self.assertLessEqual(v_side, 0.22)
        self.assertGreater(v_side, 0.0)
        self.assertEqual(status, "moving")
        self.assertNotIn("stop_person", note)

        # 2. Standing pedestrian with wide clearance (lateral 2.5m, clearance >= 3.3m):
        # Robot passes at safe speed up to 0.55 m/s
        ped_wide = self._track(4.5, 2.5, "pedestrian", True)
        ped_wide.vx_odom = 0.0
        ped_wide.vy_odom = 0.0
        v_wide, _, _, _ = self._eval([ped_wide], v_cand=1.39, v_odom=0.5)
        self.assertLessEqual(v_wide, 0.55)
        self.assertGreaterEqual(v_wide, 0.40)

    def test_standing_pedestrian_in_path_smooth_stop(self):
        # 1. Standing pedestrian directly in path 2.2m ahead: stops smoothly ahead of time
        ped_path = self._track(2.2, 0.0, "pedestrian", True)
        ped_path.vx_odom = 0.0
        ped_path.vy_odom = 0.0
        v_stop, _, _, note = self._eval([ped_path], v_cand=1.39, v_odom=0.2)
        self.assertEqual(v_stop, 0.0)
        self.assertIn("stop_person", note)

        # 2. Standing pedestrian 4.0m ahead in path: decelerates smoothly before stopping
        ped_mid = self._track(4.0, 0.0, "pedestrian", True)
        ped_mid.vx_odom = 0.0
        ped_mid.vy_odom = 0.0
        v_mid, _, _, _ = self._eval([ped_mid], v_cand=1.39, v_odom=0.4)
        self.assertLessEqual(v_mid, 0.55)
        self.assertGreater(v_mid, 0.0)

    def test_person_hold_releases_when_path_cleared(self):
        gov = SafetyGovernor(v_top=1.39, dt=0.1)

        # Step 1: Human blocks direct path at (2.0, 0.0) -> robot stops and sets person hold
        human = self._track(2.0, 0.0, "pedestrian", True)
        v_stop, _, _, note_stop = self._eval([human], v_cand=1.39, v_odom=0.0, gov=gov)
        self.assertEqual(v_stop, 0.0)
        self.assertIn("stop_person", note_stop)
        self.assertTrue(gov._person_hold)

        # Step 2: Human steps aside to safe lateral clearance (2.0, 2.0)
        human_aside = self._track(2.0, 2.0, "pedestrian", True)
        human_aside.vx_odom = 0.0
        human_aside.vy_odom = 0.0
        v_resume, _, _, _ = self._eval([human_aside], v_cand=1.39, v_odom=0.0, gov=gov)
        # Person hold must release and robot resumes motion at safe crawl!
        self.assertFalse(gov._person_hold)
        self.assertGreater(v_resume, 0.0)
        self.assertLessEqual(v_resume, 0.22)


    def test_crossing_pedestrian_early_stop(self):
        # Crossing pedestrian 4.0m ahead moving across our lane (y=-2.0, vy=1.0 m/s towards lat=0)
        ped_cross = self._track(4.0, -2.0, "pedestrian", True)
        ped_cross.vx_odom = 0.0
        ped_cross.vy_odom = 1.0
        v_stop, _, _, note = self._eval([ped_cross], v_cand=1.39, v_odom=0.3)
        self.assertEqual(v_stop, 0.0)
        self.assertIn("stop_person", note)

    def test_pedestrian_behind_not_throttled_when_safe_clearance(self):
        # Pedestrian is behind the robot at (-3.0, 3.0) -> clearance = hypot(3, 3) - 1.2 = 3.04 m >= 3.0 m
        # Robot is driving away forward -> speed should not be capped at 0.22 m/s
        ped_behind = self._track(-3.0, 3.0, "pedestrian", True)
        v_safe, _, _, _ = self._eval([ped_behind], v_cand=1.39, v_odom=0.8)
        self.assertGreater(v_safe, 0.5)

    def test_facing_pedestrian_stops_within_yield_zone(self):
        # Attentive pedestrian walking towards platform within 4.0m center distance
        # To prevent pedestrian freeze, robot must stop completely (v=0.0)
        ped_facing = self._track(2.5, 0.0, "pedestrian", True)
        ped_facing.vx_odom = -1.0
        ped_facing.vy_odom = 0.0
        v_stop, _, _, note = self._eval([ped_facing], v_cand=1.39, v_odom=0.2)
        self.assertEqual(v_stop, 0.0)
        self.assertIn("stop_person", note)

    def test_zero_length_points_clearance(self):
        """calculate_clearance on empty array returns inf."""
        empty_pts = np.empty((0, 2), dtype=float)
        cl = calculate_clearance(empty_pts, is_pedestrian=True)
        self.assertEqual(cl, math.inf)

    def test_extreme_velocity_clamping(self):
        """Candidate velocities exceeding top platform bounds are strictly clamped."""
        v_safe, _, _, _ = self._eval([], v_cand=100.0, v_odom=0.0)
        self.assertLessEqual(v_safe, 1.39)

        v_safe_rev, _, _, _ = self._eval([], v_cand=-100.0, v_odom=0.0)
        self.assertGreaterEqual(v_safe_rev, -0.5)

    def test_status_moving_enforcement_at_speed(self):
        """Status MUST be 'moving' whenever |v_odom| >= 0.05 m/s."""
        st = determine_status(v_odom=0.06, is_lost=False, is_arrived=False)
        self.assertEqual(st, "moving")
        st_rev = determine_status(v_odom=-0.10, is_lost=False, is_arrived=False)
        self.assertEqual(st_rev, "moving")

    def test_predict_ttc_with_zero_relative_velocity(self):
        """Zero relative velocity does not cause division by zero or NaN in TTC."""
        tr = Track(track_id=99, ox=5.0, oy=0.0)
        tr.pts = np.array([[5.0, 0.0]])
        tr.vx_odom = 0.0
        cl, min_t = predict_ttc_clearance(
            track=tr,
            v_platform=0.0,
            oth=0.0,
            horizon_s=2.0,
            dt_step=0.2,
        )
        self.assertTrue(math.isfinite(cl))
        self.assertTrue(math.isfinite(min_t))


if __name__ == "__main__":
    unittest.main()
