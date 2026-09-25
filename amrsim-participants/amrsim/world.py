"""World truth: static geometry (map plus patches), events, robot dynamics.

Nothing in this module is ever sent to the controller process.
"""
import math

import numpy as np

from amrsim.geometry import (as_poly, point_segment_distance, points_in_polygon, polygon_segments,
                             segments_aabb, segments_near, wrap_angle)
from amrsim.params import CONFIG, DT


class Robot:
    __slots__ = ("x", "y", "th", "v", "w", "vw")

    def __init__(self, x, y, th):
        self.x, self.y, self.th = float(x), float(y), float(th)
        self.v = 0.0   # platform speed (truth)
        self.w = 0.0
        self.vw = 0.0  # wheel speed: follows the command law; equals v unless blocked


class World:
    def __init__(self, scenario):
        m = scenario["map"]
        self.drivable = [as_poly(p) for p in m["drivable"]]
        blds = {b["id"]: as_poly(b["polygon"]) for b in m["buildings"]}
        for patch in scenario.get("map_patches", []):
            if patch["op"] == "remove":
                blds.pop(patch["id"], None)
            else:
                blds[patch["id"]] = as_poly(patch["polygon"])
        self.obstacles = blds
        segs = [polygon_segments(p) for p in blds.values()]
        self.segs = np.vstack(segs) if segs else np.empty((0, 4))
        self.aabb = segments_aabb(self.segs)
        self.obstacle_aabb = {k: (p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())
                              for k, p in blds.items()}
        self.zones = {}
        for z in m["zones"]:
            self.zones.setdefault(z["type"], []).append((z, as_poly(z["polygon"])))
        events = scenario.get("events", [])
        self.pending_drops = sorted((e for e in events if e["type"] == "object_dropped"),
                                    key=lambda e: e["t"])
        self.outages = [(e["t1"], e["t2"]) for e in events if e["type"] == "gnss_outage"]
        self.fogs = [(e["t1"], e["t2"]) for e in events if e["type"] == "fog_bank"]
        self.objects = np.empty((0, 3))
        self.snow = bool(scenario.get("weather", {}).get("snow", False))
        self.r = CONFIG["robot"]["radius"]

    # --- queries -------------------------------------------------------------
    def in_drivable(self, x, y):
        return any(points_in_polygon([[x, y]], p)[0] for p in self.drivable)

    def _in_zone(self, ztype, x, y):
        for z, poly in self.zones.get(ztype, ()):
            if points_in_polygon([[x, y]], poly)[0]:
                return z
        return None

    def zone_state(self, x, y):
        vmax = None
        for z, poly in self.zones.get("speed_limit", ()):
            if points_in_polygon([[x, y]], poly)[0]:
                vmax = z["v_max"] if vmax is None else min(vmax, z["v_max"])
        return {
            "drivable": self.in_drivable(x, y),
            "forbidden": self._in_zone("forbidden", x, y) is not None,
            "vmax": vmax,
            "shadow": self._in_zone("gnss_shadow", x, y) is not None,
        }

    def fog(self, t):
        return any(a <= t < b for a, b in self.fogs)

    def outage(self, t):
        return any(a <= t < b for a, b in self.outages)

    def inside_obstacle(self, x, y):
        for k, p in self.obstacles.items():
            x0, y0, x1, y1 = self.obstacle_aabb[k]
            if x0 <= x <= x1 and y0 <= y <= y1 and points_in_polygon([[x, y]], p)[0]:
                return True
        return False

    def static_gap(self, x, y, r):
        """Clearance between a circle and buildings, patches, dropped objects (<0 is overlap)."""
        gap = math.inf
        near = segments_near(self.segs, self.aabb, x, y, r + 3.0)
        if len(near):
            gap = float(point_segment_distance(x, y, near).min()) - r
        if len(self.objects):
            d = np.hypot(self.objects[:, 0] - x, self.objects[:, 1] - y) - self.objects[:, 2] - r
            gap = min(gap, float(d.min()))
        if gap < 3.0 and self.inside_obstacle(x, y):
            gap = -r
        return gap

    def lidar_segments(self, x, y, reach):
        return segments_near(self.segs, self.aabb, x, y, reach)

    # --- events --------------------------------------------------------------
    def update_events(self, t, robot, ped_xy):
        """Activate dropped objects whose time has come and whose spot is free."""
        still = []
        for e in self.pending_drops:
            if e["t"] > t + 1e-9:
                still.append(e)
                continue
            # never drop in front of a platform that can no longer stop before it
            dx, dy = e["x"] - robot.x, e["y"] - robot.y
            v = abs(robot.vw)
            approaching = robot.vw * (dx * math.cos(robot.th) + dy * math.sin(robot.th)) > 0
            p = CONFIG["robot"]
            margin = 0.1 + ((v * v / (2 * p["estop_decel"]) + v * DT + 0.2) if approaching else 0.0)
            clear = math.hypot(dx, dy) > e["r"] + self.r + margin
            for px, py in ped_xy:
                if math.hypot(e["x"] - px, e["y"] - py) <= e["r"] + 0.4:
                    clear = False
            if clear:
                self.objects = np.vstack([self.objects, [e["x"], e["y"], e["r"]]])
            else:
                still.append(e)  # postpone until the spot is free
        self.pending_drops = still


def _speed_law(v, v_t, estop, p):
    if estop:
        target, rate = 0.0, p["estop_decel"]
    elif v * v_t < 0 or abs(v_t) < abs(v):
        target, rate = (v_t if v * v_t >= 0 else 0.0), p["decel"]
    else:
        target, rate = v_t, p["accel"]
    return v + min(max(target - v, -rate * DT), rate * DT)


def step_robot(robot, cmd_v, cmd_w, estop, world, ped_xy, ped_r):
    """Advance the robot one tick. Returns wheel increments and contact info.

    Wheel increments are what the wheels turned (body frame of the start pose).
    While the platform is blocked by an obstacle the wheels keep turning as
    commanded (they slip), so odometry does not reveal the contact directly.
    """
    p = CONFIG["robot"]
    v_t = min(max(cmd_v, p["v_min"]), p["v_max"])
    w_t = min(max(cmd_w, -p["w_max"]), p["w_max"])
    vw = robot.vw
    vw_new = _speed_law(vw, v_t, estop, p)
    vw_avg = 0.5 * (vw + vw_new)
    half = 0.5 * w_t * DT
    th_mid = robot.th + half
    nx = robot.x + vw_avg * math.cos(th_mid) * DT
    ny = robot.y + vw_avg * math.sin(th_mid) * DT
    wheel = (vw_avg * DT * math.cos(half), vw_avg * DT * math.sin(half), w_t * DT)

    blocked_static = False
    hit_peds = []
    if vw_avg != 0.0:
        r = world.r
        g_new = world.static_gap(nx, ny, r)
        if g_new < 0.0 and g_new < world.static_gap(robot.x, robot.y, r):
            blocked_static = True
        for i, (px, py) in enumerate(ped_xy):
            d_new = math.hypot(nx - px, ny - py)
            if d_new < r + ped_r and d_new < math.hypot(robot.x - px, robot.y - py):
                hit_peds.append(i)
    if blocked_static or hit_peds:
        robot.v = 0.0          # the platform stands, the wheels slip
    else:
        robot.x, robot.y = nx, ny
        robot.v = vw_new
    robot.th = wrap_angle(robot.th + w_t * DT)
    robot.vw = vw_new
    robot.w = w_t
    return wheel, blocked_static, hit_peds
