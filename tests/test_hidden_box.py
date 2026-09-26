"""Тесты для scripts/hidden_box.py."""

import subprocess
import sys
from pathlib import Path


def test_hidden_box_cli_help():
    """Проверка, что скрипт hidden_box.py вызывается напрямую через CLI без ModuleNotFoundError."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "hidden_box.py"
    res = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "Генератор скрытых сценариев" in res.stdout


def test_load_base_scenario_default_path():
    """Проверка, что load_base_scenario по умолчанию использует REPO_ROOT и успешно загружает 01_clear.json."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import hidden_box

    sc = hidden_box.load_base_scenario()
    assert isinstance(sc, dict)
    assert sc.get("name") == "01_clear"
    assert "map" in sc


def test_candidate_7_start_heading():
    """Проверка, что кандидат 7 ориентирован наружу в проезд (dock_exit_heading), а не в стену."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import hidden_box

    base_sc = hidden_box.load_base_scenario()
    grid = hidden_box.build_planner_grid(base_sc)
    cands = hidden_box.generate_candidates(base_sc, grid)

    sc7 = next(c for c in cands if c["name"] == "hb_07_short_leg_snow_pallet")
    expected_heading = hidden_box.dock_exit_heading("shop_b")
    assert abs(sc7["start"]["theta"] - expected_heading) < 1e-4
    # Points shop_b heading in 01_clear.json is 0.0 (facing wall), sc7 start must not be 0.0
    assert sc7["start"]["theta"] != 0.0


def test_evaluate_candidate_null_score(tmp_path, monkeypatch):
    """Проверка, что evaluate_candidate не падает при score: None или total: None."""
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import hidden_box

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cand = {"name": "test_cand", "missions": [{"from": "a", "to": "b"}]}

    # Mock subprocess.run to write report files with null score
    def mock_run(cmd, **kwargs):
        with open(out_dir / "test_cand_oracle.json", "w") as f:
            json.dump({"score": None}, f)
        with open(out_dir / "test_cand_base.json", "w") as f:
            json.dump({"score": {"total": None, "deliveries": None}}, f)
        import subprocess
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(hidden_box.subprocess, "run", mock_run)

    admitted, meta, _ = hidden_box.evaluate_candidate(cand, temp_dir=out_dir)
    assert admitted is False
    assert meta["oracle_total"] == 0.0
    assert meta["baseline_total"] == 0.0


