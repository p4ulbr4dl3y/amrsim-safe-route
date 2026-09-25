"""Tests for AMR evaluation script (scripts/eval.py)."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eval as amr_eval
from eval import (
    check_regressions,
    extract_metrics,
    format_table,
    main,
    resolve_scenario_path,
    run_scenario,
)


def test_resolve_scenario_path_existing(tmp_path):
    f = tmp_path / "dummy_scen.json"
    f.write_text("{}", encoding="utf-8")
    assert resolve_scenario_path(str(f)) == f


def test_resolve_scenario_path_standard():
    p1 = resolve_scenario_path("01_clear.json")
    assert p1.exists()
    assert p1.name == "01_clear.json"

    p2 = resolve_scenario_path("01_clear")
    assert p2.exists()
    assert p2.name == "01_clear.json"

    p3 = resolve_scenario_path("amrsim-participants/scenarios/02_gnss_shadow.json")
    assert p3.exists()

    # Prefix match
    p4 = resolve_scenario_path("03")
    assert p4.exists()
    assert "03" in p4.stem

    # Non-existent
    p_non = resolve_scenario_path("non_existent_scen_xyz")
    assert str(p_non) == "non_existent_scen_xyz"


def test_extract_metrics_full():
    sample_report = {
        "scenario": "test_scen",
        "missions": [
            {"id": "m1", "delivered": True},
            {"id": "m2", "delivered": False},
        ],
        "end_reason": "completed",
        "score": {
            "total": 92.5,
            "raw_sum": 94.0,
            "counted": True,
            "fatal": False,
            "blocks": {
                "delivery": 40.0,
                "efficiency": 18.5,
                "safety": 15.0,
                "rules": 10.0,
                "pose": 5.0,
                "collisions": 4.0,
            },
        },
        "step_time_ms": {
            "mean": 1.25,
            "max": 5.4,
        },
    }

    metrics = extract_metrics(sample_report)
    assert metrics["scenario"] == "test_scen"
    assert metrics["missions"] == "1/2"
    assert metrics["end_reason"] == "completed"
    assert metrics["total"] == 92.5
    assert metrics["raw_sum"] == 94.0
    assert metrics["delivery"] == 40.0
    assert metrics["efficiency"] == 18.5
    assert metrics["safety"] == 15.0
    assert metrics["rules"] == 10.0
    assert metrics["pose"] == 5.0
    assert metrics["collisions"] == 4.0
    assert metrics["step_mean_ms"] == 1.25
    assert metrics["step_max_ms"] == 5.4
    assert metrics["counted"] is True
    assert metrics["fatal"] is False


def test_extract_metrics_defaults():
    metrics = extract_metrics({})
    assert metrics["scenario"] == "unknown"
    assert metrics["missions"] == "0/0"
    assert metrics["total"] == 0.0
    assert metrics["delivery"] == 0.0
    assert metrics["counted"] is True
    assert metrics["fatal"] is False


def test_format_table_without_baseline():
    rows = [
        {
            "scenario": "01_clear",
            "missions": "2/2",
            "delivery": 40.0,
            "efficiency": 19.5,
            "safety": 15.0,
            "rules": 10.0,
            "pose": 5.0,
            "collisions": 5.0,
            "total": 94.5,
            "step_mean_ms": 1.1,
            "step_max_ms": 4.0,
            "counted": True,
            "fatal": False,
        }
    ]
    tbl = format_table(rows)
    assert "01_clear" in tbl
    assert "94.50" in tbl
    assert "AVERAGE / TOTAL" in tbl
    assert "BaseΔ" not in tbl


def test_format_table_with_baseline_and_flags():
    rows = [
        {
            "scenario": "scen_fatal",
            "missions": "0/2",
            "delivery": 0.0,
            "efficiency": 0.0,
            "safety": 0.0,
            "rules": 0.0,
            "pose": 0.0,
            "collisions": 0.0,
            "total": 0.0,
            "step_mean_ms": 0.5,
            "step_max_ms": 1.0,
            "counted": True,
            "fatal": True,
        },
        {
            "scenario": "scen_uncounted",
            "missions": "1/2",
            "delivery": 20.0,
            "efficiency": 10.0,
            "safety": 5.0,
            "rules": 5.0,
            "pose": 2.0,
            "collisions": 2.0,
            "total": 44.0,
            "step_mean_ms": 0.8,
            "step_max_ms": 2.0,
            "counted": False,
            "fatal": False,
        },
        {
            "scenario": "scen_no_base",
            "missions": "1/1",
            "delivery": 40.0,
            "efficiency": 20.0,
            "safety": 15.0,
            "rules": 10.0,
            "pose": 5.0,
            "collisions": 5.0,
            "total": 95.0,
            "step_mean_ms": 1.0,
            "step_max_ms": 3.0,
            "counted": True,
            "fatal": False,
        },
    ]

    baseline = {
        "scenarios": {
            "scen_fatal": {"total": 50.0},
            "scen_uncounted": {"total": 44.0},  # delta = 0
        }
    }

    tbl = format_table(rows, baseline_summary=baseline)
    assert "scen_fatal [FATAL]" in tbl
    assert "scen_uncounted [UNCNT]" in tbl
    assert "-50.00" in tbl
    assert "0.00" in tbl
    assert "N/A" in tbl
    assert "BaseΔ" in tbl

    # Baseline with no overlapping scenarios
    tbl_no_match = format_table(
        rows, baseline_summary={"scenarios": {"other_scen": {"total": 50.0}}}
    )
    assert tbl_no_match is not None


def test_format_table_empty():
    tbl = format_table([])
    assert "AVERAGE / TOTAL" in tbl
    assert "0.00" in tbl


def test_check_regressions():
    results = [
        {"scenario": "scen1", "total": 90.0},
        {"scenario": "scen2", "total": 84.94},  # drop is 0.06 > 0.05
        {"scenario": "scen3", "total": 80.0},  # drop is 0.03 <= 0.05
        {"scenario": "scen_new", "total": 70.0},  # not in baseline
    ]
    baseline = {
        "scenarios": {
            "scen1": {"total": 89.0},
            "scen2": {"total": 85.0},
            "scen3": {"total": 80.03},
        }
    }

    regs = check_regressions(results, baseline, tolerance=0.05)
    assert len(regs) == 1
    assert "Regression in scen2" in regs[0]


def test_run_scenario_success(tmp_path, monkeypatch):
    report_file = tmp_path / "rep.json"
    scenario_path = tmp_path / "scen.json"
    controller_path = tmp_path / "ctrl.py"

    scenario_path.write_text("{}", encoding="utf-8")
    controller_path.write_text("{}", encoding="utf-8")

    def mock_run(cmd, env, capture_output, text):
        report_file.write_text(
            json.dumps({"scenario": "mock", "score": {"total": 100}}), encoding="utf-8"
        )
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "sim stdout"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(amr_eval.subprocess, "run", mock_run)

    # Test with custom PYTHONPATH in env
    monkeypatch.setenv("PYTHONPATH", "/custom/path")

    data = run_scenario(
        scenario_path=scenario_path,
        controller_path=controller_path,
        seed=42,
        report_path=report_file,
        verbose=True,
    )
    assert data["scenario"] == "mock"
    assert data["score"]["total"] == 100


def test_run_scenario_failure(tmp_path, monkeypatch):
    report_file = tmp_path / "nonexistent_rep.json"
    scenario_path = tmp_path / "scen.json"
    controller_path = tmp_path / "ctrl.py"

    scenario_path.write_text("{}", encoding="utf-8")
    controller_path.write_text("{}", encoding="utf-8")

    def mock_run(cmd, env, capture_output, text):
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = "Failed"
        proc.stderr = "Error details"
        return proc

    monkeypatch.setattr(amr_eval.subprocess, "run", mock_run)

    with pytest.raises(RuntimeError) as exc_info:
        run_scenario(
            scenario_path=scenario_path,
            controller_path=controller_path,
            seed=7,
            report_path=report_file,
            verbose=False,
        )
    assert "amrsim failed to generate report" in str(exc_info.value)


def test_main_controller_not_found(monkeypatch):
    test_args = ["eval.py", "--controller", "non_existent_ctrl_xyz.py"]
    monkeypatch.setattr(sys, "argv", test_args)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_scenario_not_found(tmp_path, monkeypatch):
    ctrl = tmp_path / "ctrl.py"
    ctrl.write_text("", encoding="utf-8")
    test_args = [
        "eval.py",
        "--controller",
        str(ctrl),
        "--scenarios",
        "invalid_scenario_xyz.json",
    ]
    monkeypatch.setattr(sys, "argv", test_args)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_normal_flow_with_save_and_regression_pass(tmp_path, monkeypatch):
    ctrl = tmp_path / "pkg" / "controller.py"
    ctrl.parent.mkdir(parents=True)
    ctrl.write_text("", encoding="utf-8")

    scen = tmp_path / "test_scen.json"
    scen.write_text("{}", encoding="utf-8")

    baseline_file = tmp_path / "base.json"
    baseline_file.write_text(
        json.dumps({"scenarios": {"test_scen": {"total": 85.0}}}),
        encoding="utf-8",
    )

    summary_file = tmp_path / "out" / "summary.json"

    def mock_run_scenario(scenario_path, controller_path, seed, report_path, verbose):
        return {
            "scenario": "test_scen",
            "missions": [{"id": "m1", "delivered": True}],
            "score": {"total": 90.0, "blocks": {}},
            "step_time_ms": {"mean": 1.0, "max": 2.0},
        }

    monkeypatch.setattr(amr_eval, "run_scenario", mock_run_scenario)

    test_args = [
        "eval.py",
        "--controller",
        str(ctrl),
        "--scenarios",
        str(scen),
        "--report-dir",
        str(tmp_path / "reports"),
        "--save-summary",
        str(summary_file),
        "--baseline",
        str(baseline_file),
        "--check-regression",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    main()

    assert summary_file.exists()
    summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary_data["total_score"] == 90.0
    assert "test_scen" in summary_data["scenarios"]


def test_main_regression_failed(tmp_path, monkeypatch):
    ctrl = tmp_path / "ctrl.py"
    ctrl.write_text("", encoding="utf-8")

    scen = tmp_path / "test_scen.json"
    scen.write_text("{}", encoding="utf-8")

    baseline_file = tmp_path / "base.json"
    baseline_file.write_text(
        json.dumps({"scenarios": {"test_scen": {"total": 95.0}}}),
        encoding="utf-8",
    )

    def mock_run_scenario(scenario_path, controller_path, seed, report_path, verbose):
        return {
            "scenario": "test_scen",
            "missions": [],
            "score": {"total": 80.0, "blocks": {}},
            "step_time_ms": {},
        }

    monkeypatch.setattr(amr_eval, "run_scenario", mock_run_scenario)

    test_args = [
        "eval.py",
        "--controller",
        str(ctrl),
        "--scenarios",
        str(scen),
        "--baseline",
        str(baseline_file),
        "--check-regression",
        "--tolerance",
        "0.1",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_baseline_unreadable(tmp_path, monkeypatch):
    ctrl = tmp_path / "ctrl.py"
    ctrl.write_text("", encoding="utf-8")

    scen = tmp_path / "test_scen.json"
    scen.write_text("{}", encoding="utf-8")

    bad_baseline = tmp_path / "bad_base.json"
    bad_baseline.write_text("INVALID JSON", encoding="utf-8")

    def mock_run_scenario(scenario_path, controller_path, seed, report_path, verbose):
        return {
            "scenario": "test_scen",
            "score": {"total": 50.0},
        }

    monkeypatch.setattr(amr_eval, "run_scenario", mock_run_scenario)

    test_args = [
        "eval.py",
        "--controller",
        str(ctrl),
        "--scenarios",
        str(scen),
        "--baseline",
        str(bad_baseline),
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    main()  # Should not raise exception, just print warning and proceed


def test_eval_script_execution():
    with patch.object(sys, "argv", ["eval.py", "--help"]):
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(Path(amr_eval.__file__)), run_name="__main__")
        assert exc.value.code == 0
