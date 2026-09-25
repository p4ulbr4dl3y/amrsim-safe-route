"""Unit tests for team.geom module."""
import math
import time
import unittest

import numpy as np

from team_dreamteam_4_0.geom import (
    Displacement,
    box_segs,
    filter_segs_aabb,
    inside_polygon,
    point_to_segs_displacement,
    polygon_area,
    raycast,
    rot2d,
    seg_dist,
    segments_aabb,
    wrap_angle,
)


class TestWrapAngle(unittest.TestCase):
    def test_scalar_wrap(self):
        self.assertAlmostEqual(wrap_angle(0.0), 0.0)
        self.assertAlmostEqual(wrap_angle(math.pi), -math.pi)
        self.assertAlmostEqual(wrap_angle(-math.pi), -math.pi)
        self.assertAlmostEqual(wrap_angle(3 * math.pi), -math.pi)
        self.assertAlmostEqual(wrap_angle(-3 * math.pi), -math.pi)
        self.assertAlmostEqual(wrap_angle(2 * math.pi), 0.0)
        self.assertAlmostEqual(wrap_angle(math.pi / 2), math.pi / 2)
        self.assertAlmostEqual(wrap_angle(-math.pi / 2), -math.pi / 2)
        self.assertAlmostEqual(wrap_angle(2.5 * math.pi), math.pi / 2)

    def test_array_wrap(self):
        angles = np.array([-3 * math.pi, -math.pi, 0.0, math.pi / 2, 2 * math.pi, 3.5 * math.pi])
        expected = np.array([-math.pi, -math.pi, 0.0, math.pi / 2, 0.0, -math.pi / 2])
        wrapped = wrap_angle(angles)
        self.assertEqual(wrapped.shape, angles.shape)
        np.testing.assert_allclose(wrapped, expected, atol=1e-12)


class TestRot2D(unittest.TestCase):
    def test_scalar_convention(self):
        rx, ry = rot2d(1.0, 0.0, math.pi / 2)
        self.assertAlmostEqual(rx, 0.0)
        self.assertAlmostEqual(ry, 1.0)

        rx, ry = rot2d(0.0, 1.0, math.pi / 2)
        self.assertAlmostEqual(rx, -1.0)
        self.assertAlmostEqual(ry, 0.0)

    def test_array_xy_convention(self):
        x = np.array([1.0, 0.0, -1.0])
        y = np.array([0.0, 1.0, 0.0])
        rx, ry = rot2d(x, y, math.pi / 2)
        np.testing.assert_allclose(rx, [0.0, -1.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(ry, [1.0, 0.0, -1.0], atol=1e-12)

    def test_points_convention(self):
        pts = np.array([[1.0, 0.0], [0.0, 1.0]])
        r_pts = rot2d(pts, math.pi / 2)
        expected = np.array([[0.0, 1.0], [-1.0, 0.0]])
        np.testing.assert_allclose(r_pts, expected, atol=1e-12)

        single_pt = np.array([1.0, 0.0])
        r_single = rot2d(single_pt, math.pi)
        np.testing.assert_allclose(r_single, [-1.0, 0.0], atol=1e-12)


class TestRaycast(unittest.TestCase):
    def setUp(self):
        # 10x10 square room centered at (5, 5)
        # bottom (0,0)-(10,0), right (10,0)-(10,10), top (10,10)-(0,10), left (0,10)-(0,0)
        poly = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
        self.segs = box_segs(poly)

    def test_cardinal_directions(self):
        ox, oy = 5.0, 5.0
        angles = np.array([0.0, math.pi / 2, math.pi, -math.pi / 2])
        dists = raycast(ox, oy, angles, self.segs)
        expected = np.array([5.0, 5.0, 5.0, 5.0])
        np.testing.assert_allclose(dists, expected, atol=1e-7)

    def test_diagonal(self):
        ox, oy = 5.0, 5.0
        angle = np.array([math.pi / 4])
        dist = raycast(ox, oy, angle, self.segs)
        # Corner at (10, 10): dist = hypot(5, 5) = sqrt(50)
        self.assertAlmostEqual(float(dist[0]), math.sqrt(50.0), places=6)

    def test_max_range_pruning(self):
        ox, oy = 5.0, 5.0
        angles = np.array([0.0, math.pi / 4])
        # max_range = 4.0: walls are at 5.0 and 7.07, so all should be inf
        dists = raycast(ox, oy, angles, self.segs, max_range=4.0)
        self.assertTrue(np.all(np.isinf(dists)))

        # max_range = 6.0: 0 rad hits wall at 5.0, pi/4 is at 7.07 (> 6.0) so inf
        dists = raycast(ox, oy, angles, self.segs, max_range=6.0)
        self.assertAlmostEqual(dists[0], 5.0)
        self.assertTrue(math.isinf(dists[1]))

    def test_miss_and_empty(self):
        # Ray pointing away from single wall segment
        seg = np.array([[0.0, 10.0, 10.0, 10.0]])
        dists = raycast(5.0, 5.0, np.array([-math.pi / 2]), seg)
        self.assertTrue(math.isinf(dists[0]))

        # Empty segments
        d = raycast(0.0, 0.0, np.array([0.0]), np.empty((0, 4)))
        self.assertTrue(math.isinf(d[0]))

        # Empty angles
        d = raycast(0.0, 0.0, np.empty(0), seg)
        self.assertEqual(len(d), 0)


class TestSegDist(unittest.TestCase):
    def setUp(self):
        # Segment along x-axis from (0, 0) to (10, 0)
        self.segs = np.array([[0.0, 0.0, 10.0, 0.0]])

    def test_projection_cases(self):
        # Perpendicular above midpoint
        self.assertAlmostEqual(seg_dist(5.0, 3.0, self.segs), 3.0)
        # Endpoint A
        self.assertAlmostEqual(seg_dist(-4.0, 0.0, self.segs), 4.0)
        # Endpoint B diagonally
        self.assertAlmostEqual(seg_dist(13.0, 4.0, self.segs), 5.0)

    def test_vectorized_points(self):
        px = np.array([5.0, -4.0, 13.0])
        py = np.array([3.0, 0.0, 4.0])
        dists = seg_dist(px, py, self.segs)
        np.testing.assert_allclose(dists, [3.0, 4.0, 5.0], atol=1e-12)

    def test_empty(self):
        self.assertTrue(math.isinf(seg_dist(0.0, 0.0, np.empty((0, 4)))))


class TestPointToSegsDisplacement(unittest.TestCase):
    def setUp(self):
        # Segment along x-axis from (0, 0) to (10, 0)
        self.segs = np.array([[0.0, 0.0, 10.0, 0.0]])

    def test_point_above_segment(self):
        res = point_to_segs_displacement(5.0, 2.0, self.segs)
        self.assertIsInstance(res, Displacement)
        # Tuple unpacking test
        normal, proj, dist = res
        self.assertAlmostEqual(dist, 2.0)
        np.testing.assert_allclose(proj, [5.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(normal, [0.0, 1.0], atol=1e-12)
        self.assertEqual(res.seg_idx, 0)

    def test_point_below_segment(self):
        normal, proj, dist = point_to_segs_displacement(5.0, -3.0, self.segs)
        self.assertAlmostEqual(dist, 3.0)
        np.testing.assert_allclose(proj, [5.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(normal, [0.0, -1.0], atol=1e-12)

    def test_point_past_endpoint(self):
        normal, proj, dist = point_to_segs_displacement(13.0, 4.0, self.segs)
        self.assertAlmostEqual(dist, 5.0)
        np.testing.assert_allclose(proj, [10.0, 0.0], atol=1e-12)
        # Vector from (10, 0) to (13, 4) is (3, 4), unit is (0.6, 0.8)
        np.testing.assert_allclose(normal, [0.6, 0.8], atol=1e-12)

    def test_point_on_segment(self):
        # Distance 0: should fallback to segment geometric normal (-ey, ex) = (0, 1)
        normal, proj, dist = point_to_segs_displacement(4.0, 0.0, self.segs)
        self.assertAlmostEqual(dist, 0.0, places=9)
        np.testing.assert_allclose(proj, [4.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(normal, [0.0, 1.0], atol=1e-12)

    def test_vectorized(self):
        px = np.array([5.0, 5.0, 13.0])
        py = np.array([2.0, -3.0, 4.0])
        res = point_to_segs_displacement(px, py, self.segs)
        self.assertEqual(res.normals.shape, (3, 2))
        self.assertEqual(res.projs.shape, (3, 2))
        self.assertEqual(res.dists.shape, (3,))
        np.testing.assert_allclose(res.dists, [2.0, 3.0, 5.0], atol=1e-12)
        np.testing.assert_allclose(res.normals[0], [0.0, 1.0], atol=1e-12)
        np.testing.assert_allclose(res.normals[1], [0.0, -1.0], atol=1e-12)
        np.testing.assert_allclose(res.normals[2], [0.6, 0.8], atol=1e-12)


class TestInsidePolygon(unittest.TestCase):
    def setUp(self):
        self.poly = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])

    def test_inside_outside(self):
        self.assertTrue(inside_polygon(5.0, 5.0, self.poly))
        self.assertFalse(inside_polygon(-1.0, 5.0, self.poly))
        self.assertFalse(inside_polygon(12.0, 5.0, self.poly))
        self.assertFalse(inside_polygon(5.0, -2.0, self.poly))
        self.assertFalse(inside_polygon(5.0, 15.0, self.poly))

    def test_pts_calling_convention(self):
        pts = np.array([[5.0, 5.0], [-1.0, 5.0], [9.0, 9.0]])
        res = inside_polygon(pts, self.poly)
        np.testing.assert_array_equal(res, [True, False, True])


class TestBoxSegsAndArea(unittest.TestCase):
    def test_single_box_segs(self):
        poly = [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]
        segs = box_segs(poly)
        self.assertEqual(segs.shape, (4, 4))
        # First segment (0,0)->(10,0)
        np.testing.assert_allclose(segs[0], [0.0, 0.0, 10.0, 0.0])
        # Last segment (0,5)->(0,0)
        np.testing.assert_allclose(segs[3], [0.0, 5.0, 0.0, 0.0])

    def test_multiple_buildings_box_segs(self):
        blds = [
            {"polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]},
            {"polygon": [[5, 5], [6, 5], [6, 6], [5, 6]]},
        ]
        segs = box_segs(blds)
        self.assertEqual(segs.shape, (8, 4))

    def test_polygon_area(self):
        poly = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]])
        self.assertAlmostEqual(polygon_area(poly), 12.0)


class TestPerformance(unittest.TestCase):
    def test_raycast_speed(self):
        # 360 rays against 100 segments with AABB filtering
        n_segs = 100
        segs = np.zeros((n_segs, 4))
        for i in range(n_segs):
            x = (i % 10) * 10.0
            y = (i // 10) * 10.0
            segs[i] = [x, y, x + 5.0, y]

        angles = np.linspace(-math.pi, math.pi, 360, endpoint=False)
        ox, oy = 25.0, 25.0

        # Warm up
        _ = raycast(ox, oy, angles, segs, max_range=20.0)

        # Benchmark 50 iterations
        t0 = time.perf_counter()
        for _ in range(50):
            _ = raycast(ox, oy, angles, segs, max_range=20.0)
        dt = (time.perf_counter() - t0) / 50.0

        # Each raycast should take well under 1.5 ms (typically 0.1 - 0.3 ms)
        self.assertLess(dt, 0.002, f"Raycast too slow: {dt * 1000:.2f} ms")


class TestGeomEdgeCases(unittest.TestCase):
    def test_rot2d_array_theta(self):
        x, y = 1.0, 0.0
        thetas = np.array([0.0, math.pi / 2])
        rx, ry = rot2d(x, y, thetas)
        np.testing.assert_allclose(rx, [1.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(ry, [0.0, 1.0], atol=1e-12)

    def test_aabb_empty_and_none(self):
        self.assertEqual(segments_aabb(None).shape, (0, 4))
        self.assertEqual(segments_aabb(np.empty((0, 4))).shape, (0, 4))
        self.assertEqual(filter_segs_aabb(None, 0, 0, 5).shape, (0, 4))
        self.assertEqual(filter_segs_aabb(np.empty((0, 4)), 0, 0, 5).shape, (0, 4))
        segs = np.array([[0, 0, 1, 0], [10, 10, 11, 10]])
        filtered = filter_segs_aabb(segs, 0.5, 0.5, 2.0)
        self.assertEqual(len(filtered), 1)

    def test_displacement_empty(self):
        # Scalar px, py with empty segs
        disp = point_to_segs_displacement(1.0, 2.0, None)
        self.assertTrue(np.isnan(disp.normals).all())
        self.assertTrue(math.isinf(disp.dists))
        self.assertEqual(disp.seg_idx, -1)

        # Array px, py with empty segs
        disp_arr = point_to_segs_displacement([1.0, 2.0], [3.0, 4.0], np.empty((0, 4)))
        self.assertEqual(len(disp_arr.dists), 2)
        self.assertTrue(np.isinf(disp_arr.dists).all())

    def test_inside_polygon_empty_or_degenerate(self):
        # degenerate poly < 3 vertices
        self.assertFalse(inside_polygon(1.0, 1.0, [[0, 0], [1, 1]]))
        # empty query points
        res = inside_polygon(np.empty((0, 2)), [[0, 0], [1, 0], [1, 1]])
        self.assertEqual(len(res), 0)

    def test_box_segs_edge_cases(self):
        self.assertEqual(box_segs(None).shape, (0, 4))
        self.assertEqual(box_segs({"polygon": [[0, 0], [1, 0], [1, 1]]}).shape, (3, 4))
        # Nested 2D polygons
        p1 = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
        p2 = np.array([[2.0, 2.0], [3.0, 2.0], [3.0, 3.0]])
        res = box_segs([p1, p2])
        self.assertEqual(res.shape, (6, 4))
        # Invalid shape
        self.assertEqual(box_segs([[0.0, 0.0]]).shape, (0, 4))

    def test_polygon_area_degenerate(self):
        self.assertEqual(polygon_area([[0, 0], [1, 1]]), 0.0)


if __name__ == "__main__":
    unittest.main()
