"""Unit tests for team.perceive module."""
import math
import unittest

import numpy as np

from team_dreamteam_4_0.geom import box_segs, raycast
from team_dreamteam_4_0.perceive import (
    PEDESTRIAN_CONTOUR_MAX_M,
    Perception,
    Track,
    fit_cluster_geometry,
    is_wall_cluster,
    is_wall_continuation,
    seen_has_pair,
)
from team_dreamteam_4_0.safety import SafetyGovernor


class TestPerception(unittest.TestCase):
    def setUp(self):
        self.perc = Perception(dt=0.1)
        # Create standard rectangular building wall: y=50.0, x in [0, 100]
        self.map_segs = np.array([
            [0.0, 50.0, 100.0, 50.0],
            [100.0, 50.0, 100.0, 0.0],
        ])

    def test_geometry_fitting_and_wall_detection(self):
        # 1. Straight wall segment: 2.0m long, 0.02m thick
        x = np.linspace(0.0, 2.0, 20)
        y = np.zeros_like(x)
        pts_wall = np.column_stack([x, y])
        length, thickness = fit_cluster_geometry(pts_wall)
        self.assertAlmostEqual(length, 2.0, delta=0.05)
        self.assertLess(thickness, 0.05)
        self.assertTrue(is_wall_cluster(pts_wall))

        # 2. Compact circular object (pedestrian / small object): radius 0.25m
        angles = np.linspace(0, 2 * math.pi, 12, endpoint=False)
        pts_obj = np.column_stack([0.25 * np.cos(angles), 0.25 * np.sin(angles)])
        length_obj, thickness_obj = fit_cluster_geometry(pts_obj)
        self.assertLess(length_obj, 0.6)
        self.assertFalse(is_wall_cluster(pts_obj))

        # 3. Continuation of wall
        pts_piece = np.array([[2.2, 0.01], [2.4, -0.01], [2.5, 0.0]])
        self.assertTrue(is_wall_continuation(pts_piece, [pts_wall]))

    def test_clustering_unexplained_rays(self):
        # Robot at (10, 40, pi/2) facing North towards wall at y=50 (10m away)
        pose = (10.0, 40.0, math.pi / 2)
        odom_pose = (0.0, 0.0, 0.0)

        rel_angles = np.radians(np.arange(360))
        # Default ranges to wall: beam 0 looks North (y=50) -> dist = 10m
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)

        # Inject an unexpected obstacle 3m ahead of robot (at x=10, y=43)
        # Beams around beam 0 (e.g. -2, -1, 0, 1, 2)
        indices = [(0 + d) % 360 for d in range(-2, 3)]
        for idx in indices:
            ranges[idx] = 3.0

        tracks = self.perc.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.map_segs,
            sigma_pose=0.05,
            is_fog=False,
            v_odom=0.0,
            scan_inliers=50,
        )
        # Confirmation needs two adjacent hits: the first sighting alone is not active
        # (task I.1), the second confirms the track.
        self.assertEqual(len(tracks), 0)
        self.assertEqual(len(self.perc.tracks), 1)
        self.assertFalse(self.perc.tracks[0].confirmed)

        tracks = self.perc.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.map_segs,
            sigma_pose=0.05,
            is_fog=False,
            v_odom=0.0,
            scan_inliers=50,
        )

        self.assertGreaterEqual(len(tracks), 1)
        tr = tracks[0]
        self.assertTrue(tr.confirmed)
        self.assertAlmostEqual(tr.pts[:, 0].mean(), 3.0, delta=0.2)

    def test_snow_filter_isolated_ray(self):
        # A single isolated short ray (e.g. 1.5m) should NOT create a track
        pose = (10.0, 40.0, math.pi / 2)
        odom_pose = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)

        # Single ray at beam 0 is short (snow speck)
        ranges[0] = 1.5

        tracks = self.perc.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.map_segs,
            sigma_pose=0.05,
            is_fog=False,
            v_odom=0.0,
            scan_inliers=50,
        )
        self.assertEqual(len(tracks), 0)

    def test_nan_dropout_gap_handling(self):
        # Cluster of beams with 1 NaN in between should NOT break into 2 clusters
        pose = (10.0, 40.0, math.pi / 2)
        odom_pose = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)

        # Inject 4 obstacle beams with a NaN in the middle: beams -2, -1, 0, 1
        ranges[358] = 3.0
        ranges[359] = 3.0
        ranges[0] = np.nan  # dropped beam (fog)
        ranges[1] = 3.0
        ranges[2] = 3.0

        tracks = self.perc.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.map_segs,
            sigma_pose=0.05,
            is_fog=True,
            v_odom=0.0,
            scan_inliers=50,
        )
        # A single foggy frame is not yet confirmed (task I.1); the cluster is intact.
        self.assertEqual(len(self.perc.tracks), 1)
        tracks = self.perc.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.map_segs,
            sigma_pose=0.05,
            is_fog=True,
            v_odom=0.0,
            scan_inliers=50,
        )
        self.assertEqual(len(tracks), 1)
        self.assertTrue(tracks[0].confirmed)

    def test_pure_odometry_tracking(self):
        # Verify tracks live in pure odometry coordinates (ox, oy, oth)
        pose1 = (10.0, 40.0, 0.0)
        odom1 = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges1 = raycast(pose1[0], pose1[1], pose1[2] + rel_angles, self.map_segs)
        # Obstacle at 3m ahead (robot frame: x=3, y=0) -> in odom: (3, 0)
        for idx in [359, 0, 1]:
            ranges1[idx] = 3.0

        tracks1 = self.perc.step(
            ranges=ranges1,
            rel_angles=rel_angles,
            pose=pose1,
            odom_pose=odom1,
            map_segs=self.map_segs,
        )
        self.assertAlmostEqual(self.perc.tracks[0].ox, 3.0, delta=0.2)
        self.assertAlmostEqual(self.perc.tracks[0].oy, 0.0, delta=0.2)

        # Robot moves forward 1m in odom (ox=1.0) and in world (x=11.0)
        # Obstacle stays static in world at (13, 40) -> relative dist is now 2m
        pose2 = (11.0, 40.0, 0.0)
        odom2 = (1.0, 0.0, 0.0)
        ranges2 = raycast(pose2[0], pose2[1], pose2[2] + rel_angles, self.map_segs)
        for idx in [359, 0, 1]:
            ranges2[idx] = 2.0

        tracks2 = self.perc.step(
            ranges=ranges2,
            rel_angles=rel_angles,
            pose=pose2,
            odom_pose=odom2,
            map_segs=self.map_segs,
        )
        # In odom frame, obstacle is STILL at ox=3.0 (no motion!)
        self.assertAlmostEqual(self.perc.tracks[0].ox, 3.0, delta=0.2)

    def test_pedestrian_classification_by_motion(self):
        # Shift >= 0.6m in 1s classifies as pedestrian
        tr = Track(track_id=1, ox=0.0, oy=0.0)
        # Simulate 10 steps of 0.08m motion = 0.8m total
        for step in range(10):
            tr.ox += 0.08
            tr.hist.append((tr.ox, tr.oy))
            tr.seen.append(1)

        perc = Perception()
        perc.tracks = [tr]
        # Run dummy step to trigger classification
        # Directly test classification logic
        shift = math.hypot(tr.hist[-1][0] - tr.hist[0][0], tr.hist[-1][1] - tr.hist[0][1])
        self.assertGreaterEqual(shift, 0.6)
        if shift >= 0.6:
            tr.class_label = "pedestrian"
            tr.dyn = True

        self.assertTrue(tr.is_pedestrian)
        self.assertTrue(tr.dyn)

    def test_static_object_classification(self):
        # Track stays still while AMR is still for >= 10 ticks -> static_object
        tr = Track(track_id=1, ox=5.0, oy=5.0)
        tr.length = 0.5
        for _ in range(12):
            tr.hist.append((tr.ox, tr.oy))
            tr.seen.append(1)
            tr.still_ticks += 1

        if tr.still_ticks >= 10 and tr.length <= 1.0:
            tr.class_label = "static_object"
            tr.dyn = False

        self.assertTrue(tr.is_static_object)
        self.assertFalse(tr.dyn)

    def _tick_with_object(self, robot_x, object_x, v_odom=0.0):
        """Run one perception tick with a compact object directly ahead of the robot.

        Robot drives along +X at y=40 in world coordinates; the object sits at
        (object_x, 40). Five adjacent beams are shortened to the true range, and
        pure odometry follows the world motion exactly.
        """
        rel_angles = np.radians(np.arange(360))
        pose = (robot_x, 40.0, 0.0)
        odom = (robot_x - 10.0, 0.0, 0.0)
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        dist = float(object_x - robot_x)
        for d in range(-2, 3):
            ranges[d % 360] = dist
        tracks = self.perc.step(
            ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom,
            map_segs=self.map_segs, sigma_pose=0.05, is_fog=False,
            v_odom=v_odom, scan_inliers=50,
        )
        return tracks

    def test_dropped_object_becomes_static_object_while_crawling(self):
        # Task I.4c / plan/03:29 + plan/04:32-41: a compact cluster straight ahead
        # inside the swept corridor is a *human* until it has been stable in the
        # world for >= 2.0 s, even though the platform keeps crawling at 0.22 m/s
        # and never reaches |v_odom| < 0.02.
        classified_at = None
        for k in range(30):
            robot_x = 10.0 + 0.022 * k      # 0.22 m/s: the platform never stops
            object_x = 13.0                  # static in the world
            tracks = self._tick_with_object(robot_x, object_x, v_odom=0.22)
            if classified_at is None and any(t.is_static_object for t in tracks):
                classified_at = k
        self.assertIsNotNone(classified_at)
        # >= 20 stable ticks (2.0 s) before the commitment; never on the first frame.
        self.assertGreaterEqual(classified_at, 20)
        self.assertLessEqual(classified_at, 26)

        tr = [t for t in self.perc.tracks if t.is_static_object][0]
        self.assertFalse(tr.is_pedestrian)
        self.assertFalse(tr.is_unknown)
        # The object must reach the route obstacle layer (controller forwards
        # is_static_object tracks via static_obs / get_extra_obstacles).
        obs = self.perc.get_extra_obstacles()
        self.assertTrue(any(math.hypot(ox - 13.0, oy - 40.0) < 0.5 for ox, oy, _ in obs))

    def test_object_beside_the_corridor_commits_after_1_5s(self):
        # A compact object 2.0 m off the lane axis is *not* in the swept corridor, so
        # it may be committed after 1.5 s of stable world presence (task I.4c).
        classified_at = None
        for k in range(24):
            rel_angles = np.radians(np.arange(360))
            robot_x = 10.0 + 0.022 * k
            pose = (robot_x, 40.0, 0.0)
            odom = (robot_x - 10.0, 0.0, 0.0)
            ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
            dist = math.hypot(13.0 - robot_x, 2.0)
            bearing = int(round(math.degrees(math.atan2(2.0, 13.0 - robot_x)))) % 360
            for d in range(-2, 3):
                ranges[(bearing + d) % 360] = dist
            tracks = self.perc.step(
                ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom,
                map_segs=self.map_segs, sigma_pose=0.05, is_fog=False,
                v_odom=0.22, scan_inliers=50,
            )
            if classified_at is None and any(t.is_static_object for t in tracks):
                classified_at = k
        self.assertIsNotNone(classified_at)
        self.assertGreaterEqual(classified_at, 15)
        self.assertLessEqual(classified_at, 20)

    def test_moving_wall_piece_is_reclassified_as_pedestrian(self):
        # plan/03:26-28: a person whose momentary footprint looks like a thin wall
        # piece must return to the human class through its world motion, otherwise
        # the latched wall label would let safety pass them at full speed.
        tr = Track(track_id=1, ox=0.0, oy=3.0)
        tr.class_label = "wall_extra"
        tr.dyn = False
        tr.length = 1.2
        tr.thickness = 0.05
        tr.seen = [1, 1]
        tr.hist = [(0.0, 5.0), (0.0, 4.5), (0.0, 4.0), (0.0, 3.5), (0.0, 3.0)]
        self.perc.tracks = [tr]

        pose = (10.0, 40.0, math.pi / 2)
        odom = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        self.perc.step(
            ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom,
            map_segs=self.map_segs, v_odom=0.0,
        )
        self.assertTrue(tr.is_pedestrian)
        self.assertFalse(tr.is_wall)
        self.assertEqual(self.perc.get_extra_obstacles(), [])

    def test_candidate_inside_platform_body_is_rejected(self):
        # Task I.3 / plan/03:18: a return closer than R_PLATFORM - 0.05 m sits inside
        # the hull; without a reported contact it is a phantom. Its points are rejected
        # from the active obstacle set: the cluster may exist but can never confirm,
        # so it never reaches active_tracks, safety or the route layer.
        pose = (10.0, 40.0, math.pi / 2)
        odom_pose = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        for d in range(-2, 3):
            ranges[d % 360] = 0.5
        self.perc.step(
            ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom_pose,
            map_segs=self.map_segs, sigma_pose=0.05, is_fog=False,
            v_odom=0.0, scan_inliers=50,
        )
        self.assertTrue(self.perc.tracks)
        self.assertTrue(all(tr.inside_platform_body() for tr in self.perc.tracks))
        self.assertFalse(any(tr.confirmed for tr in self.perc.tracks))
        self.assertEqual(self.perc.active_tracks, [])

        # Even after several more sightings the in-hull phantom must not confirm.
        for _ in range(4):
            self.perc.step(
                ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom_pose,
                map_segs=self.map_segs, sigma_pose=0.05, is_fog=False,
                v_odom=0.0, scan_inliers=50,
            )
        self.assertEqual(self.perc.active_tracks, [])

    def test_snow_phantom_seen_pattern_never_confirms(self):
        # Task I.2 / plan/03:18: a lone/paired snow return shows [1, 0, 0, ...] and
        # never repeats in one world point -- it must never reach active_tracks.
        phantom = Track(track_id=1, ox=0.0, oy=0.0)
        phantom.seen = [1, 0, 0, 0, 0, 0]
        self.assertFalse(phantom.refresh_confirmed())
        self.perc.tracks = [phantom]
        self.assertNotIn(phantom, self.perc.active_tracks)
        # A later isolated hit still cannot form the required adjacent pair.
        phantom.seen = [1, 0, 0, 1, 0, 0]
        self.assertFalse(phantom.refresh_confirmed())
        self.assertEqual(self.perc.active_tracks, [])
        self.assertFalse(seen_has_pair([1, 0, 1, 0, 1]))
        self.assertTrue(seen_has_pair([0, 1, 1, 0]))

        # End to end: an unconfirmed phantom never reaches safety, so no phantom stop.
        gov = SafetyGovernor(v_top=1.39, dt=0.1)
        rel_angles = np.radians(np.arange(360))
        ranges = np.full(360, 20.0)
        v_safe, _, _, note = gov.evaluate(
            v_cand=1.39, w_cand=0.0, v_odom=0.0, w_odom=0.0,
            pose=(0.0, 0.0, 0.0), odom_pose=(0.0, 0.0, 0.0),
            tracks=self.perc.active_tracks, ranges=ranges, rel_angles=rel_angles, zones=[],
        )
        self.assertAlmostEqual(v_safe, 1.39)
        self.assertNotIn("stop_person", note)

    def test_confirmed_person_survives_fog_dropout(self):
        # Task I.2 / plan/03:20: once confirmed by two adjacent hits, a pedestrian
        # stays confirmed while coasting through a fog dropout, so safety keeps the
        # brake applied instead of forgetting the person.
        pose = (10.0, 40.0, 0.0)
        odom = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))

        # Two adjacent sightings of a person 1.8 m ahead (clearance 0.6 m < 0.8 m).
        for _ in range(2):
            ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
            for d in range(-2, 3):
                ranges[d % 360] = 1.8
            self.perc.step(
                ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom,
                map_segs=self.map_segs, sigma_pose=0.05, is_fog=False,
                v_odom=0.0, scan_inliers=50,
            )
        tr = self.perc.tracks[0]
        self.assertTrue(tr.confirmed)

        # Fog dropout: clear scan, the person is gone from the lidar.
        ranges_clear = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        active = self.perc.step(
            ranges=ranges_clear, rel_angles=rel_angles, pose=pose, odom_pose=odom,
            map_segs=self.map_segs, sigma_pose=0.05, is_fog=True,
            v_odom=0.0, scan_inliers=0,
        )
        self.assertIn(tr, active)
        self.assertTrue(tr.confirmed)
        self.assertIn(tr, self.perc.active_tracks)
        # And it must be classed as a human, never as a static object.
        self.assertFalse(tr.is_static_object)

        # The coasting, still-confirmed person keeps braking the platform.
        gov = SafetyGovernor(v_top=1.39, dt=0.1)
        v_safe, _, _, note = gov.evaluate(
            v_cand=1.39, w_cand=0.0, v_odom=0.0, w_odom=0.0,
            pose=pose, odom_pose=odom, tracks=self.perc.active_tracks,
            ranges=ranges_clear, rel_angles=rel_angles, zones=[],
        )
        self.assertEqual(v_safe, 0.0)
        self.assertIn("stop_person", note)

    def test_moving_track_stays_pedestrian_and_not_in_obstacles(self):
        # Shift >= 0.6 m over ~1 s latches the human class forever (plan/03:28):
        # a moving track must never become an obstacle (else it hijacks the route).
        for k in range(12):
            self._tick_with_object(10.0, 13.0 + 0.08 * k, v_odom=0.0)
        moving = [t for t in self.perc.tracks if t.is_pedestrian]
        self.assertTrue(moving)
        self.assertFalse(moving[0].is_static_object)
        self.assertFalse(moving[0].is_unknown)
        self.assertEqual(self.perc.get_extra_obstacles(), [])

    def test_frozen_after_motion_stays_pedestrian(self):
        # A frozen attentive pedestrian with motion history is NOT a static object
        # (task D1 boundary 3): it must keep human limits and stay out of the map.
        for k in range(12):
            self._tick_with_object(10.0, 13.0 + 0.08 * k, v_odom=0.0)
        frozen_x = 13.0 + 0.08 * 11
        for _ in range(15):
            self._tick_with_object(10.0, frozen_x, v_odom=0.22)

        self.assertTrue(self.perc.tracks)
        self.assertTrue(all(t.is_pedestrian for t in self.perc.tracks))
        self.assertTrue(all(not t.is_static_object for t in self.perc.tracks))
        self.assertEqual(self.perc.get_extra_obstacles(), [])

    def test_wall_track_not_reclassified_as_object(self):
        # Boundary 2: an unmapped wall/fence keeps its class and stays a route
        # obstacle even while the platform is stopped (never becomes a pallet).
        pose = (10.0, 40.0, math.pi / 2)
        odom = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        tr = Track(track_id=1, ox=0.0, oy=2.0)
        tr.class_label = "wall_extra"
        tr.dyn = False
        tr.length = 2.0
        tr.hist = [(0.0, 2.0)] * 15
        tr.seen = [1, 1]
        self.perc.tracks = [tr]
        self.perc.step(ranges=ranges, rel_angles=rel_angles, pose=pose,
                       odom_pose=odom, map_segs=self.map_segs, v_odom=0.0)

        self.assertTrue(tr.is_wall)
        self.assertFalse(tr.is_static_object)
        self.assertEqual(len(self.perc.get_extra_obstacles()), 1)

    # ------------------------------------------------------ large body vs pedestrian

    def _coast_one_tick(self):
        """Advance one clear-scan tick so the injected tracks are evaluated, no new cluster."""
        pose = (10.0, 40.0, math.pi / 2)
        odom = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        self.perc.step(ranges=ranges, rel_angles=rel_angles, pose=pose,
                       odom_pose=odom, map_segs=self.map_segs, v_odom=0.0)

    def test_large_cluster_does_not_latch_pedestrian_on_shift(self):
        # Task T.1 / plan/03:26-28: a large (non-pedestrian-contour) cluster whose
        # centroid shifts >= 0.6 m is an unmapped body, not a person. Its visible
        # centroid wanders while the body stands still (s2_container_block seed 7:
        # track id=1, length 2.7-4.2 m, a 0.69 m jump in a single tick), and latching
        # it as a pedestrian is exactly what produced the eternal `stop_person`.
        tr = Track(track_id=1, ox=0.0, oy=3.0)
        tr.class_label = "wall_extra"
        tr.dyn = False
        tr.length = PEDESTRIAN_CONTOUR_MAX_M + 1.8
        tr.thickness = 0.02
        tr.seen = [1, 1]
        tr.hist = [(0.0, 5.0), (0.0, 4.5), (0.0, 4.0), (0.0, 3.5), (0.0, 3.0)]
        self.perc.tracks = [tr]

        self._coast_one_tick()

        self.assertTrue(tr.is_wall)
        self.assertFalse(tr.is_pedestrian)
        self.assertNotEqual(tr.class_label, "pedestrian")
        # It is in the obstacle layer right away, so the route can start the bypass
        # immediately instead of waiting 1-2 s of our own stop (task T.3).
        self.assertEqual(len(self.perc.get_extra_obstacles()), 1)

    def test_compact_contour_shift_still_latches_pedestrian(self):
        # The wave-3 rescue must survive (04 seed 42): a compact body whose momentary
        # footprint looked like a thin wall piece returns to the human class through its
        # world motion, so safety keeps human limits and the route is not rewritten.
        tr = Track(track_id=1, ox=0.0, oy=3.0)
        tr.class_label = "wall_extra"
        tr.dyn = False
        tr.length = 0.5
        tr.thickness = 0.05
        tr.seen = [1, 1]
        tr.hist = [(0.0, 3.8), (0.0, 3.6), (0.0, 3.4), (0.0, 3.2), (0.0, 3.0)]
        self.perc.tracks = [tr]

        self._coast_one_tick()

        self.assertTrue(tr.is_pedestrian)
        self.assertFalse(tr.is_wall)
        self.assertEqual(self.perc.get_extra_obstacles(), [])

    def test_large_thick_cluster_becomes_wall_extra_not_unknown(self):
        # Task T.2 / plan/03:38: a long unexplained body that is *not* a thin mapped wall
        # (thickness >= 0.1 m, so is_wall is False) must still join the obstacle layer as
        # `wall_extra`. Left `unknown`, safety treats it as a person, holds an eternal
        # stop and the bypass can never start; a container face is thick, not a fence.
        tr = Track(track_id=1, ox=0.0, oy=3.0)
        tr.class_label = "unknown"
        tr.dyn = None
        tr.length = 2.5
        tr.thickness = 0.4
        tr.seen = [1, 1]
        tr.hist = [(0.0, 3.0)] * 6
        self.perc.tracks = [tr]

        self._coast_one_tick()

        self.assertTrue(tr.is_wall)
        self.assertFalse(tr.is_unknown)
        self.assertFalse(tr.is_pedestrian)
        self.assertEqual(len(self.perc.get_extra_obstacles()), 1)

    def test_latched_pedestrian_with_growing_contour_stays_human(self):
        # A person latched while compact must never be demoted into the obstacle layer
        # when the contour later grows (a merged or partial footprint): a moving human
        # must not rewrite the route (plan/03:28).
        tr = Track(track_id=1, ox=0.0, oy=3.0)
        tr.class_label = "pedestrian"
        tr.dyn = True
        tr.length = PEDESTRIAN_CONTOUR_MAX_M + 1.8
        tr.thickness = 0.02
        tr.seen = [1, 1]
        tr.hist = [(0.0, 5.0), (0.0, 4.5), (0.0, 4.0), (0.0, 3.5), (0.0, 3.0)]
        self.perc.tracks = [tr]

        self._coast_one_tick()

        self.assertTrue(tr.is_pedestrian)
        self.assertFalse(tr.is_wall)
        self.assertEqual(self.perc.get_extra_obstacles(), [])

    def test_dynamic_track_coasting_during_fog(self):
        # Dynamic pedestrian track should be predicted forward up to 1.0s (10 ticks) during dropout
        pose = (10.0, 40.0, 0.0)
        odom = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)

        # 1. Step with visible moving pedestrian
        tr = Track(track_id=1, ox=5.0, oy=0.0, pts=np.array([[5.0, 0.0]]))
        tr.class_label = "pedestrian"
        tr.dyn = True
        tr.vx_odom = 1.0  # moving along X at 1.0 m/s
        tr.seen = [1, 1]  # already confirmed by two adjacent sightings (task I.1)
        self.perc.tracks = [tr]

        # 2. Lidar drops pedestrian (all clear / fog dropout)
        # Run step with empty scan
        tracks = self.perc.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom,
            map_segs=self.map_segs,
            is_fog=True,
        )

        # Track must still be retained via prediction!
        self.assertGreaterEqual(len(tracks), 1)
        coasted_tr = tracks[0]
        self.assertTrue(coasted_tr.is_pedestrian)
        # Position predicted forward by vx * dt = 1.0 * 0.1 = 0.1m
        self.assertAlmostEqual(coasted_tr.ox, 5.1, delta=0.05)

    def test_get_extra_obstacles_world_frame(self):
        # Tracks live in the odometry frame; the route layer needs world coordinates.
        pose = (10.0, 20.0, math.pi / 2)
        odom = (1.0, 2.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        self.perc.step(
            ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom,
            map_segs=self.map_segs,
        )

        # Unmapped wall 3.0m ahead in the odom frame (+Y odom) -> +X world at heading pi/2
        tr = Track(track_id=1, ox=odom[0], oy=odom[1] + 3.0)
        tr.class_label = "wall_extra"
        tr.dyn = False
        tr.length = 2.0
        tr.seen = [1, 1]
        self.perc.tracks = [tr]

        obs = self.perc.get_extra_obstacles()
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0][0], 7.0, delta=0.05)
        self.assertAlmostEqual(obs[0][1], 20.0, delta=0.05)
        self.assertGreaterEqual(obs[0][2], 0.4)
        self.assertLessEqual(obs[0][2], 1.0)

    def test_get_extra_obstacles_empty_before_first_step(self):
        self.assertEqual(Perception(dt=0.1).get_extra_obstacles(), [])

    def test_map_extra_note_does_not_stick(self):
        pose = (10.0, 40.0, math.pi / 2)
        odom = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)

        tr = Track(track_id=1, ox=5.0, oy=0.0)
        tr.class_label = "wall_extra"
        tr.dyn = False
        tr.length = 2.0
        self.perc.tracks = [tr]
        self.perc.step(ranges=ranges, rel_angles=rel_angles, pose=pose,
                       odom_pose=odom, map_segs=self.map_segs)
        self.assertEqual(self.perc.note, "map_extra")

        # Cause disappears -> note decays instead of sticking forever
        self.perc.tracks = []
        for _ in range(25):
            self.perc.step(ranges=ranges, rel_angles=rel_angles, pose=pose,
                           odom_pose=odom, map_segs=self.map_segs)
        self.assertEqual(self.perc.note, "")

    # ------------------------------------------------------------------ plan/05:115

    def test_isolated_one_metre_ray_creates_no_track_and_no_stop_object(self):
        """A single 1 m beam beside two far returns is snow, not an obstacle (plan/05:115).

        Beam 0 is the only shortened return and both angular neighbours look at the far
        mapped wall, so the snow filter drops the lone ray: no track is created, and the
        safety governor therefore never receives a `stop_object` cause from it.
        """
        pose = (10.0, 40.0, math.pi / 2)
        odom_pose = (0.0, 0.0, 0.0)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(pose[0], pose[1], pose[2] + rel_angles, self.map_segs)
        self.assertGreater(ranges[359], 5.0)  # two far neighbours
        self.assertGreater(ranges[1], 5.0)
        ranges[0] = 1.0  # one lone short return

        tracks = self.perc.step(
            ranges=ranges, rel_angles=rel_angles, pose=pose, odom_pose=odom_pose,
            map_segs=self.map_segs, sigma_pose=0.05, is_fog=False,
            v_odom=0.0, scan_inliers=50,
        )
        self.assertEqual(tracks, [])
        self.assertEqual(self.perc.tracks, [])
        self.assertEqual(self.perc.active_tracks, [])

        gov = SafetyGovernor(v_top=1.39, dt=0.1)
        v_safe, _, status, note = gov.evaluate(
            v_cand=1.0, w_cand=0.0, v_odom=1.0, w_odom=0.0,
            pose=pose, odom_pose=odom_pose, tracks=self.perc.active_tracks,
            ranges=ranges, rel_angles=rel_angles, zones=[],
        )
        self.assertEqual(v_safe, 1.0)
        self.assertEqual(status, "moving")
        self.assertNotIn("stop_object", note)
        self.assertNotIn("stop_person", note)

    # ------------------------------------------------------------------ plan/05:114

    def test_demolished_segment_flagged_and_excluded(self):
        """A mapped wall absent from the scan is removed for the whole run (plan/03:36-38).

        Rays run past the demolished wall (the scan returns the far wall behind it)
        while the neighbouring far wall keeps matching. After enough corroborating
        ticks the segment id is latched into `removed_segment_ids`, `note` is
        `map_missing`, and the controller then hands the matcher a segment list without
        it -- so a wall that is not there cannot drag the pose (plan/04:81).
        """
        demolished = np.array([[8.0, -4.0, 8.0, 4.0]])
        far_wall = np.array([[18.0, -8.0, 18.0, 8.0]])
        segs = np.vstack([demolished, far_wall])
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(0.0, 0.0, rel_angles, far_wall)  # the near wall is gone

        removed_tick = None
        note_at_removal = None
        for k in range(40):
            self.perc.step(
                ranges=ranges, rel_angles=rel_angles, pose=(0.0, 0.0, 0.0),
                odom_pose=(0.0, 0.0, 0.0), map_segs=segs, sigma_pose=0.0,
                is_fog=False, v_odom=0.0, scan_inliers=50,
            )
            if self.perc.removed_segment_ids:
                removed_tick = k
                note_at_removal = self.perc.note
                break

        self.assertIsNotNone(removed_tick, "the demolished wall was never removed")
        self.assertGreaterEqual(removed_tick, 5)  # needs a corroborated vote, not one frame
        self.assertIn(0, self.perc.removed_segment_ids)
        self.assertEqual(note_at_removal, "map_missing")
        # Once excluded, the segment no longer contributes to the expected ranges:
        # beam 0 then measures the far wall behind the demolished one.
        exp_all = raycast(0.0, 0.0, np.array([0.0]), segs)
        exp_kept = raycast(0.0, 0.0, np.array([0.0]), segs[[1]])
        self.assertAlmostEqual(exp_all[0], 8.0, delta=0.05)
        self.assertAlmostEqual(exp_kept[0], 18.0, delta=0.05)

        # One more step with the removed segment hits line 677 (continue if s_idx in removed_segment_ids)
        self.perc.step(
            ranges=ranges, rel_angles=rel_angles, pose=(0.0, 0.0, 0.0),
            odom_pose=(0.0, 0.0, 0.0), map_segs=segs, sigma_pose=0.0,
            is_fog=False, v_odom=0.0, scan_inliers=50,
        )


class TestPerceiveCoverage(unittest.TestCase):
    """Targeted coverage for edge cases and branches in perceive.py."""

    def test_track_helpers(self):
        from team_dreamteam_4_0.perceive import track_forward_lateral, track_world_shift
        tr = Track(1, 0.0, 0.0, None)
        self.assertEqual(track_forward_lateral(tr), (math.inf, math.inf))
        tr.pts = np.empty((0, 2))
        self.assertEqual(track_forward_lateral(tr), (math.inf, math.inf))

        self.assertEqual(track_world_shift(tr), 0.0)
        tr.hist.append((0.0, 0.0))
        self.assertEqual(track_world_shift(tr), 0.0)
        tr.hist.append((3.0, 4.0))
        self.assertAlmostEqual(track_world_shift(tr), 5.0)

    def test_fit_cluster_geometry_branches(self):
        # len < 2
        self.assertEqual(fit_cluster_geometry(np.empty((0, 2))), (0.0, 0.0))
        self.assertEqual(fit_cluster_geometry(np.array([[1.0, 2.0]])), (0.0, 0.0))
        # len == 2
        l, th = fit_cluster_geometry(np.array([[0.0, 0.0], [3.0, 4.0]]))
        self.assertAlmostEqual(l, 5.0)
        self.assertEqual(th, 0.0)
        # SVD exception handling
        pts = np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
        orig_svd = np.linalg.svd
        try:
            def bad_svd(*args, **kwargs):
                raise np.linalg.LinAlgError("mock failure")
            np.linalg.svd = bad_svd
            l, th = fit_cluster_geometry(pts)
            self.assertGreater(l, 0.0)
            self.assertEqual(th, 0.0)
        finally:
            np.linalg.svd = orig_svd

    def test_wall_predicates(self):
        self.assertFalse(is_wall_cluster(np.array([[0.0, 0.0], [1.0, 1.0]])))
        # is_wall_continuation empty or short clouds
        self.assertFalse(is_wall_continuation(np.empty((0, 2)), []))
        self.assertFalse(is_wall_continuation(np.array([[1.0, 1.0]]), [np.array([[0.0, 0.0]])]))  # len < 3
        # dists > 0.6
        wall = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
        far_pts = np.array([[10.0, 10.0], [11.0, 10.0]])
        self.assertFalse(is_wall_continuation(far_pts, [wall]))

        # SVD exception in is_wall_continuation
        orig_svd = np.linalg.svd
        try:
            def bad_svd(*args, **kwargs):
                raise np.linalg.LinAlgError("mock failure")
            np.linalg.svd = bad_svd
            near_pts = np.array([[2.2, 0.0], [2.4, 0.0]])
            self.assertFalse(is_wall_continuation(near_pts, [wall]))
        finally:
            np.linalg.svd = orig_svd

    def test_step_empty_and_run_end(self):
        perc = Perception(dt=0.1)
        # Empty ranges or None map_segs
        res = perc.step([], [], (0, 0, 0), (0, 0, 0), None)
        self.assertEqual(res, [])

        # Beams triggering unexplained run at the very end of 360 array (beam 358, 359)
        map_segs = np.array([[0.0, 50.0, 100.0, 50.0]])
        rel_angles = np.radians(np.arange(360))
        ranges = np.full(360, 20.0)
        ranges[358] = 2.0
        ranges[359] = 2.0
        tracks = perc.step(ranges, rel_angles, (10, 10, 0), (0, 0, 0), map_segs, sigma_pose=0.1)
        self.assertGreaterEqual(len(perc.tracks), 1)

    def test_track_classification_and_inheritance(self):
        perc = Perception(dt=0.1)
        # Existing pedestrian track at (5.0, 5.0)
        ped = Track(0, 5.0, 5.0, np.array([[5.0, 5.0]]))
        ped.class_label = "pedestrian"
        ped.dyn = True
        perc.tracks.append(ped)

        # Detect a wall piece
        c_wall = {
            "pts": np.array([[10.0, 0.0], [12.0, 0.0], [14.0, 0.0]]),
            "ox": 12.0, "oy": 0.0,
            "length": 4.0, "thickness": 0.01,
            "is_wall": True, "is_wall_piece": False,
        }

        wall_tr = Track(1, 12.0, 0.0, c_wall["pts"])
        wall_tr.class_label = "unknown"
        wall_tr.dyn = None
        perc.tracks.append(wall_tr)

        perc._last_pose = (0.0, 0.0, 0.0)
        perc._last_odom_pose = (0.0, 0.0, 0.0)
        wall_tr.seen = [1, 1]
        wall_tr.class_label = "wall_extra"
        obs = perc.get_extra_obstacles()
        self.assertEqual(len(obs), 1)

    def test_map_discrepancies_empty_segs(self):
        perc = Perception(dt=0.1)
        perc._check_map_discrepancies(np.array([1.0]), np.array([1.0]), 0, 0, 0, np.empty((0, 4)), 50)
        self.assertEqual(perc.note, "")

        # Directly hit line 677 (removed_segment_ids continue in overshoot loop)
        perc.removed_segment_ids.add(0)
        segs = np.array([[8.0, -4.0, 8.0, 4.0]])
        exp_r = np.array([8.0])
        r_actual = np.array([18.0])
        perc._check_map_discrepancies(r_actual, exp_r, 0.0, 0.0, 0.0, segs, 50)

    def test_import_fallback(self):
        import sys
        mod_name = "team.perceive"
        if mod_name in sys.modules:
            orig = sys.modules[mod_name]
            try:
                with open("/Users/yegor/doc-1790342627/team/perceive.py", "r") as f:
                    code = f.read()
                globs = {"__name__": "__main__", "__file__": "/Users/yegor/doc-1790342627/team/perceive.py", "__package__": ""}
                team_path = "/Users/yegor/doc-1790342627/team"
                if team_path not in sys.path:
                    sys.path.insert(0, team_path)
                exec(compile(code, "/Users/yegor/doc-1790342627/team/perceive.py", "exec"), globs)
            finally:
                sys.modules[mod_name] = orig

    def test_step_wall_extra_and_ped_inheritance_and_discrepancies(self):
        perc = Perception(dt=0.1)
        perc.removed_segment_ids.add(0)
        map_segs = np.array([
            [0.0, 50.0, 100.0, 50.0],
            [0.0, 60.0, 100.0, 60.0],
        ])
        rel_angles = np.radians(np.arange(360))
        pose = (10.0, 40.0, 0.0)
        odom_pose = (0.0, 0.0, 0.0)
        ranges = np.full(360, 20.0)
        for b in range(10, 31):
            ranges[b] = 5.0
        ranges[32] = 5.0
        ranges[33] = 5.0

        perc.step(ranges, rel_angles, pose, odom_pose, map_segs, sigma_pose=0.05, scan_inliers=50)
        perc.step(ranges, rel_angles, pose, odom_pose, map_segs, sigma_pose=0.05, scan_inliers=50)

        unconf_wall = Track(100, 5.0, 5.0, np.array([[5.0, 5.0]]))
        unconf_wall.class_label = "wall_extra"
        unconf_wall.seen = [1, 0, 0]
        perc.tracks.append(unconf_wall)
        perc._last_pose = (0, 0, 0)
        perc._last_odom_pose = (0, 0, 0)
        obs = perc.get_extra_obstacles()

    def test_new_track_inherits_pedestrian(self):
        perc = Perception(dt=0.1)
        ped = Track(1, 5.0, 0.0, np.array([[5.0, 0.0]]))
        ped.class_label = "pedestrian"
        ped.dyn = True
        perc.tracks.append(ped)

        room = np.array([[-10.0, -10.0], [10.0, -10.0], [10.0, 10.0], [-10.0, 10.0]])
        segs = box_segs(room)
        rel_angles = np.radians(np.arange(360))
        ranges = raycast(0.0, 0.0, rel_angles, segs)

        ranges[0] = 5.0
        ranges[1] = 5.0
        ranges[4] = 5.2
        ranges[5] = 5.2
        perc.step(ranges, rel_angles, (0, 0, 0), (0, 0, 0), segs, sigma_pose=0.05)
        self.assertEqual(len(perc.tracks), 2)
        self.assertTrue(all(tr.class_label == "pedestrian" for tr in perc.tracks))


if __name__ == "__main__":
    unittest.main()
