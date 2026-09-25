#!/usr/bin/env python3
"""AMR evaluation script.

Runs AMR controller across scenarios and prints compact summary table,
with optional regression checking against baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_SCENARIOS = [
    "amrsim-participants/scenarios/01_clear.json",
    "amrsim-participants/scenarios/02_gnss_shadow.json",
    "amrsim-participants/scenarios/03_fog_snow.json",
    "amrsim-participants/scenarios/04_busy_yard.json",
]


def resolve_scenario_path(scenario: str) -> Path:
    p = Path(scenario)
    if p.exists():
        return p
    # Try under amrsim-participants/scenarios/
    candidate = Path("amrsim-participants/scenarios") / scenario
    if candidate.exists():
        return candidate
    if not scenario.endswith(".json"):
        candidate_json = Path("amrsim-participants/scenarios") / f"{scenario}.json"
        if candidate_json.exists():
            return candidate_json
    # Fallback to exact match by prefix
    scenarios_dir = Path("amrsim-participants/scenarios")
    if scenarios_dir.exists():
        for f in scenarios_dir.glob("*.json"):
            if f.stem == scenario or f.stem.startswith(f"{scenario}_"):
                return f
    return p


def run_scenario(
    scenario_path: Path,
    controller_path: Path,
    seed: int,
    report_path: Path,
    verbose: bool = False,
) -> Dict[str, Any]:
    env = os.environ.copy()
    amrsim_part_dir = str(Path("amrsim-participants").resolve())
    curr_pythonpath = env.get("PYTHONPATH", "")
    if amrsim_part_dir not in curr_pythonpath:
        env["PYTHONPATH"] = (
            f"{amrsim_part_dir}:{curr_pythonpath}" if curr_pythonpath else amrsim_part_dir
        )

    cmd = [
        sys.executable,
        "-m",
        "amrsim",
        "run",
        str(scenario_path),
        "--controller",
        str(controller_path),
        "--seed",
        str(seed),
        "--report",
        str(report_path),
    ]

    report_path.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if verbose or proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)

    if not report_path.exists():
        raise RuntimeError(
            f"amrsim failed to generate report {report_path}. Exit code: {proc.returncode}"
        )

    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    scenario_name = report.get("scenario", "unknown")
    missions = report.get("missions", [])
    total_missions = len(missions)
    delivered_missions = sum(1 for m in missions if m.get("delivered", False))
    missions_str = f"{delivered_missions}/{total_missions}"

    end_reason = report.get("end_reason", "unknown")
    score_data = report.get("score", {})
    total_score = float(score_data.get("total", 0.0))
    raw_sum = float(score_data.get("raw_sum", 0.0))
    blocks = score_data.get("blocks", {})

    deliv_score = float(blocks.get("delivery", 0.0))
    eff_score = float(blocks.get("efficiency", 0.0))
    safe_score = float(blocks.get("safety", 0.0))
    rules_score = float(blocks.get("rules", 0.0))
    pose_score = float(blocks.get("pose", 0.0))
    coll_score = float(blocks.get("collisions", 0.0))

    step_time = report.get("step_time_ms", {})
    step_mean = float(step_time.get("mean", 0.0))
    step_max = float(step_time.get("max", 0.0))

    return {
        "scenario": scenario_name,
        "missions": missions_str,
        "end_reason": end_reason,
        "total": total_score,
        "raw_sum": raw_sum,
        "delivery": deliv_score,
        "efficiency": eff_score,
        "safety": safe_score,
        "rules": rules_score,
        "pose": pose_score,
        "collisions": coll_score,
        "step_mean_ms": step_mean,
        "step_max_ms": step_max,
        "counted": score_data.get("counted", True),
        "fatal": score_data.get("fatal", False),
    }


def format_table(
    rows: List[Dict[str, Any]],
    baseline_summary: Optional[Dict[str, Any]] = None,
) -> str:
    headers = [
        "Scenario",
        "Missions",
        "Delivery",
        "Effic.",
        "Safety",
        "Rules",
        "Pose",
        "Coll.",
        "Total",
    ]
    if baseline_summary:
        headers.append("BaseΔ")
    headers.append("Step (avg/max ms)")

    table_data = []
    total_score_sum = 0.0
    base_score_sum = 0.0
    has_baseline_comparison = False

    for r in rows:
        scen = r["scenario"]
        scen_label = scen
        if r.get("fatal"):
            scen_label += " [FATAL]"
        elif not r.get("counted"):
            scen_label += " [UNCNT]"

        row = [
            scen_label,
            r["missions"],
            f"{r['delivery']:.1f}",
            f"{r['efficiency']:.2f}",
            f"{r['safety']:.1f}",
            f"{r['rules']:.1f}",
            f"{r['pose']:.1f}",
            f"{r['collisions']:.1f}",
            f"{r['total']:.2f}",
        ]
        total_score_sum += r["total"]

        if baseline_summary and "scenarios" in baseline_summary:
            base_scen = baseline_summary["scenarios"].get(scen)
            if base_scen:
                base_tot = float(base_scen.get("total", 0.0))
                base_score_sum += base_tot
                delta = r["total"] - base_tot
                delta_str = f"{delta:+.2f}" if abs(delta) >= 0.01 else " 0.00"
                row.append(delta_str)
                has_baseline_comparison = True
            else:
                row.append("  N/A")

        row.append(f"{r['step_mean_ms']:.2f} / {r['step_max_ms']:.1f}")
        table_data.append(row)

    # Summary row
    summary_row = [
        "AVERAGE / TOTAL",
        f"{sum(int(r['missions'].split('/')[0]) for r in rows)}/{sum(int(r['missions'].split('/')[1]) for r in rows)}",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        f"{total_score_sum:.2f}",
    ]
    if baseline_summary:
        if has_baseline_comparison:
            tot_delta = total_score_sum - base_score_sum
            summary_row.append(f"{tot_delta:+.2f}")
        else:
            summary_row.append("-")
    summary_row.append("-")

    # Column widths
    all_rows = [headers] + table_data + [summary_row]
    col_widths = [max(len(str(item)) for item in col) for col in zip(*all_rows)]

    def make_line(items: List[str]) -> str:
        return " | ".join(f"{str(it):<{col_widths[i]}}" for i, it in enumerate(items))

    sep = "-+-".join("-" * w for w in col_widths)

    lines = [
        make_line(headers),
        sep,
    ]
    for r in table_data:
        lines.append(make_line(r))
    lines.append(sep)
    lines.append(make_line(summary_row))

    return "\n".join(lines)


def check_regressions(
    results: List[Dict[str, Any]],
    baseline_summary: Dict[str, Any],
    tolerance: float = 0.05,
) -> List[str]:
    regressions = []
    base_scenarios = baseline_summary.get("scenarios", {})

    for r in results:
        scen = r["scenario"]
        if scen in base_scenarios:
            base_tot = float(base_scenarios[scen].get("total", 0.0))
            new_tot = r["total"]
            diff = new_tot - base_tot
            if diff < -tolerance:
                regressions.append(
                    f"Regression in {scen}: score dropped {diff:.2f} (from {base_tot:.2f} to {new_tot:.2f})"
                )
    return regressions


def main() -> None:
    parser = argparse.ArgumentParser(description="Оценка контроллера AMR")
    parser.add_argument(
        "--controller",
        default="amrsim-participants/baseline/controller.py",
        help="Путь к скрипту или каталогу контроллера",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Случайное зерно генератора (по умолчанию: 7)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=DEFAULT_SCENARIOS,
        help="Пути или имена сценариев для запуска",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="results",
        help="Каталог для сохранения отчетов симуляции (по умолчанию: results)",
    )
    parser.add_argument(
        "--save-summary",
        type=str,
        default=None,
        help="Путь для сохранения сводного JSON-файла",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="Базовый сводный JSON-файл для сравнения (по умолчанию: results/baseline_summary.json при наличии)",
    )
    parser.add_argument(
        "--check-regression",
        action="store_true",
        help="Завершать ошибкой, если результат сценария ниже базового уровня",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Допустимое отклонение балла для проверки регрессий (по умолчанию: 0.05)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Подробный вывод хода симуляции",
    )

    args = parser.parse_args()

    controller_path = Path(args.controller)
    if not controller_path.exists():
        print(f"Ошибка: контроллер не найден: {controller_path}", file=sys.stderr)
        sys.exit(1)

    # Determine baseline summary if available
    baseline_data: Optional[Dict[str, Any]] = None
    baseline_file = Path(args.baseline) if args.baseline else Path("results/baseline_summary.json")
    if baseline_file.exists():
        try:
            with open(baseline_file, "r", encoding="utf-8") as f:
                baseline_data = json.load(f)
        except Exception as e:
            print(f"Предупреждение: не удалось прочитать базовые результаты {baseline_file}: {e}", file=sys.stderr)

    report_dir = Path(args.report_dir)
    ctrl_label = controller_path.stem if controller_path.is_file() else controller_path.name
    if ctrl_label == "controller":
        ctrl_label = controller_path.parent.name or "controller"

    results: List[Dict[str, Any]] = []

    print(f"Тестирование контроллера: {controller_path} (seed={args.seed})")
    print(f"Сценариев: {len(args.scenarios)}")
    print("-" * 60)

    for scen_raw in args.scenarios:
        scen_path = resolve_scenario_path(scen_raw)
        if not scen_path.exists():
            print(f"Ошибка: сценарий не найден: {scen_raw} ({scen_path})", file=sys.stderr)
            sys.exit(1)

        scen_stem = scen_path.stem
        report_file = report_dir / f"{ctrl_label}_{scen_stem}.json"

        report = run_scenario(
            scenario_path=scen_path,
            controller_path=controller_path,
            seed=args.seed,
            report_path=report_file,
            verbose=args.verbose,
        )
        metrics = extract_metrics(report)
        results.append(metrics)

    print("\n" + format_table(results, baseline_summary=baseline_data) + "\n")

    # Structure summary data
    summary_obj = {
        "seed": args.seed,
        "controller": str(controller_path),
        "total_score": round(sum(r["total"] for r in results), 2),
        "avg_score": round(sum(r["total"] for r in results) / len(results), 2) if results else 0.0,
        "scenarios": {r["scenario"]: r for r in results},
    }

    if args.save_summary:
        save_path = Path(args.save_summary)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(summary_obj, f, indent=2)
        print(f"Сводный отчет сохранен в: {save_path}")

    # Check regression if requested or if baseline exists and --check-regression
    if args.check_regression and baseline_data:
        regressions = check_regressions(results, baseline_data, tolerance=args.tolerance)
        if regressions:
            print("ПРОВЕРКА РЕГРЕССИЙ НЕ ПРОЙДЕНА:", file=sys.stderr)
            for reg in regressions:
                print(f"  - {reg}", file=sys.stderr)
            sys.exit(1)
        else:
            print("Проверка регрессий: ПРОЙДЕНА (все сценарии >= базовый уровень - допуск)")


if __name__ == "__main__":
    main()
