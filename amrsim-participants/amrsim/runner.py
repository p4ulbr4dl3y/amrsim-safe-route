"""Run a scenario: simulation loop, controller process, log (JSONL) and report (JSON).

The log is kept in memory and written after the run, so a controller cannot
read the truth of the current run from disk while it is being produced.
"""
import hashlib
import json
import math
import time
from pathlib import Path

from amrsim import SCHEMA, __version__
from amrsim.params import controller_config
from amrsim.proc import ControllerError, ControllerProcess, WallLimit
from amrsim.schema import load_scenario
from amrsim.scoring import score_records
from amrsim.sim import STATUSES, Simulation
from amrsim.util import PKG_DIR, AmrsimError, check_writable, package_hash, write_json  # noqa: F401

IDLE_CMD = {"v": 0.0, "w": 0.0, "status": "waiting", "pose_est": None, "note": ""}
DEFAULT_WALL_LIMIT = 600.0

EXIT_OK, EXIT_CONTROLLER, EXIT_WALL = 0, 3, 4


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def salted_seed(seed, salt):
    """Jury seed: hash(seed + salt); the salt never reaches the controller."""
    if not salt:
        return int(seed)
    h = hashlib.sha256(("%d:%s" % (int(seed), salt)).encode("utf-8")).hexdigest()
    return int(h[:15], 16)


def clean_cmd(cmd):
    """Validate a command coming back from the controller process."""
    if not isinstance(cmd, dict):
        raise ControllerError("step() result is not a dict")
    out = {}
    for k in ("v", "w"):
        v = cmd.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ControllerError("step() returned %s=%r, expected a finite number" % (k, v))
        out[k] = float(v)
    st = cmd.get("status", "moving")
    if st not in STATUSES:
        raise ControllerError("step() returned status=%r, expected one of %s" % (st, ", ".join(STATUSES)))
    out["status"] = st
    pe = cmd.get("pose_est")
    if isinstance(pe, (list, tuple)) and len(pe) == 3 and all(
            isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) for a in pe):
        out["pose_est"] = [float(a) for a in pe]
    else:
        out["pose_est"] = None  # missing or non-finite estimate counts as a large error
    note = cmd.get("note", "")
    out["note"] = note[:200] if isinstance(note, str) else ""
    return out


def run_scenario(scenario_path, seed=0, controller_path=None, cheat=False, wall_limit=DEFAULT_WALL_LIMIT,
                 log_path=None, report_path=None, max_ticks=None, salt=None, scenario=None):
    """Run one scenario and return the report dict (also written to report_path)."""
    if isinstance(wall_limit, bool) or not isinstance(wall_limit, (int, float)) or \
            not math.isfinite(wall_limit) or not 0 < wall_limit <= 86400:
        raise AmrsimError("wall limit must be a number of seconds in (0, 86400], got %r" % (wall_limit,))
    sc = scenario if scenario is not None else load_scenario(scenario_path)
    sim = Simulation(sc, salted_seed(seed, salt))
    ctrl_info = None
    if controller_path is not None:
        cp = Path(controller_path)
        if cp.is_dir():
            cp = cp / "controller.py"
        if not cp.is_file():
            raise AmrsimError("controller not found: %s" % controller_path)
        given = str(cp)  # as written on the command line: reports stay free of local paths
        controller_path = cp.resolve()
        ctrl_info = {"path": given, "sha256": file_sha(controller_path)}
    header = {
        "type": "header", "schema": SCHEMA, "amrsim": __version__, "package_hash": package_hash(),
        "scenario": sc["name"], "scenario_sha": file_sha(scenario_path) if scenario_path else None,
        "seed": int(seed), "salted": bool(salt), "cheat": bool(cheat), "dt": 0.1,
        "hidden": bool(sc.get("hidden", False)), "points": sc["map"]["points"],
        "missions": [{"id": m["id"], "from": m["from"], "to": m["to"], "deadline_s": m["deadline_s"],
                      "reference_length_m": round(sim.missions.ref_len[i], 3)}
                     for i, m in enumerate(sc["missions"])],
        "controller": ctrl_info,
        # for render and for the jury; the log holds world truth anyway and never reaches controllers
        "map": sc["map"], "map_patches": sc.get("map_patches", []), "events": sc.get("events", []),
    }
    records = [header]
    missions = []
    deny = [PKG_DIR]
    for p in (scenario_path, log_path, report_path):
        if p:
            d = Path(p).resolve().parent
            # never deny the controller's own directory (its helper modules live there)
            if controller_path is None or not Path(controller_path).is_relative_to(d):
                deny.append(d)
    t_wall = time.perf_counter()
    deadline = time.monotonic() + float(wall_limit)
    ctrl = None
    error = None
    end_reason = None
    tail = ""
    try:
        if controller_path is not None:
            st = sc["start"]
            ctrl = ControllerProcess(controller_path, sc["map"], controller_config(),
                                     [st["x"], st["y"], st["theta"]], deadline, deny=deny)
        while not sim.done:
            if max_ticks is not None and sim.k >= max_ticks:
                sim._finish("max_ticks")
                break
            obs = sim.observe()
            if ctrl is None:
                cmd = IDLE_CMD
            else:
                try:
                    cmd = clean_cmd(ctrl.step(obs, truth=sim.truth_pose() if cheat else None))
                except ControllerError as e:
                    raise ControllerError("at t=%.1f: %s" % (sim.t, e))
            rec, extra = sim.apply(cmd)
            if cmd.get("note"):
                rec["nt"] = cmd["note"]
            records.append(rec)
            records.extend(extra)
            missions.extend(extra)
        end_reason = sim.end_reason
    except ControllerError as e:
        error = "controller error %s" % e if str(e).startswith("at t=") else "controller error: %s" % e
        end_reason = "controller_error"
        tail = getattr(e, "stderr_tail", "")
    except WallLimit as e:
        error = "real-time limit of %.0f s per scenario exceeded" % wall_limit
        end_reason = "wall_limit"
        tail = getattr(e, "stderr_tail", "")
    finally:
        if ctrl is not None:
            tail = ctrl.close()
    for e in sim.close_unfinished():
        records.append(e)
        missions.append(e)
    records.append({"type": "end", "t": round(sim.t, 1), "reason": end_reason, "error": error})
    wall = time.perf_counter() - t_wall
    if log_path:
        p = Path(log_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8", newline="\n") as f:
                for r in records:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
        except OSError as e:
            raise AmrsimError("cannot write log %s: %s" % (p, e.strerror))
    score = score_records(records)
    times = ctrl.step_times if ctrl is not None else []
    report = {
        "schema": SCHEMA, "amrsim": __version__, "package_hash": header["package_hash"],
        "scenario": sc["name"], "scenario_sha": header["scenario_sha"], "hidden": header["hidden"],
        "seed": int(seed), "salted": bool(salt), "cheat": bool(cheat), "controller": ctrl_info,
        "counted": end_reason not in ("controller_error", "wall_limit"),
        "end_reason": end_reason, "error": error, "ticks": sim.k, "missions": missions,
        "score": score,
        "step_time_ms": {"n": len(times),
                         "mean": round(1000 * sum(times) / len(times), 3) if times else None,
                         "max": round(1000 * max(times), 3) if times else None},
        "wall_time_s": round(wall, 3), "wall_limit_s": float(wall_limit),
        "sandbox_violations": ctrl.sandbox if ctrl is not None else [],
        "controller_stderr_tail": tail,
        "log": str(log_path) if log_path else None,
    }
    if report_path:
        write_json(report_path, report)
    return report


def exit_code(report):
    if report["end_reason"] == "controller_error":
        return EXIT_CONTROLLER
    if report["end_reason"] == "wall_limit":
        return EXIT_WALL
    return EXIT_OK
