"""Reference path planner: shortest path over drivable area with clearance.

Grid A* over drivable cells that keep `clearance` meters from obstacles and
from the drivable boundary, then line-of-sight shortcutting. Used offline to
fill missions[].reference_path; the simulator does not need it at run time.
"""
import heapq
import math

import numpy as np

from amrsim.geometry import as_poly, point_segment_distance, points_in_polygon, polygon_segments


class Grid:
    def __init__(self, drivable, obstacles, clearance=1.4, res=0.5):
        polys = [as_poly(p) for p in drivable]
        allp = np.vstack(polys)
        self.res = res
        self.x0 = float(allp[:, 0].min()) - 2 * res
        self.y0 = float(allp[:, 1].min()) - 2 * res
        self.nx = int(math.ceil((allp[:, 0].max() - self.x0) / res)) + 3
        self.ny = int(math.ceil((allp[:, 1].max() - self.y0) / res)) + 3
        xs = self.x0 + res * np.arange(self.nx)
        ys = self.y0 + res * np.arange(self.ny)
        gx, gy = np.meshgrid(xs, ys)  # (ny, nx)
        pts = np.stack([gx.ravel(), gy.ravel()], axis=1)
        free = np.zeros(len(pts), dtype=bool)
        for p in polys:
            free |= points_in_polygon(pts, p)
        for o in obstacles:
            o = as_poly(o)
            free &= ~points_in_polygon(pts, o)
        free = free.reshape(self.ny, self.nx)
        k = int(math.ceil(clearance / res))
        eroded = free.copy()
        for di in range(-k, k + 1):
            for dj in range(-k, k + 1):
                if (di * di + dj * dj) * res * res <= clearance * clearance:
                    eroded &= _shift(free, di, dj)
        # exact clearance to obstacle edges: thin walls can fall between grid points
        self.clearance = clearance
        self.osegs = np.vstack([polygon_segments(as_poly(o)) for o in obstacles]) if obstacles \
            else np.empty((0, 4))
        for i, j in zip(*np.nonzero(eroded)):
            if self.wall_dist(*self.xy((i, j))) < clearance:
                eroded[i, j] = False
        self.free = eroded

    def wall_dist(self, x, y):
        if len(self.osegs) == 0:
            return math.inf
        return float(point_segment_distance(x, y, self.osegs).min())

    def cell(self, x, y):
        return int(round((y - self.y0) / self.res)), int(round((x - self.x0) / self.res))

    def xy(self, c):
        return self.x0 + c[1] * self.res, self.y0 + c[0] * self.res

    def ok(self, c):
        i, j = c
        return 0 <= i < self.ny and 0 <= j < self.nx and self.free[i, j]

    def nearest_free(self, x, y, max_r=6.0):
        ci, cj = self.cell(x, y)
        best, bd = None, math.inf
        k = int(max_r / self.res)
        for i in range(ci - k, ci + k + 1):
            for j in range(cj - k, cj + k + 1):
                if self.ok((i, j)):
                    d = (i - ci) ** 2 + (j - cj) ** 2
                    if d < bd:
                        best, bd = (i, j), d
        return best

    def line_free(self, a, b):
        """Segment stays on free cells and keeps clearance - 0.3 m from walls exactly."""
        ax, ay = a
        bx, by = b
        n = max(2, int(math.hypot(bx - ax, by - ay) / 0.1) + 1)
        for s in np.linspace(0.0, 1.0, n):
            x, y = ax + s * (bx - ax), ay + s * (by - ay)
            if not self.ok(self.cell(x, y)):
                return False
        if len(self.osegs):
            xs = ax + np.linspace(0.0, 1.0, n) * (bx - ax)
            ys = ay + np.linspace(0.0, 1.0, n) * (by - ay)
            near = self.osegs[(np.minimum(self.osegs[:, 0], self.osegs[:, 2]) <= max(ax, bx) + 3) &
                              (np.maximum(self.osegs[:, 0], self.osegs[:, 2]) >= min(ax, bx) - 3) &
                              (np.minimum(self.osegs[:, 1], self.osegs[:, 3]) <= max(ay, by) + 3) &
                              (np.maximum(self.osegs[:, 1], self.osegs[:, 3]) >= min(ay, by) - 3)]
            for x, y in zip(xs, ys):
                if len(near) and point_segment_distance(x, y, near).min() < self.clearance - 0.3:
                    return False
        return True

    def astar(self, s, g):
        nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        dist = {s: 0.0}
        prev = {}
        pq = [(0.0, s)]
        while pq:
            _, c = heapq.heappop(pq)
            if c == g:
                break
            dc = dist[c]
            for di, dj in nbrs:
                n = (c[0] + di, c[1] + dj)
                if not self.ok(n):
                    continue
                nd = dc + math.hypot(di, dj)
                if nd < dist.get(n, math.inf):
                    dist[n] = nd
                    prev[n] = c
                    h = math.hypot(n[0] - g[0], n[1] - g[1])
                    heapq.heappush(pq, (nd + h, n))
        if g not in dist:
            return None
        path = [g]
        while path[-1] != s:
            path.append(prev[path[-1]])
        return path[::-1]


def _shift(a, di, dj):
    out = np.zeros_like(a)
    h, w = a.shape
    src = a[max(0, di):h + min(0, di), max(0, dj):w + min(0, dj)]
    out[max(0, -di):h + min(0, -di), max(0, -dj):w + min(0, -dj)] = src
    return out


def plan(grid, a, b):
    """Shortest free path between points a and b (both must be near free cells)."""
    ca = grid.nearest_free(*a)
    cb = grid.nearest_free(*b)
    if ca is None or cb is None:
        raise ValueError("start or goal is not near drivable free space: %s %s" % (a, b))
    cells = grid.astar(ca, cb)
    if cells is None:
        raise ValueError("no path between %s and %s" % (a, b))
    pts = [tuple(a)] + [grid.xy(c) for c in cells] + [tuple(b)]
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not grid.line_free(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return [[round(x, 2), round(y, 2)] for x, y in out]


def path_length(path):
    return float(sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:])))


def dock_route(grid, p_from, p_to, approach=3.5):
    """Path from dock p_from to dock p_to leaving and entering along dock axes."""
    hf = (math.cos(p_from["heading"]), math.sin(p_from["heading"]))
    ht = (math.cos(p_to["heading"]), math.sin(p_to["heading"]))
    out = (p_from["x"] - approach * hf[0], p_from["y"] - approach * hf[1])
    inn = (p_to["x"] - approach * ht[0], p_to["y"] - approach * ht[1])
    mid = plan(grid, out, inn)
    return [[round(p_from["x"], 2), round(p_from["y"], 2)]] + mid + \
        [[round(p_to["x"], 2), round(p_to["y"], 2)]]
