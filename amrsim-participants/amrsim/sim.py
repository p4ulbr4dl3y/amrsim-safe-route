"""One simulation run: world truth, sensors, missions, per-tick records.

The controller never sees this object; it only gets observe() output (obs),
which is built from sensor models and map information.
"""
import math

import numpy as np

from amrsim.agents import Crowd
from amrsim.params import CONFIG, DT
from amrsim.planner import path_length
from amrsim.sensors import Gnss, Imu, Lidar, Odometry
from amrsim.world import Robot, World, step_robot

STATUSES = ("moving", "arrived", "waiting", "lost", "estop")


class MissionTracker:
    def __init__(self, scenario):
        self.points = scenario["map"]["points"]
        self.missions = scenario["missions"]
        self.i = 0
        self.t_start = 0.0
        self.hold = []
        self.picked = False  # platform was within pickup_radius of the 'from' point during the mission
        self.pickup = CONFIG["mission"]["pickup_radius"]
        self.hold_ticks = int(round(CONFIG["mission"]["arrival_hold_s"] / DT))
        self.results = []
        self.ref_len = [path_length(m["reference_path"]) for m in self.missions]

    def active(self):
        return self.missions[self.i] if self.i < len(self.missions) else None

    def obs(self):
        m = self.active()
        if m is None:
            return None
        p = self.points[m["to"]]
        return {
            "id": m["id"], "index": self.i, "count": len(self.missions),
            "from": m["from"], "to": m["to"],
            "goal": [p["x"], p["y"], p["heading"]], "tol": p["tol"],
            "t_start": round(self.t_start, 1), "deadline_s": m["deadline_s"],
            "reference_path": m["reference_path"],
        }

    def update(self, t, status, x, y):
        """Account one tick; returns a mission-close record or None."""
        m = self.active()
        if m is None:
            return None
        p = self.points[m["to"]]
        f = self.points[m["from"]]
        if math.hypot(x - f["x"], y - f["y"]) < self.pickup:
            self.picked = True
        d = math.hypot(x - p["x"], y - p["y"])
        if status == "arrived":
            self.hold.append((t, d))
        else:
            self.hold = []
        elapsed = t - self.t_start
        res = None
        if elapsed > m["deadline_s"] + 1e-9:
            res = self._close(m, t, "timeout", False)
        elif len(self.hold) >= self.hold_ticks:
            ok = all(dd < p["tol"] for _, dd in self.hold)
            if not self.picked:
                res = self._close(m, t, "not_picked_up", False)
            else:
                res = self._close(m, t, "delivered" if ok else "off_target", ok)
        return res

    def _close(self, m, t, reason, delivered):
        res = {
            "type": "mission", "id": m["id"], "from": m["from"], "to": m["to"],
            "t_start": round(self.t_start, 1), "t_end": round(t, 1),
            "t_arrival": round(self.hold[0][0], 1) if self.hold else None,
            "max_hold_dist": round(max(d for _, d in self.hold), 4) if self.hold else None,
            "deadline_s": m["deadline_s"], "reference_length_m": round(self.ref_len[self.i], 3),
            "delivered": delivered, "reason": reason,
        }
        self.results.append(res)
        self.i += 1
        self.t_start = t + DT
        self.hold = []
        self.picked = False
        return res

    def unfinished(self, t):
        """Close missions that never finished (scenario ended)."""
        out = []
        while self.active() is not None:
            self.t_start = min(self.t_start, t)  # never-started missions: t_start = t_end
            out.append(self._close(self.active(), t, "not_finished", False))
        return out


class Simulation:
    def __init__(self, scenario, seed):
        self.sc = scenario
        ss = np.random.SeedSequence(int(seed) % (2 ** 63))
        g = [np.random.default_rng(s) for s in ss.spawn(6)]
        self.world = World(scenario)
        st = scenario["start"]
        self.robot = Robot(st["x"], st["y"], st["theta"])
        snow = self.world.snow
        self.gnss = Gnss(g[0])
        self.odom = Odometry(g[1], snow)
        self.imu = Imu(g[2])
        self.lidar = Lidar(g[3], snow)
        self.crowd = Crowd(scenario.get("pedestrians", []), g[4])
        self.det_rng = g[5]
        self.missions = MissionTracker(scenario)
        self.ped_r = CONFIG["pedestrian"]["radius"]
        self.k = 0
        self.last_odom = {"dx": 0.0, "dy": 0.0, "dtheta": 0.0}
        self.done = False
        self.end_reason = None
        self.duration = float(scenario["duration_s"])
        self._zs = None

    @property
    def t(self):
        return round(self.k * DT, 6)

    def circles(self):
        pts = self.crowd.xy()
        c = [(x, y, self.ped_r) for x, y in pts]
        if len(self.world.objects):
            c.extend(map(tuple, self.world.objects))
        return np.array(c, dtype=float).reshape(-1, 3)

    def observe(self):
        r = self.robot
        t = self.t
        zs = self.world.zone_state(r.x, r.y)
        self._zs = zs
        blocked = zs["shadow"] or self.world.outage(t)
        fog = self.world.fog(t)
        obs = {
            "t": round(t, 1),
            "lidar": {"ranges": self.lidar.scan(self.world, r.x, r.y, r.th, self.circles(), fog)},
            "odom": dict(self.last_odom),
            "imu": self.imu.step(r.w, r.th),
            "gnss": self.gnss.step(t, r.x, r.y, blocked),
            "mission": self.missions.obs(),
        }
        if self.sc.get("provide_detections"):
            obs["detections"] = self._detections(fog)
        return obs

    def _detections(self, fog):
        """Easy mode only: people and dropped objects in the robot frame, with noise."""
        r = self.robot
        c, s = math.cos(r.th), math.sin(r.th)
        reach = self.lidar.fog_range if fog else self.lidar.max_range
        items = [("person", p.x, p.y, p.vx, p.vy) for p in self.crowd.active()]
        items += [("object", float(ox), float(oy), 0.0, 0.0) for ox, oy, _ in self.world.objects]
        out = []
        for cls, x, y, vx, vy in items:
            dx, dy = x - r.x, y - r.y
            if math.hypot(dx, dy) > reach:
                continue
            n = self.det_rng.normal(0.0, 0.1, 4)
            out.append({"class": cls,
                        "x": round(c * dx + s * dy + n[0], 2), "y": round(-s * dx + c * dy + n[1], 2),
                        "vx": round(c * vx + s * vy + n[2], 2), "vy": round(-s * vx + c * vy + n[3], 2)})
        return out

    def truth_pose(self):
        """Only for the oracle channel (--cheat), never part of obs."""
        return [self.robot.x, self.robot.y, self.robot.th]

    def _gaps(self):
        r = self.robot
        hum = None
        for px, py in self.crowd.xy():
            g = math.hypot(px - r.x, py - r.y) - self.world.r - self.ped_r
            hum = g if hum is None else min(hum, g)
        obj = self.world.static_gap(r.x, r.y, self.world.r)
        if hum is not None:
            obj = min(obj, hum)
        return hum, obj

    def apply(self, cmd):
        """Apply a validated command at time t; return (tick record, extra records)."""
        if self._zs is None:
            raise RuntimeError("observe() must be called before apply()")
        r = self.robot
        t = self.t
        zs = self._zs
        hum, obj = self._gaps()
        m = self.missions.active()
        pe = cmd.get("pose_est")
        rec = {
            "type": "tick", "t": round(t, 1),
            "x": round(r.x, 4), "y": round(r.y, 4), "th": round(r.th, 5),
            "v": round(r.v, 4), "w": round(r.w, 4),
            "cv": round(cmd["v"], 4), "cw": round(cmd["w"], 4), "st": cmd["status"],
            "pe": [round(float(a), 4) for a in pe] if pe is not None else None,
            "m": m["id"] if m else None,
            "drv": int(zs["drivable"]), "fbd": int(zs["forbidden"]), "vmax": zs["vmax"],
            "hum": round(hum, 3) if hum is not None else None,
            "obj": round(obj, 3) if math.isfinite(obj) else None,
        }
        extra = []
        closed = self.missions.update(t, cmd["status"], rec["x"], rec["y"])
        if closed:
            extra.append(closed)
        ped_xy = self.crowd.xy()
        wheel, blocked, hits = step_robot(r, cmd["v"], cmd["w"], cmd["status"] == "estop",
                                          self.world, ped_xy, self.ped_r)
        contacts = set(hits)
        contacts.update(self.crowd.step(t, r, self.world))
        rec["coll"] = int(blocked)
        rec["cont"] = int(bool(contacts))
        if ped_xy:  # positions at the start of the tick, like x, y and hum in the same record
            rec["peds"] = [[round(x, 2), round(y, 2)] for x, y in ped_xy]
        peds = self.crowd.xy()
        self.last_odom = self.odom.step(wheel)
        self.k += 1
        self.world.update_events(self.t, r, peds)
        self._zs = None
        if self.missions.active() is None:
            self._finish("missions_done")
        elif self.t >= self.duration - 1e-9:
            self._finish("time_up")
        return rec, extra

    def _finish(self, reason):
        self.done = True
        self.end_reason = reason

    def close_unfinished(self):
        return self.missions.unfinished(self.t)
