"""Scenario schema amr-1.0: loading and validation with short, located messages."""
import math
from pathlib import Path

from amrsim import SCHEMA
from amrsim.util import AmrsimError, read_json

ZONE_TYPES = ("gnss_shadow", "speed_limit", "forbidden", "people_area")
EVENT_TYPES = ("object_dropped", "gnss_outage", "fog_bank")


class _V:
    def __init__(self, src):
        self.src = src

    def fail(self, where, msg):
        raise AmrsimError("%s: %s: %s" % (self.src, where, msg))

    def obj(self, d, where, required=()):
        if not isinstance(d, dict):
            self.fail(where, "expected an object")
        for k in required:
            if k not in d:
                self.fail(where, "missing field '%s'" % k)
        return d

    def num(self, v, where, lo=-math.inf, hi=math.inf):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.fail(where, "expected a finite number")
        try:
            f = float(v)
        except OverflowError:
            self.fail(where, "expected a finite number")
        if not math.isfinite(f):
            self.fail(where, "expected a finite number")
        if not lo <= f <= hi:
            self.fail(where, "value %s out of range [%s, %s]" % (v, lo, hi))
        return f

    def boolean(self, v, where):
        if not isinstance(v, bool):
            self.fail(where, "expected true or false")
        return v

    def string(self, v, where):
        if not isinstance(v, str) or not v:
            self.fail(where, "expected a non-empty string")
        return v

    def xy(self, v, where):
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            self.fail(where, "expected [x, y]")
        return [self.num(v[0], where + "[0]"), self.num(v[1], where + "[1]")]

    def polyline(self, v, where, min_len):
        if not isinstance(v, list) or len(v) < min_len:
            self.fail(where, "expected a list of at least %d [x, y] points" % min_len)
        return [self.xy(p, "%s[%d]" % (where, i)) for i, p in enumerate(v)]

    def lst(self, v, where):
        if not isinstance(v, list):
            self.fail(where, "expected a list")
        return v


def validate(sc, src="scenario"):
    """Validate a parsed scenario dict in place; return it. Raises AmrsimError."""
    V = _V(src)
    V.obj(sc, "top level", ("schema", "name", "duration_s", "map", "start", "missions"))
    if sc["schema"] != SCHEMA:
        V.fail("schema", "expected '%s', got '%s'" % (SCHEMA, sc["schema"]))
    V.string(sc["name"], "name")
    V.num(sc["duration_s"], "duration_s", 1.0, 3600.0)
    if "dt" in sc and abs(V.num(sc["dt"], "dt") - 0.1) > 1e-12:
        V.fail("dt", "only 0.1 is supported")
    for flag in ("hidden", "provide_detections"):
        if flag in sc:
            V.boolean(sc[flag], flag)
    weather = V.obj(sc.get("weather", {}), "weather")
    if "snow" in weather:
        V.boolean(weather["snow"], "weather.snow")

    m = V.obj(sc["map"], "map", ("drivable", "buildings", "points", "zones"))
    for i, p in enumerate(V.lst(m["drivable"], "map.drivable")):
        V.polyline(p, "map.drivable[%d]" % i, 3)
    bids = set()
    for i, b in enumerate(V.lst(m["buildings"], "map.buildings")):
        w = "map.buildings[%d]" % i
        V.obj(b, w, ("id", "polygon"))
        V.string(b["id"], w + ".id")
        if b["id"] in bids:
            V.fail(w + ".id", "duplicate id '%s'" % b["id"])
        bids.add(b["id"])
        V.polyline(b["polygon"], w + ".polygon", 3)
    points = V.obj(m["points"], "map.points")
    if not points:
        V.fail("map.points", "at least one point is required")
    for name, p in points.items():
        w = "map.points.%s" % name
        V.obj(p, w, ("x", "y", "heading", "tol"))
        V.num(p["x"], w + ".x")
        V.num(p["y"], w + ".y")
        V.num(p["heading"], w + ".heading", -2 * math.pi, 2 * math.pi)
        V.num(p["tol"], w + ".tol", 0.01, 5.0)
    for i, z in enumerate(V.lst(m["zones"], "map.zones")):
        w = "map.zones[%d]" % i
        V.obj(z, w, ("id", "type", "polygon"))
        if z["type"] not in ZONE_TYPES:
            V.fail(w + ".type", "expected one of %s" % ", ".join(ZONE_TYPES))
        V.polyline(z["polygon"], w + ".polygon", 3)
        if z["type"] == "speed_limit":
            if "v_max" not in z:
                V.fail(w, "speed_limit zone needs v_max")
            V.num(z["v_max"], w + ".v_max", 0.05, 1.39)
    V.lst(m.get("gates", []), "map.gates")
    V.lst(m.get("crossing", []), "map.crossing")

    st = V.obj(sc["start"], "start", ("x", "y", "theta"))
    for k in ("x", "y", "theta"):
        V.num(st[k], "start." + k)

    missions = V.lst(sc["missions"], "missions")
    if not missions:
        V.fail("missions", "at least one mission is required")
    mids = set()
    for i, ms in enumerate(missions):
        w = "missions[%d]" % i
        V.obj(ms, w, ("id", "from", "to", "deadline_s", "reference_path"))
        V.string(ms["id"], w + ".id")
        if ms["id"] in mids:
            V.fail(w + ".id", "duplicate id '%s'" % ms["id"])
        mids.add(ms["id"])
        for k in ("from", "to"):
            V.string(ms[k], w + "." + k)
            if ms[k] not in points:
                V.fail(w + "." + k, "unknown point '%s'" % ms[k])
        V.num(ms["deadline_s"], w + ".deadline_s", 1.0, 3600.0)
        rp = V.polyline(ms["reference_path"], w + ".reference_path", 2)
        if sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(rp, rp[1:])) < 0.5:
            V.fail(w + ".reference_path", "path length must be at least 0.5 m")

    patch_ids = set()
    for i, pt in enumerate(V.lst(sc.get("map_patches", []), "map_patches")):
        w = "map_patches[%d]" % i
        V.obj(pt, w, ("id", "op"))
        V.string(pt["id"], w + ".id")
        if pt["id"] in patch_ids:
            V.fail(w + ".id", "duplicate id '%s'" % pt["id"])
        patch_ids.add(pt["id"])
        if pt["op"] == "add":
            V.polyline(pt.get("polygon"), w + ".polygon", 3)
            if pt["id"] in bids:
                V.fail(w + ".id", "added patch id '%s' clashes with a building" % pt["id"])
        elif pt["op"] == "remove":
            if pt["id"] not in bids:
                V.fail(w + ".id", "no building '%s' to remove" % pt["id"])
        else:
            V.fail(w + ".op", "expected 'add' or 'remove'")

    pids = set()
    for i, pd in enumerate(V.lst(sc.get("pedestrians", []), "pedestrians")):
        w = "pedestrians[%d]" % i
        V.obj(pd, w, ("id", "waypoints", "speed"))
        V.string(pd["id"], w + ".id")
        if pd["id"] in pids:
            V.fail(w + ".id", "duplicate id '%s'" % pd["id"])
        pids.add(pd["id"])
        V.polyline(pd["waypoints"], w + ".waypoints", 1)
        V.num(pd["speed"], w + ".speed", 0.1, 3.0)
        for flag in ("inattentive", "loop"):
            if flag in pd:
                V.boolean(pd[flag], w + "." + flag)
        if "t_start" in pd:
            V.num(pd["t_start"], w + ".t_start", 0.0)

    for i, ev in enumerate(V.lst(sc.get("events", []), "events")):
        w = "events[%d]" % i
        V.obj(ev, w, ("type",))
        if ev["type"] not in EVENT_TYPES:
            V.fail(w + ".type", "expected one of %s" % ", ".join(EVENT_TYPES))
        if ev["type"] == "object_dropped":
            V.obj(ev, w, ("t", "x", "y", "r"))
            V.num(ev["t"], w + ".t", 0.0)
            V.num(ev["x"], w + ".x")
            V.num(ev["y"], w + ".y")
            V.num(ev["r"], w + ".r", 0.05, 5.0)
        else:
            V.obj(ev, w, ("t1", "t2"))
            if V.num(ev["t1"], w + ".t1", 0.0) >= V.num(ev["t2"], w + ".t2", 0.0):
                V.fail(w, "t1 must be less than t2")
    return sc


def load_scenario(path):
    p = Path(path)
    return validate(read_json(p), src=str(p))
