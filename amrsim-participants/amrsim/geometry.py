"""Planar geometry on numpy arrays: polygons, segments, rays, circles.

Conventions: meters, angles in radians counterclockwise from +X (east).
A segment array has shape (M, 4): x1, y1, x2, y2.
"""
import math

import numpy as np


def as_poly(points):
    """List of [x, y] -> (N, 2) float array."""
    return np.asarray(points, dtype=float).reshape(-1, 2)


def wrap_angle(a):
    """Wrap to [-pi, pi)."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def points_in_polygon(pts, poly):
    """Even-odd rule. pts (N, 2), poly (M, 2) -> bool (N,)."""
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    x = pts[:, 0][:, None]
    y = pts[:, 1][:, None]
    x1 = poly[:, 0][None, :]
    y1 = poly[:, 1][None, :]
    x2 = np.roll(poly[:, 0], -1)[None, :]
    y2 = np.roll(poly[:, 1], -1)[None, :]
    straddle = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    hits = straddle & (x < x_cross)
    return (hits.sum(axis=1) % 2) == 1


def point_in_polygon(x, y, poly):
    return bool(points_in_polygon([[x, y]], poly)[0])


def polygon_segments(poly):
    """(N, 2) polygon -> (N, 4) closed ring of edges."""
    nxt = np.roll(poly, -1, axis=0)
    return np.hstack([poly, nxt])


def polygon_area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def point_segment_distance(px, py, segs):
    """Distance from point to each segment. segs (M, 4) -> (M,)."""
    if len(segs) == 0:
        return np.empty(0)
    ax, ay, bx, by = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    ex, ey = bx - ax, by - ay
    ll = ex * ex + ey * ey
    with np.errstate(divide="ignore", invalid="ignore"):
        u = ((px - ax) * ex + (py - ay) * ey) / ll
    u = np.where(ll > 0, np.clip(u, 0.0, 1.0), 0.0)
    dx = ax + u * ex - px
    dy = ay + u * ey - py
    return np.sqrt(dx * dx + dy * dy)


def segments_near(segs, aabb, x, y, radius):
    """Subset of segments whose bounding box is within radius of (x, y)."""
    if len(segs) == 0:
        return segs
    m = (aabb[:, 0] <= x + radius) & (aabb[:, 2] >= x - radius) & \
        (aabb[:, 1] <= y + radius) & (aabb[:, 3] >= y - radius)
    return segs[m]


def segments_aabb(segs):
    if len(segs) == 0:
        return np.empty((0, 4))
    return np.stack([np.minimum(segs[:, 0], segs[:, 2]), np.minimum(segs[:, 1], segs[:, 3]),
                     np.maximum(segs[:, 0], segs[:, 2]), np.maximum(segs[:, 1], segs[:, 3])], axis=1)


def ray_cast(ox, oy, angles, segs, circles=None):
    """Distance along each ray to the first hit; inf where nothing is hit.

    angles (K,) absolute ray directions; segs (M, 4); circles (C, 3) cx, cy, r.
    """
    dx = np.cos(angles)
    dy = np.sin(angles)
    out = np.full(angles.shape, np.inf)
    if segs is not None and len(segs):
        px = segs[:, 0] - ox
        py = segs[:, 1] - oy
        ex = segs[:, 2] - segs[:, 0]
        ey = segs[:, 3] - segs[:, 1]
        denom = dx[:, None] * ey[None, :] - dy[:, None] * ex[None, :]
        cpe = (px * ey - py * ex)[None, :]
        cpd = px[None, :] * dy[:, None] - py[None, :] * dx[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = cpe / denom
            u = cpd / denom
        ok = (np.abs(denom) > 1e-12) & (t > 1e-9) & (u >= 0.0) & (u <= 1.0)
        t = np.where(ok, t, np.inf)
        out = np.minimum(out, t.min(axis=1))
    if circles is not None and len(circles):
        cx = circles[:, 0] - ox
        cy = circles[:, 1] - oy
        rr = circles[:, 2]
        b = dx[:, None] * cx[None, :] + dy[:, None] * cy[None, :]
        c = (cx * cx + cy * cy - rr * rr)[None, :]
        disc = b * b - c
        with np.errstate(invalid="ignore"):
            sq = np.sqrt(np.where(disc >= 0, disc, np.nan))
        t = b - sq
        # origin inside a circle: report the exit point
        t = np.where(c < 0, b + sq, t)
        t = np.where((disc >= 0) & (t > 1e-9), t, np.inf)
        out = np.minimum(out, t.min(axis=1))
    return out
