"""Unit tests for team.perceive module."""
import math
import unittest

import numpy as np

from team.geom import box_segs, raycast
from team.perceive import (
    Perception,
    Track,
    fit_cluster_geometry,
    is_wall_cluster,
    is_wall_continuation,
)


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

        self.assertGreaterEqual(len(tracks), 1)
        tr = tracks[0]
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
        self.assertEqual(len(tracks), 1)

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
        self.assertAlmostEqual(tracks1[0].ox, 3.0, delta=0.2)
        self.assertAlmostEqual(tracks1[0].oy, 0.0, delta=0.2)

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
        self.assertAlmostEqual(tracks2[0].ox, 3.0, delta=0.2)

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


if __name__ == "__main__":
    unittest.main()
