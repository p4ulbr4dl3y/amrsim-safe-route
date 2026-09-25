"""Command line entry: python -m amrsim <command>.

Every command fails with a short message and a non-zero exit code, never with a
long traceback (use --debug to see one).
"""
import argparse
import math
import os
import platform
import sys
import time
from pathlib import Path

from amrsim import SCHEMA, __version__
from amrsim.util import AmrsimError, package_hash


def cmd_doctor(args):
    ok = True
    print("amrsim %s (schema %s, package hash %s)" % (__version__, SCHEMA, package_hash()))
    print("python  %s on %s" % (platform.python_version(), platform.platform()))
    if sys.version_info < (3, 10):
        print("FAIL python 3.10+ required")
        ok = False
    try:
        import numpy
        print("numpy   %s" % numpy.__version__)
    except ImportError:
        print("FAIL numpy is not installed: python -m pip install numpy")
        ok = False
    try:
        import matplotlib  # noqa: F401  (optional, only for render)
        print("matplotlib %s (render enabled)" % matplotlib.__version__)
    except ImportError:
        print("matplotlib not installed (optional; render disabled)")
    import subprocess
    import tempfile
    from amrsim.proc import child_env
    with tempfile.TemporaryDirectory(prefix="amrsim_doc_") as tmp:
        try:
            r = subprocess.run([sys.executable, "-B", "-c", "import numpy; print(numpy.__version__)"],
                               cwd=tmp, env=child_env(tmp), capture_output=True, text=True, timeout=60)
            child_ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            child_ok = False
    if child_ok:
        print("controller process: starts, numpy importable")
    else:
        print("FAIL controller process cannot import numpy (check PYTHONPATH / user site)")
        ok = False
    out = Path(args.out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".amrsim_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print("out dir %s writable" % out)
    except OSError as e:
        print("FAIL out dir %s not writable: %s" % (out, e.strerror))
        ok = False
    print("doctor: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def cmd_smoke(args):
    """Quick self-test: the baseline controller on scenario 01 within a wall budget."""
    from amrsim.probes import BASELINE
    from amrsim.runner import run_scenario
    scn = resolve_scenario("01_clear")
    if not BASELINE.is_file():
        raise AmrsimError("baseline controller not found: %s" % BASELINE)
    t0 = time.perf_counter()
    rep = run_scenario(scn, seed=1, controller_path=BASELINE, wall_limit=max(args.budget * 3, 60.0))
    dt = time.perf_counter() - t0
    delivered = sum(m["delivered"] for m in rep["score"]["missions"])
    ok = rep["end_reason"] == "missions_done" and dt < args.budget and delivered == len(rep["missions"])
    print("smoke: baseline on %s, %d ticks, end %s, delivered %d/%d, total %.2f, %.2f s (budget %.0f s): %s" %
          (rep["scenario"], rep["ticks"], rep["end_reason"], delivered, len(rep["missions"]),
           rep["score"]["total"], dt, args.budget, "OK" if ok else "FAIL"))
    if rep["error"]:
        print("error: %s" % rep["error"], file=sys.stderr)
    return 0 if ok else 1


def cmd_probe_determinism(args):
    from amrsim.probes import probe_determinism
    ok, lines = probe_determinism(seed=args.seed)
    print("probe-determinism: baseline on 01_clear seed %d, two runs" % args.seed)
    print("\n".join(lines))
    print("probe-determinism: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def resolve_scenario(name):
    """Accept a path or a short name like 01 / 01_clear / 01e (looked up in scenarios/)."""
    p = Path(name)
    if p.is_file():
        return p
    if p.is_absolute() or len(p.parts) != 1 or any(c in name for c in "*?[]"):
        raise AmrsimError("scenario not found: %s" % name)
    for base in (Path("scenarios"), Path(__file__).resolve().parents[1] / "scenarios"):
        if not base.is_dir():
            continue
        hits = sorted(base.glob("%s*.json" % name))
        exact = [h for h in hits if h.stem == name or h.stem.split("_", 1)[0] == name]
        if len(exact) == 1:
            return exact[0]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise AmrsimError("scenario %s is ambiguous: %s" % (name, ", ".join(h.stem for h in hits)))
    raise AmrsimError("scenario not found: %s" % name)


def _wall_seconds(s):
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError("not a number: %r" % s)
    if not (math.isfinite(v) and 0 < v <= 86400):
        raise argparse.ArgumentTypeError("expected seconds in (0, 86400], got %r" % s)
    return v


def _read_salt(args):
    if getattr(args, "salt_file", None):
        p = Path(args.salt_file)
        try:
            salt = p.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise AmrsimError("cannot read salt file %s: %s" % (p, e.strerror))
        if not salt:
            raise AmrsimError("salt file %s is empty" % p)
        return salt
    return None


def cmd_run(args):
    from amrsim.runner import exit_code, run_scenario
    from amrsim.util import check_writable
    scn = resolve_scenario(args.scenario)
    check_writable(args.report)
    check_writable(args.log)
    if args.cheat and not args.controller:
        print("warning: --cheat without --controller: nothing receives the true pose "
              "(oracle: --controller baseline/controller.py --cheat)", file=sys.stderr)
    rep = run_scenario(scn, seed=args.seed, controller_path=args.controller, cheat=args.cheat,
                       wall_limit=args.wall_limit, log_path=args.log, report_path=args.report,
                       salt=_read_salt(args))
    who = rep["controller"]["path"] if rep["controller"] else "none (robot stands)"
    print("scenario %s seed %d%s controller %s" % (rep["scenario"], rep["seed"],
                                                   " (salted)" if rep["salted"] else "", who))
    print("  %d ticks, end %s, %.1f s wall, step mean %s ms max %s ms" %
          (rep["ticks"], rep["end_reason"], rep["wall_time_s"], rep["step_time_ms"]["mean"],
           rep["step_time_ms"]["max"]))
    for m in rep["missions"]:
        print("  mission %s %s->%s: %s" % (m["id"], m["from"], m["to"], m["reason"]))
    if rep.get("score"):
        sc = rep["score"]
        nc = sc.get("not_counted_blocks") or []
        print("  score %.2f%s%s  %s" % (sc["total"], "" if rep["counted"] else " (not counted)",
                                        " (no delivery: safety, rules, pose not counted)" if nc else "",
                                        " ".join("%s %.1f" % kv for kv in sc["blocks"].items())))
    if rep["sandbox_violations"]:
        print("  sandbox blocked %d attempt(s), first: %s" % (len(rep["sandbox_violations"]),
                                                          rep["sandbox_violations"][0]))
    if rep["error"]:
        print("error: %s" % rep["error"], file=sys.stderr)
    return exit_code(rep)


def cmd_check(args):
    from amrsim.check import check_dir
    if not Path(args.target).exists():
        raise AmrsimError("not found: %s" % args.target)
    findings, fatal = check_dir(args.target)
    nv = sum(1 for k, _, _ in findings if k in ("VIOLATION", "ERROR"))
    nw = sum(1 for k, _, _ in findings if k == "WARNING")
    print("check %s: %d violation(s) or error(s), %d warning(s)" % (args.target, nv, nw))
    for k, where, msg in findings:
        print("  %-9s %s: %s" % (k, where, msg))
    print("result: %s" % ("FAIL (a violation means 0 points for the case)" if fatal else "OK"))
    return 1 if fatal else 0


def print_score(sc, head):
    print(head)
    nc = sc.get("not_counted_blocks") or []
    print("  total %.2f%s%s%s" % (sc["total"], "" if sc["counted"] else " (not counted)",
                                  " (contact with a person while moving: 0)" if sc["fatal"] else "",
                                  " (no mission delivered)" if nc else ""))
    for k, v in sc["blocks"].items():
        print("  %-11s %8.2f  (max %.0f)%s" % (k, v, sc["max"][k],
                                               "  not_counted: no delivery" if k in nc else ""))
    for m in sc["missions"]:
        print("  mission %-3s %-12s time %s ratio %s" % (m["id"], m["reason"], m["time_s"], m["ratio"]))
    if sc["top_episodes"]:
        print("  top episodes:")
        for e in sc["top_episodes"]:
            print("    t=%6.1f-%6.1f %-24s %7.2f  at (%.1f, %.1f)" %
                  (e["t_start"], e["t_end"], e["type"], e["cost"], e["x"], e["y"]))


def cmd_score(args):
    import json
    from amrsim.scoring import score_records
    from amrsim.util import read_json
    p = Path(args.file)
    if p.suffix == ".jsonl":
        if not p.is_file():
            raise AmrsimError("file not found: %s" % p)
        recs = []
        try:
            with p.open(encoding="utf-8-sig") as f:
                for i, line in enumerate(f, 1):
                    if line.strip():
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            raise AmrsimError("%s:%d: not a JSON line" % (p, i))
                        if not isinstance(rec, dict):
                            raise AmrsimError("%s:%d: not a JSON object" % (p, i))
                        recs.append(rec)
        except UnicodeDecodeError:
            raise AmrsimError("not UTF-8 text: %s (save the file as UTF-8)" % p)
        except OSError as e:
            raise AmrsimError("cannot read %s: %s" % (p, e.strerror))
        try:
            sc = score_records(recs)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
            raise AmrsimError("%s: not an amrsim run log (%s)" % (p, e))
        print_score(sc, "log %s" % p)
        return 0
    rep = read_json(p)
    sc = rep.get("score") if isinstance(rep, dict) else None
    if not isinstance(sc, dict) or not {"total", "counted", "fatal", "blocks", "max", "missions",
                                         "top_episodes"} <= set(sc):
        raise AmrsimError("%s: not an amrsim report (no complete 'score'); pass the report .json "
                          "or the log .jsonl" % p)
    try:
        print_score(sc, "report %s: scenario %s seed %s%s" % (
            p, rep.get("scenario"), rep.get("seed"),
            " ORACLE (--cheat, not for ranking)" if rep.get("cheat") else ""))
    except (KeyError, TypeError, ValueError) as e:
        raise AmrsimError("%s: damaged score block (%s)" % (p, e))
    return 0


def cmd_probe_scoring(args):
    from amrsim.probes import probe_scoring
    ok, lines = probe_scoring()
    print("probe-scoring: known log -> known score")
    print("\n".join(lines))
    print("probe-scoring: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def _seed_list(s):
    try:
        seeds = [int(x) for x in s.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("expected comma-separated integers, got %r" % s)
    if not seeds:
        raise argparse.ArgumentTypeError("no seeds given")
    return seeds


def cmd_batch(args):
    from amrsim.batch import default_jobs, run_batch
    from amrsim.util import check_writable
    check_writable(args.out)
    check_writable(Path(args.out).with_name(Path(args.out).stem + "_summary.csv"))
    if args.jobs < 0:
        raise AmrsimError("--jobs must be 0 (auto) or a positive number")
    jobs = default_jobs() if args.jobs == 0 else args.jobs
    rows, summary = run_batch(args.teams, args.scenarios, args.seeds, args.out, jobs=jobs,
                              wall=args.wall_limit, salt=_read_salt(args))
    print("summary (case = mean over all runs, hidden scenarios weigh 2; check FAIL or MISSING -> 0):")
    for r in summary:
        print("  %-24s check %-4s runs %3d  open %6s  hidden %6s  case %6.2f" %
              (r["team"], r["check"], r["runs"], r["open_mean"], r["hidden_mean"], r["case_score"]))
    print("table: %s, summary: %s" % (args.out, Path(args.out).with_name(Path(args.out).stem + "_summary.csv")))
    errors = [r for r in rows if r.get("end_reason") == "error"]
    if errors:
        print("WARNING: %d run(s) failed with infrastructure errors (end_reason error); their scores are "
              "not valid, first: %s" % (len(errors), errors[0].get("error")), file=sys.stderr)
        return 1
    return 0


def cmd_render(args):
    from amrsim.render import render_log
    from amrsim.util import check_writable
    check_writable(args.png)
    out = render_log(args.log, args.png)
    print("render: %s" % out)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="python -m amrsim", description="amr-sim %s" % __version__)
    p.add_argument("--debug", action="store_true", help="show full tracebacks")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help="show full tracebacks")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    d = sub.add_parser("doctor", help="check environment", parents=[common])
    d.add_argument("--out", default="out", help="output dir to test for write access")
    d.set_defaults(func=cmd_doctor)

    r = sub.add_parser("run", help="run one scenario", parents=[common])
    r.add_argument("scenario", help="scenario file or short name (01, 01_clear)")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--report", default=None, help="report JSON path")
    r.add_argument("--log", default=None, help="log JSONL path")
    r.add_argument("--controller", default=None, help="team controller.py (or its directory)")
    r.add_argument("--cheat", action="store_true",
                   help="oracle: pass the true pose to Controller.set_truth (not for ranking)")
    r.add_argument("--wall-limit", type=_wall_seconds, default=600.0, help="real-time limit per scenario, s")
    r.add_argument("--salt-file", default=None, help="jury salt: seed = hash(seed + salt)")
    r.set_defaults(func=cmd_run)

    sc = sub.add_parser("score", help="print the score of a report (.json) or recompute it from a log (.jsonl)",
                        parents=[common])
    sc.add_argument("file")
    sc.set_defaults(func=cmd_score)

    ps = sub.add_parser("probe-scoring", help="known log -> known score self-test", parents=[common])
    ps.set_defaults(func=cmd_probe_scoring)

    pd = sub.add_parser("probe-determinism", help="two identical runs -> identical report and log",
                        parents=[common])
    pd.add_argument("--seed", type=int, default=3)
    pd.set_defaults(func=cmd_probe_determinism)

    b = sub.add_parser("batch", help="run every team on every scenario and seed, write a CSV table",
                       parents=[common])
    b.add_argument("teams", help="directory with team folders (each has controller.py)")
    b.add_argument("scenarios", nargs="+", help="scenario files or directories (open and hidden together)")
    b.add_argument("--seeds", type=_seed_list, default=[1, 2, 3], help="e.g. 1,2,3")
    b.add_argument("--out", default="out/table.csv")
    b.add_argument("--jobs", type=int, default=1, help="parallel runs (0 = CPU count - 1)")
    b.add_argument("--wall-limit", type=_wall_seconds, default=600.0)
    b.add_argument("--salt-file", default=None, help="jury salt: seed = hash(seed + salt)")
    b.set_defaults(func=cmd_batch)

    rd = sub.add_parser("render", help="PNG of a run from its log (needs matplotlib)", parents=[common])
    rd.add_argument("log", help="run log .jsonl")
    rd.add_argument("--png", required=True, help="output PNG path")
    rd.set_defaults(func=cmd_render)

    c = sub.add_parser("check", help="static rules check of a team directory", parents=[common])
    c.add_argument("target", help="team directory or controller.py")
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("smoke", help="quick self-test on scenario 01", parents=[common])
    s.add_argument("--budget", type=float, default=20.0, help="wall time budget, s")
    s.set_defaults(func=cmd_smoke)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # any path prints, whatever the console code page
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except AmrsimError as e:
        print("error: %s" % e, file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:  # last resort: one line, not a 200-line trace
        if args.debug or os.environ.get("AMRSIM_DEBUG"):
            raise
        print("internal error: %s: %s (rerun with --debug)" % (type(e).__name__, e), file=sys.stderr)
        return 1
