"""Scenario score from a run log (SPEC section 8). Pure function of the records.

Blocks safety, traffic rules and pose honesty are credited only in a scenario where at
least one mission was delivered; with no delivery the scenario scores 0 and those blocks
are reported but marked in not_counted_blocks.

Every rule works on per-tick truth written by the simulator: true speed |v|,
clearance to the nearest person (hum) and to any obstacle (obj), zone flags,
reported status and pose estimate. Episodes merge ticks whose gap is shorter
than the 2 s hysteresis.
"""
import math

import numpy as np

from amrsim.params import CONFIG

HYST_TICKS = 20          # 2 s at 0.1 s
V_REF = 1.39

MAX = {"delivery": 40.0, "efficiency": 15.0, "safety": 25.0, "rules": 10.0, "pose": 10.0,
       "collisions": 0.0}
# Credited only when the platform delivered at least one mission in the scenario: standing
# still must not earn points for being safe and law-abiding (dress rehearsal 22.09).
PASSIVE_BLOCKS = ("safety", "rules", "pose")

RULES = {
    "proximity_per_s": -2.0,     # person < 3 m and |v| > 0.28
    "close_pass": -10.0,         # person < 0.5 m and |v| > 0
    "contact_standing": -10.0,   # contact, platform not moving in the last 1 s
    "out_of_drivable": -3.0,
    "forbidden_zone": -5.0,
    "overspeed": -2.0,
    "pose_error": -3.0,          # error > 1 m while moving longer than 5 s
    "status_mismatch": -2.0,     # status != moving at |v| > 0.05 longer than 1 s
    "estop_no_object": -1.0,     # estop with nothing within 1.5 m
    "collision": -30.0,
}
THRESH = {"prox_gap": 3.0, "prox_v": 0.28, "close_gap": 0.5, "moving_v": 0.05, "pose_err": 1.0,
          "pose_ticks": 50, "status_ticks": 10, "estop_gap": 1.5, "contact_v": 0.1,
          "contact_window": 10, "overspeed_tol": 0.05}


def episodes(mask, hyst=HYST_TICKS):
    """Indices of True ticks grouped: a gap of >= hyst False ticks starts a new episode."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    out = []
    start = prev = idx[0]
    n = 1
    for i in idx[1:]:
        if i - prev - 1 >= hyst:
            out.append((int(start), int(prev), n))
            start, n = i, 0
        prev = i
        n += 1
    out.append((int(start), int(prev), n))
    return out


def _arr(ticks, key, default=np.nan):
    return np.array([default if r.get(key) is None else r[key] for r in ticks], dtype=float)


def split_records(records):
    if any(not isinstance(r, dict) for r in records):
        raise ValueError("every log line must be a JSON object")
    header = next((r for r in records if r.get("type") == "header"), None)
    ticks = [r for r in records if r.get("type") == "tick"]
    end = next((r for r in records if r.get("type") == "end"), None)
    if header is None:
        raise ValueError("log has no header")
    if end is None:
        raise ValueError("log has no end record (run incomplete or log truncated)")
    return header, ticks, end


def mission_outcomes(header, ticks, hold=10):
    """Recompute deliveries from ticks: first run of `hold` arrived ticks per mission."""
    pts = header["points"]
    res = []
    for m in header["missions"]:
        idx = [i for i, r in enumerate(ticks) if r.get("m") == m["id"]]
        out = {"id": m["id"], "delivered": False, "t_start": None, "t_arrival": None,
               "time_s": None, "ratio": None, "efficiency": 0.0, "reason": "not_started"}
        if not idx:
            res.append(out)
            continue
        t_start = ticks[idx[0]]["t"]
        out["t_start"] = t_start
        out["reason"] = "not_finished"
        goal = pts[m["to"]]
        origin = pts[m["from"]]
        L = float(m["reference_length_m"])
        if not L > 0:
            raise ValueError("mission %s: reference_length_m must be > 0" % m["id"])
        pickup = CONFIG["mission"]["pickup_radius"]
        picked = False
        run = []
        for i in idx:
            r = ticks[i]
            if math.hypot(r["x"] - origin["x"], r["y"] - origin["y"]) < pickup:
                picked = True
            if r.get("st") == "arrived":
                run.append(i)
            else:
                run = []
            if r["t"] - t_start > m["deadline_s"] + 1e-9:
                out["reason"] = "timeout"
                break
            if len(run) >= hold:
                ok = all(math.hypot(ticks[j]["x"] - goal["x"], ticks[j]["y"] - goal["y"]) < goal["tol"]
                         for j in run[:hold])
                out["t_arrival"] = ticks[run[0]]["t"]
                out["reason"] = ("delivered" if ok else "off_target") if picked else "not_picked_up"
                if ok and picked:
                    out["delivered"] = True
                    t_mis = out["t_arrival"] - t_start
                    t_ref = L / V_REF * 1.25
                    out["time_s"] = round(t_mis, 1)
                    out["ratio"] = round(t_mis / t_ref, 4)
                    out["efficiency"] = min(1.0, max(0.0, 2.0 - t_mis / t_ref))
                break
        res.append(out)
    return res


def score_records(records):
    header, ticks, end = split_records(records)
    t = _arr(ticks, "t")
    x = _arr(ticks, "x")
    y = _arr(ticks, "y")
    v = np.abs(_arr(ticks, "v", 0.0))
    hum = _arr(ticks, "hum", np.inf)
    obj = _arr(ticks, "obj", np.inf)
    drv = _arr(ticks, "drv", 1.0)
    fbd = _arr(ticks, "fbd", 0.0)
    vmax = _arr(ticks, "vmax", np.nan)
    coll = _arr(ticks, "coll", 0.0)
    cont = _arr(ticks, "cont", 0.0)
    st = [r.get("st") for r in ticks]
    pe = [r.get("pe") for r in ticks]
    err = np.array([math.hypot(p[0] - xx, p[1] - yy) if p is not None and len(p) >= 2 else np.inf
                    for p, xx, yy in zip(pe, x, y)], dtype=float)

    eps = []

    def add(kind, i0, i1, cost, block):
        eps.append({"type": kind, "block": block, "t_start": float(t[i0]), "t_end": float(t[i1]),
                    "x": round(float(x[i0]), 2), "y": round(float(y[i0]), 2), "cost": round(cost, 3)})
        return cost

    # missions
    outcomes = mission_outcomes(header, ticks)
    n = max(1, len(outcomes))
    delivery = MAX["delivery"] * sum(o["delivered"] for o in outcomes) / n
    efficiency = MAX["efficiency"] * sum(o["efficiency"] for o in outcomes) / n

    # safety
    safety = MAX["safety"]
    prox = (hum < THRESH["prox_gap"]) & (v > THRESH["prox_v"])
    for i0, i1, k in episodes(prox):
        safety += add("person_near_fast", i0, i1, RULES["proximity_per_s"] * k * 0.1, "safety")
    close = (hum < THRESH["close_gap"]) & (v > 0.0)
    for i0, i1, _ in episodes(close):
        safety += add("person_close_pass", i0, i1, RULES["close_pass"], "safety")
    fatal = False
    fatal_t = None
    for i0, i1, _ in episodes(cont > 0):
        moving = False
        for i in range(i0, i1 + 1):
            if cont[i] > 0 and v[max(0, i - THRESH["contact_window"]):i + 1].max() > THRESH["contact_v"]:
                moving = True
                fatal_t = fatal_t if fatal_t is not None else float(t[i])
                break
        if moving:
            fatal = True
            add("person_contact_moving", i0, i1, 0.0, "fatal")
        else:
            safety += add("person_contact_standing", i0, i1, RULES["contact_standing"], "safety")

    # traffic rules
    rules = MAX["rules"]
    for i0, i1, _ in episodes(drv < 0.5):
        rules += add("out_of_drivable", i0, i1, RULES["out_of_drivable"], "rules")
    for i0, i1, _ in episodes(fbd > 0.5):
        rules += add("forbidden_zone", i0, i1, RULES["forbidden_zone"], "rules")
    over = ~np.isnan(vmax) & (v > np.nan_to_num(vmax, nan=np.inf) + THRESH["overspeed_tol"])
    for i0, i1, _ in episodes(over):
        rules += add("overspeed", i0, i1, RULES["overspeed"], "rules")

    # pose honesty
    pose = MAX["pose"]
    moving = v > THRESH["moving_v"]
    for i0, i1, k in episodes((err > THRESH["pose_err"]) & moving):
        if k > THRESH["pose_ticks"]:
            pose += add("pose_error", i0, i1, RULES["pose_error"], "pose")
    mism = np.array([s != "moving" for s in st], dtype=bool) & moving
    for i0, i1, k in episodes(mism):
        if k > THRESH["status_ticks"]:
            pose += add("status_mismatch", i0, i1, RULES["status_mismatch"], "pose")
    est = np.array([s == "estop" for s in st], dtype=bool) & (obj >= THRESH["estop_gap"])
    for i0, i1, _ in episodes(est):
        pose += add("estop_no_object", i0, i1, RULES["estop_no_object"], "pose")

    # contacts with objects and buildings
    collisions = 0.0
    for i0, i1, _ in episodes(coll > 0):
        collisions += add("collision", i0, i1, RULES["collision"], "collisions")

    blocks = {"delivery": delivery, "efficiency": efficiency, "safety": safety, "rules": rules,
              "pose": pose, "collisions": collisions}
    blocks = {k: round(float(val), 3) for k, val in blocks.items()}
    deliveries = sum(o["delivered"] for o in outcomes)
    not_counted = [] if deliveries else list(PASSIVE_BLOCKS)
    raw = sum(val for k, val in blocks.items() if k not in not_counted)
    end_reason = end.get("reason") if end else None
    counted = end_reason not in ("wall_limit", "controller_error")
    total = 0.0 if (fatal or not counted or not deliveries) else min(100.0, max(0.0, raw))
    top = sorted((e for e in eps if e["cost"] < 0 or e["block"] == "fatal"),
                 key=lambda e: (e["block"] != "fatal", e["cost"]))[:5]
    return {
        "total": round(total, 2), "raw_sum": round(raw, 3), "fatal": fatal, "fatal_t": fatal_t,
        "counted": counted, "deliveries": int(deliveries), "not_counted_blocks": not_counted,
        "blocks": blocks, "max": MAX, "missions": outcomes, "episodes": eps, "top_episodes": top,
    }
