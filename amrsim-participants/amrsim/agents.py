"""Pedestrians: waypoint walkers around the platform (SPEC section 6).

- Circles r = 0.3 m, speed from the scenario (0.8-1.5 m/s), waypoints in order,
  optionally looping; without loop a pedestrian leaves the world at the last one.
- Attentive: stops while a moving platform (|v| > 0.05) is within 4 m ahead.
- Inattentive: never stops for the platform.
- Everybody walks around a standing platform (|v| <= 0.05), keeping the centre
  outside r_robot + r_ped + 0.3 = 1.5 m; if its target is inside that circle,
  it waits.
Deterministic: no random draws.
"""
import math

from amrsim.params import CONFIG, DT

YIELD_DIST = 4.0
STAND_V = 0.05
MAX_WAIT_TICKS = 20   # a pedestrian gives up a waypoint blocked by the platform after 2 s


class Pedestrian:
    __slots__ = ("id", "wps", "speed", "inattentive", "loop", "t_start", "x", "y", "k", "state", "vx", "vy",
                 "blocked")

    def __init__(self, spec):
        self.id = spec["id"]
        self.wps = [tuple(map(float, w)) for w in spec["waypoints"]]
        self.speed = float(spec["speed"])
        self.inattentive = bool(spec.get("inattentive", False))
        self.loop = bool(spec.get("loop", True))
        self.t_start = float(spec.get("t_start", 0.0))
        self.x, self.y = self.wps[0]
        self.k = 1 % len(self.wps)
        self.state = "walking" if self.t_start <= 0.0 else "pending"   # pending -> walking -> gone
        self.vx = self.vy = 0.0
        self.blocked = 0  # ticks spent waiting for a waypoint covered by the standing platform


class Crowd:
    def __init__(self, specs, rng=None):
        self.peds = [Pedestrian(s) for s in specs]
        self.r = CONFIG["pedestrian"]["radius"]
        self.robot_r = CONFIG["robot"]["radius"]
        self.contact_d = self.r + self.robot_r
        self.avoid_d = self.contact_d + 0.3

    def active(self):
        return [p for p in self.peds if p.state == "walking"]

    def xy(self):
        return [(p.x, p.y) for p in self.peds if p.state == "walking"]

    def step(self, t, robot, world=None):
        """Move everybody one tick after the robot moved; return indices (in xy order) in contact."""
        standing = abs(robot.v) <= STAND_V
        for p in self.peds:
            if p.state == "pending" and t + 1e-9 >= p.t_start:
                # appear only where the platform cannot hit you: 4 m from a moving one, 1.5 m otherwise
                need = self.avoid_d if standing else YIELD_DIST
                if math.hypot(p.x - robot.x, p.y - robot.y) >= need:
                    p.state = "walking"
            if p.state != "walking":
                continue
            x0, y0 = p.x, p.y
            self._walk(p, robot, standing)
            p.vx, p.vy = (p.x - x0) / DT, (p.y - y0) / DT
        contacts = []
        for i, p in enumerate(self.active()):
            dx, dy = p.x - robot.x, p.y - robot.y
            d = math.hypot(dx, dy)
            if d < self.contact_d - 1e-9:
                if d < 1e-9:
                    dx, dy, d = 1.0, 0.0, 1.0
                p.x = robot.x + dx / d * self.contact_d
                p.y = robot.y + dy / d * self.contact_d
                contacts.append(i)
            elif d <= self.contact_d + 1e-6:
                contacts.append(i)
        return contacts

    def _walk(self, p, robot, standing):
        tx, ty = p.wps[p.k]
        dx, dy = tx - p.x, ty - p.y
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            self._next(p)
            return
        ux, uy = dx / dist, dy / dist
        step = min(p.speed * DT, dist)
        rx, ry = robot.x - p.x, robot.y - p.y
        dr = math.hypot(rx, ry)
        if not standing:
            if not p.inattentive and dr < YIELD_DIST and (ux * rx + uy * ry) > 0.0:
                return  # yield: wait for the moving platform
            nx, ny = p.x + ux * step, p.y + uy * step
        else:
            nx, ny = p.x + ux * step, p.y + uy * step
            if math.hypot(nx - robot.x, ny - robot.y) < self.avoid_d:
                if math.hypot(tx - robot.x, ty - robot.y) < self.avoid_d:
                    p.blocked += 1
                    if p.blocked > MAX_WAIT_TICKS:
                        p.blocked = 0
                        self._next(p)  # give up this waypoint, walk on to the next one
                    return
                if dr < 1e-9:
                    return
                # slide along the circle around the platform, towards the target side
                ox, oy = -rx / dr, -ry / dr          # outward normal (from robot to pedestrian)
                t1x, t1y = -oy, ox
                if t1x * ux + t1y * uy < 0:
                    t1x, t1y = -t1x, -t1y
                nx, ny = p.x + t1x * step, p.y + t1y * step
                dd = math.hypot(nx - robot.x, ny - robot.y)
                if dd < self.avoid_d:
                    nx = robot.x + (nx - robot.x) / dd * self.avoid_d
                    ny = robot.y + (ny - robot.y) / dd * self.avoid_d
        p.x, p.y = nx, ny
        if math.hypot(tx - p.x, ty - p.y) < 1e-6:
            self._next(p)

    def _next(self, p):
        p.k += 1
        if p.k >= len(p.wps):
            if p.loop:
                p.k = 0
            else:
                p.state = "gone"
