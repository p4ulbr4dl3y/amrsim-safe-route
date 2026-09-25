"""Product probes: known log -> known score, and run determinism.

The known log is synthetic and small (one 50 m mission, 600 ticks) with one or
two episodes of every rule, so each block of SPEC section 8 is exercised.
Expected values were computed by hand; see KNOWN_EXPECTED.
"""
from pathlib import Path

from amrsim import SCHEMA
from amrsim.util import PKG_DIR

PKG_ROOT = PKG_DIR.parent

# Hand computation for known_log_records():
#   delivery   40 (1 of 1 missions)
#   efficiency 15 * (2 - 50 / (50 / 1.39 * 1.25)) = 15 * 0.888 = 13.32
#   safety     25 - 0.2*(20 + 5 + 2) ticks near a person fast - 10 close pass = 9.6
#   rules      10 - 2 overspeed - 2*3 off drivable - 5 forbidden = -3
#   pose       10 - 3 pose error (65 ticks) - 2 status mismatch (15 ticks) - 1 estop = 4
#   collisions -30 * 2 = -60
#   total      clamp(40 + 13.32 + 9.6 - 3 + 4 - 60) = 3.92
KNOWN_EXPECTED = {"delivery": 40.0, "efficiency": 13.32, "safety": 9.6, "rules": -3.0, "pose": 4.0,
                  "collisions": -60.0, "total": 3.92}


def _in(t, a, b):
    return a - 1e-9 <= t < b - 1e-9


def known_log_records(contact_at=None, clean=False):
    """Synthetic run log. contact_at: time of a person contact; clean: no penalty events."""
    hdr = {"type": "header", "schema": SCHEMA, "scenario": "known", "seed": 0, "dt": 0.1,
           "points": {"a": {"x": 0.0, "y": 0.0, "heading": 0.0, "tol": 0.2},
                      "b": {"x": 50.0, "y": 0.0, "heading": 0.0, "tol": 0.2}},
           "missions": [{"id": "m1", "from": "a", "to": "b", "deadline_s": 100.0,
                         "reference_length_m": 50.0}]}
    recs = [hdr]
    for k in range(600):
        t = round(k * 0.1, 1)
        moving = t < 50.0 - 1e-9
        x = t if moving else 50.0
        r = {"type": "tick", "t": t, "x": x, "y": 0.0, "th": 0.0, "v": 1.0 if moving else 0.0,
             "w": 0.0, "st": "moving" if moving else "arrived", "pe": [x, 0.0, 0.0],
             "m": "m1" if t < 51.0 - 1e-9 else None, "drv": 1, "fbd": 0, "vmax": None,
             "hum": None, "obj": 5.0, "coll": 0, "cont": 0}
        if not clean:
            if _in(t, 10.0, 12.0):
                r["hum"] = 2.0
            if _in(t, 20.0, 20.5):
                r["hum"] = 2.5
            if t in (25.0, 26.0):
                r["hum"] = 0.4
            if _in(t, 30.0, 33.0):
                r["vmax"] = 0.8
            if _in(t, 34.0, 34.5) or _in(t, 37.0, 37.5):
                r["drv"] = 0
            if _in(t, 40.0, 40.3):
                r["fbd"] = 1
            if _in(t, 41.0, 47.0) or _in(t, 47.5, 48.0):
                r["pe"] = [x, 1.5, 0.0]
            if _in(t, 44.0, 45.5):
                r["st"] = "waiting"
            if _in(t, 48.0, 48.2):
                r["st"] = "estop"
            if t in (46.0, 46.5, 49.0):
                r["coll"] = 1
        if contact_at is not None and abs(t - contact_at) < 1e-9:
            r["cont"] = 1
            r["hum"] = 0.0
        recs.append(r)
    recs.append({"type": "end", "t": 60.0, "reason": "time_up", "error": None})
    return recs


def probe_scoring():
    """Returns (ok, lines)."""
    from amrsim.scoring import score_records
    lines = []
    ok = True
    res = score_records(known_log_records())
    got = dict(res["blocks"], total=res["total"])
    for k, want in KNOWN_EXPECTED.items():
        good = abs(got[k] - want) < 1e-6
        ok &= good
        lines.append("  %-10s expected %8.2f got %8.2f %s" % (k, want, got[k], "ok" if good else "MISMATCH"))
    clean = score_records(known_log_records(clean=True))["total"]
    moving = score_records(known_log_records(clean=True, contact_at=30.0))
    standing = score_records(known_log_records(clean=True, contact_at=55.0))["total"]
    for name, got_v, want in (("clean", clean, 98.32), ("contact moving", moving["total"], 0.0),
                              ("contact standing", standing, 88.32)):
        good = abs(got_v - want) < 1e-6
        ok &= good
        lines.append("  %-17s expected %6.2f got %6.2f %s" % (name, want, got_v, "ok" if good else "MISMATCH"))
    ok &= moving["fatal"] is True
    return ok, lines


BASELINE = PKG_ROOT / "baseline" / "controller.py"
SCENARIOS = PKG_ROOT / "scenarios"
# Report fields that must be identical between two runs (timings are excluded on purpose)
DETERMINISTIC_KEYS = ("scenario", "scenario_sha", "seed", "ticks", "end_reason", "error", "missions", "score",
                      "controller", "package_hash")


def probe_determinism(scenario="01_clear", seed=3):
    """Two runs of the baseline with the same scenario and seed: same report and same log bytes."""
    import hashlib
    import tempfile
    from amrsim.runner import run_scenario
    scn = SCENARIOS / ("%s.json" % scenario)
    lines = []
    with tempfile.TemporaryDirectory(prefix="amrsim_det_") as d:
        reps, digests = [], []
        ran_ok = True
        for i in range(2):
            lp = Path(d) / ("run%d.jsonl" % i)
            rep = run_scenario(scn, seed=seed, controller_path=BASELINE, log_path=lp)
            if rep["ticks"] == 0 or rep["error"] is not None or rep["end_reason"] != "missions_done":
                ran_ok = False
                lines.append("  run %d did not complete: end %s, error %s" % (i + 1, rep["end_reason"], rep["error"]))
            reps.append({k: rep.get(k) for k in DETERMINISTIC_KEYS})
            digests.append(hashlib.sha256(lp.read_bytes()).hexdigest())
            lines.append("  run %d: %d ticks, total %.2f, log sha256 %s" %
                         (i + 1, rep["ticks"], rep["score"]["total"], digests[-1][:16]))
    same_rep = reps[0] == reps[1]
    same_log = digests[0] == digests[1]
    lines.append("  report fields equal: %s, log bytes equal: %s" % (same_rep, same_log))
    return same_rep and same_log and ran_ok, lines
