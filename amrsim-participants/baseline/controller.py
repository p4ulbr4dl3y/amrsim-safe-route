"""Baseline controller for amr-sim: a deliberately naive reference.

What it does
- Localization: odometry dead reckoning, heading blended with the IMU, GNSS
  blended in when valid. No lidar localization on the route, only a short
  "dock snap" near the goal (front and side walls of the dock bay).
- Following: pure pursuit along mission.reference_path, rotate in place when
  the path turns sharply, speed limits from map zones.
- Safety: lidar returns that the map does not explain (and that are not right
  next to a mapped wall), clustered and tracked in the odometry frame. Stop for
  anything in the corridor ahead and for moving or not yet classified objects
  closer than 3.2 m; slow to 0.25 m/s for them within 6 m; straight objects
  longer than 1 m count as walls. After 8 s of waiting for someone standing beside the path,
  pass at 0.25 m/s. Independent of the map, stop for any return inside the
  swept footprint within the braking distance.

What it does not do (on purpose): no scan matching, no odometry calibration,
no replanning around blocked paths. It passes 01_clear and fails
02_gnss_shadow, where a long GNSS shadow makes dead reckoning drift.

Allowed imports: standard library and numpy.
"""
import math

import numpy as np


def wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def raycast(ox, oy, angles, segs):
    """Distance to the first map wall along each ray (inf if none)."""
    if len(segs) == 0:
        return np.full(angles.shape, np.inf)
    dx, dy = np.cos(angles), np.sin(angles)
    px, py = segs[:, 0] - ox, segs[:, 1] - oy
    ex, ey = segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]
    den = dx[:, None] * ey[None, :] - dy[:, None] * ex[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (px * ey - py * ex)[None, :] / den
        u = (px[None, :] * dy[:, None] - py[None, :] * dx[:, None]) / den
    ok = (np.abs(den) > 1e-12) & (t > 1e-9) & (u >= 0) & (u <= 1)
    return np.where(ok, t, np.inf).min(axis=1)


def seg_dist(px, py, segs):
    """Distance from points (N,) to the nearest segment: (N,)."""
    if len(segs) == 0 or len(px) == 0:
        return np.full(len(px), np.inf)
    ax, ay, bx, by = segs[:, 0], segs[:, 1], segs[:, 2], segs[:, 3]
    ex, ey = bx - ax, by - ay
    ll = np.maximum(ex * ex + ey * ey, 1e-12)
    u = np.clip(((px[:, None] - ax) * ex + (py[:, None] - ay) * ey) / ll, 0.0, 1.0)
    dx = ax + u * ex - px[:, None]
    dy = ay + u * ey - py[:, None]
    return np.sqrt(dx * dx + dy * dy).min(axis=1)


def inside(x, y, poly):
    """Even-odd point in polygon."""
    n = len(poly)
    c = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


class Track:
    __slots__ = ("x", "y", "hist", "seen", "dyn", "still")

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.hist = [(x, y)]
        self.seen = [1]
        self.dyn = None  # None unknown, True moving, False static
        self.still = 0   # ticks without motion


class Controller:
    def __init__(self, map_, config, initial_pose):
        self.dt = config["dt"]
        rb = config["robot"]
        self.R = rb["radius"]
        self.v_top = rb["v_max"]
        self.w_top = rb["w_max"]
        lid = config["lidar"]
        self.rel = np.radians(lid["angle_min_deg"] + lid["angle_increment_deg"] * np.arange(lid["beams"]))
        self.cos_rel, self.sin_rel = np.cos(self.rel), np.sin(self.rel)
        segs = []
        for b in map_["buildings"]:
            p = np.asarray(b["polygon"], dtype=float)
            segs.append(np.hstack([p, np.roll(p, -1, axis=0)]))
        self.segs = np.vstack(segs) if segs else np.empty((0, 4))
        lo = np.minimum(self.segs[:, :2], self.segs[:, 2:])
        hi = np.maximum(self.segs[:, :2], self.segs[:, 2:])
        self.seg_lo, self.seg_hi = lo, hi
        self.zones = [(z["polygon"], z["v_max"]) for z in map_["zones"] if z["type"] == "speed_limit"]
        self.x, self.y, self.th = map(float, initial_pose)
        self.ox = self.oy = self.oth = 0.0  # pure odometry frame for tracking (no corrections)
        self.near_wait = 0
        self.near_hold = 0
        self.unc = 0.0
        self.truth = None
        self.mission = None
        self.path = None
        self.seg = 0
        self.arrived = False
        self.v_odom = 0.0
        self.rej = []
        self.tracks = []
        self.note = ""

    # ------------------------------------------------------------------ oracle
    def set_truth(self, pose):
        """Oracle channel (run with --cheat): true pose before each step."""
        self.truth = [float(a) for a in pose]

    # ------------------------------------------------------------ localization
    def near_segs(self, reach=20.5):
        m = ((self.seg_lo[:, 0] <= self.x + reach) & (self.seg_hi[:, 0] >= self.x - reach) &
             (self.seg_lo[:, 1] <= self.y + reach) & (self.seg_hi[:, 1] >= self.y - reach))
        return self.segs[m]

    def localize(self, obs):
        od = obs["odom"]
        oc, os_ = math.cos(self.oth), math.sin(self.oth)
        self.ox += oc * od["dx"] - os_ * od["dy"]
        self.oy += os_ * od["dx"] + oc * od["dy"]
        self.oth = wrap(self.oth + od["dtheta"])
        c, s = math.cos(self.th), math.sin(self.th)
        self.x += c * od["dx"] - s * od["dy"]
        self.y += s * od["dx"] + c * od["dy"]
        self.th = wrap(self.th + od["dtheta"])
        self.th = wrap(self.th + 0.02 * wrap(obs["imu"]["heading"] - self.th))
        self.v_odom = od["dx"] / self.dt
        self.unc = min(10.0, self.unc + 0.03 * math.hypot(od["dx"], od["dy"]))
        g = obs["gnss"]
        if g["valid"]:
            ix, iy = g["x"] - self.x, g["y"] - self.y
            inn = math.hypot(ix, iy)
            if inn < 2.5 + self.unc:
                k = 0.05 * min(1.0, 0.03 / max(1e-9, 0.05 * inn))
                self.x += k * ix
                self.y += k * iy
                self.unc = max(0.3, self.unc * 0.98)
                self.rej = []
            else:
                self.rej.append((ix, iy))
                if len(self.rej) > 60:  # 6 s of steady disagreement: GNSS wins
                    a = np.array(self.rej[-20:])
                    if a.std(axis=0).max() < 1.0:
                        self.x += float(a[:, 0].mean())
                        self.y += float(a[:, 1].mean())
                        self.unc = 0.6
                    self.rej = []
        else:
            self.rej = []
        if self.truth is not None:
            self.x, self.y, self.th = self.truth
            self.unc = 0.0

    def dock_snap(self, obs, goal):
        gx, gy, gh = goal
        if math.hypot(gx - self.x, gy - self.y) > 3.0 or abs(wrap(self.th - gh)) > 0.26:
            return
        r = np.asarray(obs["lidar"]["ranges"], dtype=float)
        n = len(r)

        def med(k):
            vals = r[[(k + j) % n for j in range(-2, 3)]]
            vals = vals[np.isfinite(vals)]
            return float(np.median(vals)) if len(vals) >= 3 else math.nan

        segs = self.near_segs(8.0)
        exp = raycast(self.x, self.y, np.array([self.th, self.th + math.pi / 2, self.th - math.pi / 2]), segs)
        mf, ml, mr = med(0), med(n // 4), med(3 * n // 4)
        c, s = math.cos(self.th), math.sin(self.th)
        if math.isfinite(mf) and math.isfinite(exp[0]) and abs(mf - exp[0]) < 0.8:
            d = mf - exp[0]
            self.x -= 0.5 * d * c
            self.y -= 0.5 * d * s
        lat = []
        if math.isfinite(ml) and math.isfinite(exp[1]) and abs(ml - exp[1]) < 0.8:
            lat.append(-(ml - exp[1]))
        if math.isfinite(mr) and math.isfinite(exp[2]) and abs(mr - exp[2]) < 0.8:
            lat.append(mr - exp[2])
        if lat:
            d = sum(lat) / len(lat)
            self.x += 0.5 * d * -s
            self.y += 0.5 * d * c

    # ---------------------------------------------------------------- perception
    def perceive(self, obs):
        """Confirmed clusters of unexplained lidar returns: list of (robot-frame pts, track)."""
        r = np.asarray(obs["lidar"]["ranges"], dtype=float)
        segs = self.near_segs()
        exp = raycast(self.x, self.y, self.th + self.rel, segs)
        margin = 0.35 + min(1.5, 1.5 * self.unc)
        bad = np.isfinite(r) & (r < exp - margin)
        if bad.any():
            # a return close to a mapped wall is most likely that wall seen from a wrong pose
            idx = np.flatnonzero(bad)
            ang = self.th + self.rel[idx]
            wx = self.x + r[idx] * np.cos(ang)
            wy = self.y + r[idx] * np.sin(ang)
            near_wall = seg_dist(wx, wy, segs) < 0.4 + min(1.5, 1.5 * self.unc)
            bad[idx[near_wall]] = False
        n = len(r)
        clusters = []
        finite = np.isfinite(r)
        breaks = finite & ~bad  # a real return the map explains ends an object; NaN does not
        if bad.any():
            # start after a beam that ends objects (explained return, else a missing one):
            # in fog in the open yard every return can be unexplained
            start = int(np.argmax(breaks)) if breaks.any() else int(np.argmax(~finite)) if (~finite).any() else 0
            run = []
            skipped = 0
            for j in range(1, n + 1):
                k = (start + j) % n
                if bad[k] and (not run or self._gap(r, k, run[-1]) < 0.6):
                    # neighbours closer than 0.6 m in the plane belong to one object (a fence seen
                    # at a shallow angle has large range steps between beams, small gaps in the plane)
                    run.append(k)
                    skipped = 0
                    continue
                if run and skipped < 2:
                    nxt = [(start + j + d) % n for d in (1, 2)]
                    if not finite[k] or any(bad[q] and self._gap(r, q, run[-1]) < 0.6 for q in nxt):
                        skipped += 1  # a dropped beam (fog) or a stray return (snow) inside an object
                        continue
                if len(run) >= 2:
                    clusters.append(run)
                run = [k] if bad[k] else []
                skipped = 0
            if len(run) >= 2:
                clusters.append(run)
        # tracks live in the odometry frame: GNSS corrections of the pose do not move them
        c, s = math.cos(self.oth), math.sin(self.oth)
        out = []
        cur = []
        for run in clusters:
            idx = np.array(run)
            px = r[idx] * self.cos_rel[idx]
            py = r[idx] * self.sin_rel[idx]
            wx = self.ox + c * px.mean() - s * py.mean()
            wy = self.oy + s * px.mean() + c * py.mean()
            cur.append((np.stack([px, py], axis=1), wx, wy))
        # associate with tracks (nearest within 1 m)
        used = set()
        for pts, wx, wy in cur:
            best, bd = None, 1.0
            for i, tr in enumerate(self.tracks):
                if i in used:
                    continue
                d = math.hypot(tr.x - wx, tr.y - wy)
                if d < bd:
                    best, bd = i, d
            if best is None:
                tr = Track(wx, wy)
                # a fragment of a person already known to move (fog drops beams) keeps the class
                if any(o.dyn is True and math.hypot(o.x - wx, o.y - wy) < 1.0 for o in self.tracks):
                    tr.dyn = True
                self.tracks.append(tr)
                used.add(len(self.tracks) - 1)
            else:
                tr = self.tracks[best]
                used.add(best)
                tr.x, tr.y = wx, wy
                tr.hist.append((wx, wy))
                tr.seen.append(1)
            out.append((pts, tr))
        robot_still = abs(self.v_odom) < 0.02
        for i, tr in enumerate(self.tracks):
            if i not in used:
                tr.seen.append(0)
                tr.hist.append(tr.hist[-1])
            tr.hist = tr.hist[-11:]
            tr.seen = tr.seen[-11:]
            if len(tr.hist) >= 11:
                # a person walks >= 0.8 m in 1 s; the visible arc of a static object shifts less
                moved = math.hypot(tr.hist[-1][0] - tr.hist[0][0], tr.hist[-1][1] - tr.hist[0][1])
                if moved >= 0.6:
                    tr.dyn = True
                    tr.still = 0
                elif moved < 0.25:
                    tr.still = tr.still + 1 if robot_still else 0
                    if tr.dyn is None and sum(tr.seen) >= 9:
                        tr.dyn = False
                    elif tr.still > 30:
                        tr.dyn = False  # nobody walks away from a standing platform: an object
        self.tracks = [tr for tr in self.tracks if sum(tr.seen[-6:]) > 0]
        return [(pts, tr) for pts, tr in out if sum(tr.seen[-4:]) >= 3]

    def _gap(self, r, a, b):
        return math.hypot(r[a] * self.cos_rel[a] - r[b] * self.cos_rel[b],
                          r[a] * self.sin_rel[a] - r[b] * self.sin_rel[b])

    @staticmethod
    def _is_wall(pts):
        """Longer than a person and straight: an unmapped wall or fence, not people."""
        if len(pts) < 3:
            return False
        c = pts - pts.mean(axis=0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        along = c @ vt[0]
        across = c @ vt[1]
        # robust: the end face of a fence or a stray return must not make it "not straight"
        return float(along.max() - along.min()) > 1.0 and float(np.percentile(np.abs(across), 80)) < 0.1

    @staticmethod
    def _on_wall(pts, walls):
        """A short cluster that continues the line of an unmapped wall next to it."""
        for w in walls:
            if float(np.min(np.hypot(pts[:, None, 0] - w[None, :, 0], pts[:, None, 1] - w[None, :, 1]))) > 0.6:
                continue
            c = w.mean(axis=0)
            _, _, vt = np.linalg.svd(w - c, full_matrices=False)
            if float(np.percentile(np.abs((pts - c) @ vt[1]), 80)) < 0.15:
                return True
        return False

    def safety_limit(self, obs, v_now):
        """Returns (v_limit, stop_reason or None)."""
        v_lim = self.v_top
        stop = None
        d_stop = self.R + v_now * v_now / 2.0 + 0.6
        found = self.perceive(obs)
        walls = [pts for pts, _ in found if self._is_wall(pts)]
        for pts, tr in found:
            ahead = (pts[:, 0] > 0) & (pts[:, 0] < d_stop) & (np.abs(pts[:, 1]) < self.R + 0.35)
            if ahead.any():
                stop = "obstacle ahead"
            dist = float(np.hypot(pts[:, 0], pts[:, 1]).min())
            if self._is_wall(pts) or self._on_wall(pts, walls):
                continue  # a wall or a fence the map does not know, or a piece of one
            if tr.dyn is not False and dist < 3.2:
                stop = stop or "person near"
            elif tr.dyn is not False and dist < 6.0:
                v_lim = min(v_lim, 0.25)
        # any return inside the swept footprint within the braking distance, map or not:
        # a wrong pose estimate must not hide a real wall
        r = np.asarray(obs["lidar"]["ranges"], dtype=float)
        reach = self.R + v_now * v_now / 2.4 + v_now * self.dt + 0.25
        with np.errstate(invalid="ignore"):
            px, py = r * self.cos_rel, r * self.sin_rel
            close = np.isfinite(r) & (px > 0) & (px < reach) & (np.abs(py) < self.R + 0.1)
        # three adjacent beams: a real obstacle, not a snowflake
        if (close & np.roll(close, 1) & np.roll(close, -1)).any():
            stop = stop or "too close"
        return v_lim, stop

    # ----------------------------------------------------------------- guidance
    def zone_limit(self, x, y):
        lim = self.v_top
        for poly, vm in self.zones:
            if inside(x, y, poly):
                lim = min(lim, vm - 0.1)
        return lim

    def closest_segment(self):
        best, bd = 0, math.inf
        for i in range(len(self.path) - 1):
            (bx, by), (ax, ay) = self.path[i], self.path[i + 1]
            ex, ey = ax - bx, ay - by
            L2 = ex * ex + ey * ey
            u = max(0.0, min(1.0, ((self.x - bx) * ex + (self.y - by) * ey) / L2)) if L2 > 0 else 0.0
            d = math.hypot(bx + u * ex - self.x, by + u * ey - self.y)
            if d < bd - 1e-6:
                best, bd = i, d
        return best

    def follow(self):
        """Pure pursuit on the reference path. Returns (v, w, remaining distance)."""
        P = self.path
        # advance along segments while the projection passed the segment end
        while self.seg < len(P) - 2:
            ax, ay = P[self.seg + 1]
            bx, by = P[self.seg]
            ex, ey = ax - bx, ay - by
            L2 = ex * ex + ey * ey
            u = ((self.x - bx) * ex + (self.y - by) * ey) / L2 if L2 > 0 else 1.0
            if u >= 1.0:
                self.seg += 1
            else:
                break
        bx, by = P[self.seg]
        ax, ay = P[self.seg + 1]
        ex, ey = ax - bx, ay - by
        L = math.hypot(ex, ey)
        u = max(0.0, min(1.0, ((self.x - bx) * ex + (self.y - by) * ey) / (L * L))) if L > 0 else 1.0
        remaining = (1.0 - u) * L + sum(math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1])
                                        for i in range(self.seg + 1, len(P) - 1))
        look = 1.5
        # lookahead point along the path
        tx, ty = P[-1]
        acc = -u * L
        for i in range(self.seg, len(P) - 1):
            sx, sy = P[i]
            nx, ny = P[i + 1]
            sl = math.hypot(nx - sx, ny - sy)
            if acc + sl >= look:
                f = (look - acc) / sl if sl > 0 else 0.0
                tx, ty = sx + f * (nx - sx), sy + f * (ny - sy)
                break
            acc += sl
        gx, gy = P[-1]
        dgoal = math.hypot(gx - self.x, gy - self.y)
        if remaining < 1.5:
            tx, ty = gx, gy
        alpha = wrap(math.atan2(ty - self.y, tx - self.x) - self.th)
        if dgoal < 0.03 or (self.seg == len(P) - 2 and remaining < 0.03):
            return 0.0, 0.0, 0.0
        if abs(alpha) > 0.8:
            return 0.0, max(-0.8, min(0.8, 1.5 * alpha)), remaining
        v = self.v_top
        if abs(alpha) > 0.35:
            v = 0.5
        v = min(v, math.sqrt(2 * 0.4 * max(0.0, min(remaining, dgoal + 0.05) - 0.02)) + 0.03)
        lx = max(0.5, math.hypot(tx - self.x, ty - self.y))
        w = 2.0 * v * math.sin(alpha) / lx if v > 0.05 else 1.5 * alpha
        w = max(-self.w_top, min(self.w_top, w))
        return v, w, remaining

    # ---------------------------------------------------------------------- step
    def step(self, obs):
        self.localize(obs)
        m = obs.get("mission")
        if m is None:
            return self.out(0.0, 0.0, "arrived" if self.arrived else "waiting")
        if self.mission != m["id"]:
            self.mission = m["id"]
            self.path = [tuple(p) for p in m["reference_path"]]
            self.seg = self.closest_segment()
            self.arrived = False
        if self.truth is None:
            self.dock_snap(obs, m["goal"])
        if self.arrived:
            return self.out(0.0, 0.0, "arrived")
        v, w, remaining = self.follow()
        c, s = math.cos(self.th), math.sin(self.th)
        v = min(v, self.zone_limit(self.x, self.y), self.zone_limit(self.x + 3 * c, self.y + 3 * s),
                self.zone_limit(self.x - 1.5 * c, self.y - 1.5 * s))
        v_lim, stop = self.safety_limit(obs, abs(self.v_odom))
        if stop == "person near":
            self.near_hold = 10
        elif stop is None and self.near_hold > 0:
            self.near_hold -= 1  # a person's track flickering out (fog) does not release the stop
            stop = "person near"
        self.near_wait = self.near_wait + 1 if stop == "person near" else 0
        if stop == "person near" and self.near_wait > 80:
            stop = None  # someone standing beside the path for 8 s: pass slowly
            v_lim = min(v_lim, 0.25)
        if stop and remaining > 0.3:
            v = 0.0
            if stop != "obstacle ahead":
                w = 0.0  # turning on the spot is safe for a round platform: it may clear the corridor
        else:
            v = min(v, v_lim)
        moving = abs(self.v_odom) > 0.05 or v > 0.05 or abs(w) > 0.05
        if v == 0.0 and w == 0.0 and remaining <= 0.05 and abs(self.v_odom) < 0.02:
            self.arrived = True
            return self.out(0.0, 0.0, "arrived")
        status = "moving" if moving or not stop else "waiting"
        self.note = stop or ""
        return self.out(v, w, status)

    def out(self, v, w, status):
        return {"v": float(v), "w": float(w), "status": status,
                "pose_est": [self.x, self.y, self.th], "note": self.note}
