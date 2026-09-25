"""amrsim batch <teams dir> <scenarios dir> --seeds 1,2,3 --out table.csv

Every team directory (with controller.py) runs every scenario with every seed.
Rows go to the CSV; a per-team summary goes to <out>_summary.csv and stdout.
Case score of a team = mean over runs where hidden scenarios weigh 2; a check
violation makes the case score 0 (SPEC section 7).
"""
import csv
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from amrsim.check import check_dir
from amrsim.schema import load_scenario
from amrsim.util import AmrsimError

COLUMNS = ["team", "scenario", "hidden", "seed", "counted", "total", "deliveries", "delivery",
           "efficiency", "safety", "rules", "pose", "collisions", "fatal", "end_reason", "error",
           "wall_s", "step_mean_ms", "step_max_ms", "sandbox_violations", "check"]
SUMMARY_COLUMNS = ["team", "check", "runs", "open_mean", "hidden_mean", "case_score"]


def find_teams(teams_dir):
    """Team folders with controller.py, and folders that look like teams but have none."""
    root = Path(teams_dir)
    if not root.is_dir():
        raise AmrsimError("teams directory not found: %s" % root)
    teams, missing = [], []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "__")):
            continue
        (teams if (d / "controller.py").is_file() else missing).append(d)
    if (root / "controller.py").is_file():
        teams.insert(0, root)
    if not teams:
        raise AmrsimError("no team directories with controller.py in %s" % root)
    return teams, missing


def find_scenarios(scen):
    """(path, name, hidden) per scenario; hidden scenarios must be admitted by the generator.

    scen: a file, a directory, or a list of them (open and hidden sets in one batch).
    """
    files = []
    for item in (scen if isinstance(scen, (list, tuple)) else [scen]):
        p = Path(item)
        found = [p] if p.is_file() else sorted(p.glob("*.json")) if p.is_dir() else []
        if not found:
            raise AmrsimError("no scenario files in %s" % p)
        files += found
    out = []
    for f in files:
        sc = load_scenario(f)  # fail early on a broken file
        g = sc.get("generator")
        if sc.get("hidden") and isinstance(g, dict) and g.get("status") != "accepted":
            raise AmrsimError("%s: hidden scenario not admitted to scoring (generator status '%s'; "
                              "SPEC 7 needs the oracle above 85)" % (f, g.get("status")))
        out.append((f, sc["name"], bool(sc.get("hidden", False))))
    return out


def _error_row(team, name, hidden, seed, msg):
    return {"team": Path(team).name, "scenario": name, "hidden": hidden, "seed": seed, "counted": False,
            "total": 0.0, "end_reason": "error", "error": msg}


def _run_one(job):
    """Worker: one (team, scenario, seed). Must stay a top-level function (spawn pickling)."""
    from amrsim.runner import run_scenario
    team, scen, name, hidden, seed, out_dir, wall, salt = job
    tag = "%s__%s__s%d" % (Path(team).name, Path(scen).stem, seed)
    log = Path(out_dir) / "logs" / (tag + ".jsonl") if out_dir else None
    rep_path = Path(out_dir) / "reports" / (tag + ".json") if out_dir else None
    try:
        rep = run_scenario(scen, seed=seed, controller_path=team, wall_limit=wall, log_path=log,
                           report_path=rep_path, salt=salt)
    except AmrsimError as e:
        return _error_row(team, name, hidden, seed, str(e))
    except Exception as e:  # one broken run must not abort the jury batch
        return _error_row(team, name, hidden, seed, "%s: %s" % (type(e).__name__, e))
    sc = rep.get("score") or {}
    b = sc.get("blocks", {})
    return {
        "team": Path(team).name, "scenario": rep["scenario"], "hidden": rep.get("hidden", False),
        "seed": seed, "counted": rep["counted"], "total": sc.get("total", 0.0),
        "deliveries": sc.get("deliveries"),  # 0 means the passive blocks below were not credited
        "delivery": b.get("delivery"), "efficiency": b.get("efficiency"), "safety": b.get("safety"),
        "rules": b.get("rules"), "pose": b.get("pose"), "collisions": b.get("collisions"),
        "fatal": sc.get("fatal"), "end_reason": rep["end_reason"], "error": rep["error"] or "",
        "wall_s": rep["wall_time_s"], "step_mean_ms": rep["step_time_ms"]["mean"],
        "step_max_ms": rep["step_time_ms"]["max"], "sandbox_violations": len(rep["sandbox_violations"]),
    }


def run_batch(teams_dir, scen, seeds, out_csv, jobs=1, wall=600.0, salt=None, progress=print):
    teams, missing = find_teams(teams_dir)
    scens = find_scenarios(scen)
    out_csv = Path(out_csv)
    out_dir = out_csv.parent / (out_csv.stem + "_runs")
    sum_path = out_csv.with_name(out_csv.stem + "_summary.csv")
    checks = {}
    for t in teams:
        try:
            _, fatal = check_dir(t)
            checks[t.name] = "FAIL" if fatal else "OK"
        except Exception as e:  # the checker must not abort the batch either
            checks[t.name] = "ERROR"
            progress("WARNING: check of %s crashed (%s: %s); review this team by hand" % (t.name, type(e).__name__, e))
    for d in missing:
        checks[d.name] = "MISSING"
        progress("WARNING: %s has no controller.py at top level: team scored 0" % d)
    jobs_list = [(str(t), str(f), name, hidden, int(sd), str(out_dir), wall, salt)
                 for t in teams for f, name, hidden in scens for sd in seeds]
    jobs = max(1, min(int(jobs), len(jobs_list)))
    if sys.platform == "win32":
        jobs = min(jobs, 61)  # concurrent.futures limit on Windows
    progress("batch: %d team(s) x %d scenario(s) x %d seed(s) = %d runs, jobs=%d" %
             (len(teams), len(scens), len(seeds), len(jobs_list), jobs))
    rows = []
    try:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        f = out_csv.open("w", encoding="utf-8", newline="")
    except OSError as e:
        raise AmrsimError("cannot write %s: %s" % (out_csv, e.strerror))
    with f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()

        def take(r):
            r["check"] = checks.get(r["team"], "")
            rows.append(r)
            w.writerow({k: r.get(k, "") for k in COLUMNS})
            f.flush()  # partial results survive an interrupted batch
            progress("  %-20s %-24s seed %-4d total %6.2f %s" % (r["team"], r["scenario"], r["seed"],
                                                              r.get("total") or 0.0, r.get("end_reason")))
        if jobs <= 1:
            for j in jobs_list:
                take(_run_one(j))
        else:
            ctx = multiprocessing.get_context("spawn")  # no fork: same behavior on Windows
            with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx) as ex:
                for r in ex.map(_run_one, jobs_list):
                    take(r)
    summary = summarize(rows, checks)
    for d in missing:
        summary.append({"team": d.name, "check": "MISSING", "runs": 0, "open_mean": "", "hidden_mean": "",
                        "case_score": 0.0})
    try:
        with sum_path.open("w", encoding="utf-8", newline="") as sf:
            sw = csv.DictWriter(sf, fieldnames=SUMMARY_COLUMNS)
            sw.writeheader()
            sw.writerows(summary)
    except OSError as e:
        raise AmrsimError("cannot write %s: %s" % (sum_path, e.strerror))
    return rows, summary


def summarize(rows, checks):
    out = []
    for team in sorted({r["team"] for r in rows}):
        rs = [r for r in rows if r["team"] == team]
        op = [float(r.get("total") or 0.0) for r in rs if not r.get("hidden")]
        hd = [float(r.get("total") or 0.0) for r in rs if r.get("hidden")]
        wsum = sum(op) + 2 * sum(hd)
        wn = len(op) + 2 * len(hd)
        case = wsum / wn if wn else 0.0
        if checks.get(team) in ("FAIL", "MISSING"):
            case = 0.0
        out.append({"team": team, "check": checks.get(team, ""), "runs": len(rs),
                    "open_mean": round(sum(op) / len(op), 2) if op else "",
                    "hidden_mean": round(sum(hd) / len(hd), 2) if hd else "",
                    "case_score": round(case, 2)})
    out.sort(key=lambda r: -r["case_score"])
    return out


def default_jobs():
    return max(1, (os.cpu_count() or 2) - 1)
