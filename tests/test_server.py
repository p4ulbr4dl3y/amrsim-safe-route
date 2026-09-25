"""Tests for AMR SafeRoute SDUI server, scenario management, and CSV export."""

from __future__ import annotations

import io
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen, Request

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "arm"))

import server
from server import (
    AMRServerHandler,
    SCENARIO_META,
    build_analytics_view_model,
    build_dashboard_view_model,
    build_episodes_view_model,
    build_missions_view_model,
    build_replay_view_model,
    get_scenario_file,
    get_scenario_log_path,
    get_scenario_report,
    normalize_scenario_id,
)

ALL_SCENARIO_IDS = [
    "01_clear",
    "01e_clear_easy",
    "02_gnss_shadow",
    "02e_gnss_shadow_easy",
    "03_fog_snow",
    "04_busy_yard",
    "s1_pallet_2m",
    "s2_container_block",
    "s3_wall_removed",
    "s4_shadow_start_charger",
    "s5_fog_inattentive",
]


def test_normalize_scenario_id():
    assert normalize_scenario_id(None) == "04_busy_yard"
    assert normalize_scenario_id("") == "04_busy_yard"
    assert normalize_scenario_id("01_clear") == "01_clear"
    assert normalize_scenario_id("01_clear.json") == "01_clear"
    assert normalize_scenario_id("backend/scenarios/s1_pallet_2m.json") == "s1_pallet_2m"
    assert normalize_scenario_id("team/scenarios/s1_pallet_2m.json") == "s1_pallet_2m"
    assert normalize_scenario_id("team/s1_pallet_2m") == "s1_pallet_2m"
    assert normalize_scenario_id("backend\\scenarios\\s2_container_block.json") == "s2_container_block"
    assert normalize_scenario_id("02_gnss_shadow_easy") == "02e_gnss_shadow_easy"
    assert normalize_scenario_id("02_gnss_shadow_easy.json") == "02e_gnss_shadow_easy"
    assert normalize_scenario_id("02_shadow_easy") == "02e_gnss_shadow_easy"
    assert normalize_scenario_id("01_clear_easy") == "01e_clear_easy"


def test_get_scenario_file_all_scenarios():
    for sc_id in ALL_SCENARIO_IDS:
        sc_file = get_scenario_file(sc_id)
        assert sc_file is not None, f"Scenario file not found for: {sc_id}"
        assert sc_file.exists(), f"Scenario file does not exist: {sc_file}"


def test_get_scenario_file_with_aliases_and_paths():
    assert get_scenario_file("02_gnss_shadow_easy") is not None
    assert get_scenario_file("02_gnss_shadow_easy.json") is not None
    assert get_scenario_file("team/scenarios/s1_pallet_2m.json") is not None
    assert get_scenario_file("backend/scenarios/s1_pallet_2m.json") is not None
    assert get_scenario_file("s1_pallet_2m.json") is not None


def test_get_scenario_report_and_logs():
    for sc_id in ALL_SCENARIO_IDS:
        rep = get_scenario_report(sc_id)
        assert rep is not None, f"Report not found for scenario: {sc_id}"
        assert "score" in rep, f"Report missing score for scenario: {sc_id}"

        log_p = get_scenario_log_path(sc_id)
        assert log_p is not None, f"Log path not found for scenario: {sc_id}"
        assert log_p.exists(), f"Log file does not exist: {log_p}"


def test_view_models_build_successfully():
    for sc_id in ALL_SCENARIO_IDS:
        dash_vm = build_dashboard_view_model(sc_id)
        assert dash_vm["scenario"] == normalize_scenario_id(sc_id)
        assert "totalScore" in dash_vm
        assert "deliveriesCount" in dash_vm
        assert "mapData" in dash_vm

        rep_vm = build_replay_view_model(sc_id)
        assert rep_vm["scenario"] == normalize_scenario_id(sc_id)
        assert "ticks" in rep_vm
        assert "mapData" in rep_vm

        ep_vm = build_episodes_view_model(sc_id)
        assert ep_vm["scenario"] == normalize_scenario_id(sc_id)
        assert "episodes" in ep_vm
        assert "summary" in ep_vm

        miss_vm = build_missions_view_model(sc_id)
        assert miss_vm["scenario"] == normalize_scenario_id(sc_id)
        assert "missions" in miss_vm

        an_vm = build_analytics_view_model(sc_id)
        assert an_vm["scenario"] == normalize_scenario_id(sc_id)
        assert "blocks" in an_vm


def test_episodes_never_empty_for_any_scenario():
    """Verify that build_episodes_view_model populates informative events even for clean scenarios."""
    for sc_id in ALL_SCENARIO_IDS:
        ep_vm = build_episodes_view_model(sc_id)
        episodes = ep_vm.get("episodes", [])
        assert len(episodes) > 0, f"Episodes list is empty for scenario: {sc_id}"

        for ep in episodes:
            assert "id" in ep
            assert "type" in ep
            assert "category" in ep
            assert "severity" in ep
            assert "t_start" in ep
            assert "t_end" in ep
            assert "x" in ep
            assert "y" in ep
            assert "cost" in ep


def test_csv_export_format_and_rows():
    """Verify that CSV export contains valid columns and multiple data rows for every scenario."""
    expected_headers = [
        "Episode ID", "Type", "Category", "Severity", "Start (s)", "End (s)",
        "X", "Y", "Speed (m/s)", "Hum Dist (m)", "Obj Dist (m)", "PE Error (m)",
        "Cost (pts)", "Explanation"
    ]

    for sc_id in ALL_SCENARIO_IDS:
        ep_vm = build_episodes_view_model(sc_id)
        episodes = ep_vm.get("episodes", [])
        assert len(episodes) > 0

        lines = [",".join(expected_headers)]
        for ep in episodes:
            tk_snap = ep.get("telemetrySnapshot") or {}
            v_val = f"{tk_snap.get('v', ''):.2f}" if isinstance(tk_snap.get('v'), (int, float)) else ""
            hum_val = f"{tk_snap.get('hum', ''):.2f}" if isinstance(tk_snap.get('hum'), (int, float)) else ""
            obj_val = f"{tk_snap.get('obj', ''):.2f}" if isinstance(tk_snap.get('obj'), (int, float)) else ""
            pe_val = f"{tk_snap.get('pe_error', ''):.4f}" if isinstance(tk_snap.get('pe_error'), (int, float)) else ""
            cost_val = f"{ep.get('cost', 0.0):.2f}"
            expl = str(ep.get("ruleExplanation", "")).replace('"', '""')

            lines.append(
                f"{ep.get('id')},{ep.get('type')},{ep.get('category')},{ep.get('severity', 'info')},"
                f"{ep.get('t_start')},{ep.get('t_end')},{ep.get('x')},{ep.get('y')},"
                f"{v_val},{hum_val},{obj_val},{pe_val},{cost_val},\"{expl}\""
            )

        csv_content = "\n".join(lines)
        csv_lines = [l for l in csv_content.splitlines() if l.strip()]

        # Ensure header + at least 1 data row
        assert len(csv_lines) >= 2, f"CSV has no data rows for {sc_id}"
        assert csv_lines[0] == ",".join(expected_headers)


@pytest.fixture(scope="module")
def http_server():
    """Start local test server on a free port."""
    from http.server import ThreadingHTTPServer

    srv = ThreadingHTTPServer(("127.0.0.1", 0), AMRServerHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


def test_api_scenarios_endpoint(http_server):
    url = f"{http_server}/api/scenarios"
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert len(data) >= 11
        ids = {s["id"] for s in data}
        for expected in ALL_SCENARIO_IDS:
            assert expected in ids, f"Missing scenario in /api/scenarios: {expected}"
        for s in data:
            assert s["hasReport"] is True, f"Report should exist for: {s['id']}"


def test_api_export_csv_endpoint(http_server):
    for test_sc in ["01_clear", "02_gnss_shadow_easy", "s1_pallet_2m", "s2_container_block", "s3_wall_removed"]:
        url = f"{http_server}/api/export/csv?scenario={test_sc}"
        with urlopen(url) as resp:
            assert resp.status == 200
            assert "text/csv" in resp.headers.get("Content-Type", "")
            content = resp.read().decode("utf-8")
            lines = [l for l in content.splitlines() if l.strip()]
            assert len(lines) >= 2, f"CSV export for {test_sc} returned empty rows!"
            assert "Episode ID" in lines[0]


def test_api_ui_dashboard_endpoint(http_server):
    url = f"{http_server}/api/ui/dashboard?scenario=02_gnss_shadow_easy"
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["scenario"] == "02e_gnss_shadow_easy"
        assert "totalScore" in data


def test_rule_explanations_latex_formatting():
    from server import RULE_EXPLANATIONS
    assert "person_near_fast" in RULE_EXPLANATIONS
    # Check that KaTeX math delimiters ($) are present for key physical thresholds
    assert "$d_{\\text{hum}} < 3.0" in RULE_EXPLANATIONS["person_near_fast"]
    assert "$|v| > 0.28" in RULE_EXPLANATIONS["person_near_fast"]
    assert "$d_{\\text{obj}} < 0.8" in RULE_EXPLANATIONS["obstacle_close"]
    assert "$\\|\\mathbf{e}_{\\text{pose}}\\| > 1.0" in RULE_EXPLANATIONS["pose_drift"]


def test_episodes_view_model_contains_latex_math():
    ep_vm = build_episodes_view_model("04_busy_yard")
    assert "episodes" in ep_vm
    assert len(ep_vm["episodes"]) > 0
    # Any episode with ruleExplanation should retain LaTeX math notation
    has_math = any("$" in ep.get("ruleExplanation", "") for ep in ep_vm["episodes"])
    assert has_math, "Episodes view model should contain LaTeX mathematical formatting"


def test_server_view_model_analytics_six_blocks():
    analytics = build_analytics_view_model("01_clear")
    assert "blocks" in analytics
    assert len(analytics["blocks"]) == 6
    block_keys = {b["key"] for b in analytics["blocks"]}
    expected_keys = {"delivery", "efficiency", "safety", "rules", "pose", "collisions"}
    assert block_keys == expected_keys
    assert "radar" in analytics
    assert len(analytics["radar"]["labels"]) == 6


def test_server_missions_view_model_structure():
    vm = build_missions_view_model("04_busy_yard")
    assert "summary" in vm
    assert "missions" in vm
    assert vm["summary"]["total"] >= 1
    for m in vm["missions"]:
        assert "id" in m
        assert "fromLabel" in m
        assert "toLabel" in m
        assert "status" in m


def test_server_replay_ticks_and_episodes():
    rep = build_replay_view_model("01_clear", seed=7)
    assert "ticks" in rep
    assert len(rep["ticks"]) > 0
    assert "mapData" in rep
    assert "totalTicks" in rep
    assert rep["totalTicks"] >= len(rep["ticks"])
    assert rep["ticks"][0]["t"] <= rep["ticks"][-1]["t"]


def test_api_post_unknown_endpoint(http_server):
    url = f"{http_server}/api/unknown_action"
    req = Request(url, data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 404


def test_format_time():
    from server import format_time
    assert format_time(0.0) == "00:00"
    assert format_time(65.0) == "01:05"
    assert format_time(3600.0) == "60:00"


def test_get_scenario_file_relative_and_not_found(tmp_path, monkeypatch):
    from server import get_scenario_file, ROOT_DIR
    # Relative path from ROOT_DIR
    rel_file = "amrsim-participants/scenarios/01_clear.json"
    assert get_scenario_file(rel_file) is not None

    # Missing file
    assert get_scenario_file("completely_missing_scen_12345") is None


def test_load_scenario_json(tmp_path):
    from server import load_scenario_json
    # Existing valid
    data = load_scenario_json("01_clear")
    assert data is not None
    assert "map" in data or "missions" in data

    # Non-existent
    assert load_scenario_json("non_existent_scen_xyz") is None

    # Invalid JSON file
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{invalid json", encoding="utf-8")
    assert load_scenario_json(str(bad_file)) is None


def test_get_scenario_report_bad_file(tmp_path, monkeypatch):
    import server
    # Force report load error
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(server, "RESULTS_DIR", tmp_path)
    bad_rep = tmp_path / "bad_rep.json"
    bad_rep.write_text("{broken json", encoding="utf-8")
    res = server.get_scenario_report("bad_rep")
    assert res is None


def test_get_scenario_log_path_none(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(server, "ROOT_DIR", tmp_path)
    assert server.get_scenario_log_path("missing") is None


def test_run_simulation_missing_scen():
    from server import run_simulation
    with pytest.raises(FileNotFoundError):
        run_simulation("non_existent_scen_xyz")


def test_run_simulation_mocked(tmp_path, monkeypatch):
    import server
    from unittest.mock import MagicMock

    rep_path = tmp_path / "01_clear.json"
    rep_path.write_text(json.dumps({"score": {"total": 91.5}}), encoding="utf-8")

    monkeypatch.setattr(server, "OUT_DIR", tmp_path)

    def mock_subprocess_run(cmd, cwd, env, capture_output, text):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "simulation success\n"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(server.subprocess, "run", mock_subprocess_run)

    # Test with team/ prefix in controller and cheat=True
    res = server.run_simulation(
        scenario_id="01_clear",
        controller_path="team/controller.py",
        seed=123,
        cheat=True,
    )
    assert res["exitCode"] == 0
    assert res["score"] == 91.5
    assert "simulation success" in res["stdout"]


def test_extract_map_data_variations():
    from server import extract_map_data

    # Both none
    empty_map = extract_map_data(None, None)
    assert empty_map["bounds"] == [0, 0, 250, 200]
    assert empty_map["points"] == {}

    # Header with map
    header = {
        "map": {
            "bounds": [0, 0, 100, 100],
            "points": {"ptA": {"x": 10.0, "y": 20.0}},
            "buildings": [],
            "zones": [],
        }
    }
    header_map = extract_map_data(None, header)
    assert header_map["bounds"] == [0, 0, 100, 100]
    assert "ptA" in header_map["points"]


def test_parse_ticks_log_edge_cases(tmp_path, monkeypatch):
    import server

    # Non-existent log
    monkeypatch.setattr(server, "get_scenario_log_path", lambda s: None)
    res = server.parse_ticks_log("missing_log_scen")
    assert res["totalTicks"] == 0
    assert res["ticks"] == []

    # File with empty lines and only header
    log_file = tmp_path / "only_header.jsonl"
    log_file.write_text(
        '\n\n{"type": "header", "map": {"bounds": [0, 0, 50, 50]}}\n\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "get_scenario_log_path", lambda s: log_file)
    res2 = server.parse_ticks_log("header_only_scen")
    assert res2["totalTicks"] == 0
    assert res2["ticks"] == []

    # File with ticks where pe is None
    ticks_file = tmp_path / "no_pe.jsonl"
    ticks_file.write_text(
        '{"type": "tick", "t": 1.0, "x": 5.0, "y": 6.0, "pe": null}\n'
        '{"type": "tick", "t": 2.0, "x": 6.0, "y": 7.0, "pe": [6.1, 7.1]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "get_scenario_log_path", lambda s: ticks_file)
    res3 = server.parse_ticks_log("pe_test_scen")
    assert len(res3["ticks"]) == 2
    assert res3["ticks"][0]["pe_error"] == 0.0
    assert res3["ticks"][1]["pe_error"] > 0.0


def test_build_dashboard_empty_ticks(monkeypatch):
    import server
    # Force empty raw_ticks in parse_ticks_log
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"header": None, "ticks": [], "raw_ticks": [], "totalTicks": 0, "duration": 0.0},
    )
    dash = server.build_dashboard_view_model("01_clear")
    assert len(dash["speedHistory"]) == 40
    assert dash["speedHistory"][0] == 0.0
    assert len(dash["speedTimestamps"]) == 40


def test_build_episodes_gnss_and_empty(monkeypatch):
    import server

    # GNSS outage tick
    gnss_ticks = [
        {"t": 1.0, "x": 10.0, "y": 10.0, "gnss": 0, "nt": "gnss_shadow"},
        {"t": 2.0, "x": 11.0, "y": 10.0, "gnss": 0, "nt": "gnss"},
    ]
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"raw_ticks": gnss_ticks, "ticks": gnss_ticks},
    )
    monkeypatch.setattr(server, "get_scenario_report", lambda s: {"score": {"episodes": []}})

    vm_gnss = server.build_episodes_view_model("custom_gnss")
    assert any(e["type"] == "gnss_outage" for e in vm_gnss["episodes"])

    # Empty ticks -> fallback to nominal episode
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"raw_ticks": [], "ticks": []},
    )
    vm_empty = server.build_episodes_view_model("custom_empty")
    assert len(vm_empty["episodes"]) == 1
    assert vm_empty["episodes"][0]["id"] == "ep-nominal-1"


def test_api_options_method(http_server):
    req = Request(f"{http_server}/api/scenarios", method="OPTIONS")
    with urlopen(req) as resp:
        assert resp.status == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        assert "GET" in resp.headers.get("Access-Control-Allow-Methods")


def test_api_ui_get_endpoints(http_server):
    for endpoint in [
        "/api/ui/replay?scenario=01_clear&seed=7",
        "/api/ui/episodes?scenario=01_clear",
        "/api/ui/missions?scenario=01_clear",
        "/api/ui/analytics?scenario=01_clear",
        "/api/report?scenario=01_clear",
        "/api/ticks?scenario=01_clear",
    ]:
        url = f"{http_server}{endpoint}"
        with urlopen(url) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data is not None


def test_api_report_not_found(http_server):
    url = f"{http_server}/api/report?scenario=non_existent_scenario_xyz"
    with pytest.raises(HTTPError) as exc_info:
        urlopen(url)
    assert exc_info.value.code == 404


def test_api_ui_endpoints_error_branches(http_server, monkeypatch):
    import server

    def raise_err(*args, **kwargs):
        raise ValueError("Simulated UI builder error")

    monkeypatch.setattr(server, "build_dashboard_view_model", raise_err)
    monkeypatch.setattr(server, "build_replay_view_model", raise_err)
    monkeypatch.setattr(server, "build_episodes_view_model", raise_err)
    monkeypatch.setattr(server, "build_missions_view_model", raise_err)
    monkeypatch.setattr(server, "build_analytics_view_model", raise_err)

    for ep in [
        "/api/ui/dashboard?scenario=01_clear",
        "/api/ui/replay?scenario=01_clear",
        "/api/ui/episodes?scenario=01_clear",
        "/api/ui/missions?scenario=01_clear",
        "/api/ui/analytics?scenario=01_clear",
    ]:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{http_server}{ep}")
        assert exc_info.value.code == 500


def test_api_static_frontend_and_spa(http_server):
    # Root / SPA fallback
    with urlopen(f"{http_server}/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")

    # Non-existent asset or route falling back to SPA index.html
    with urlopen(f"{http_server}/dashboard") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")


def test_api_run_simulation_endpoint(http_server, monkeypatch):
    import server

    def mock_run_sim(scenario_id, controller_path, seed, cheat):
        return {
            "exitCode": 0,
            "stdout": "amrsim simulated run ok\n",
            "stderr": "",
            "reportPath": "out.json",
            "logPath": "out.jsonl",
            "report": {"score": {"total": 95.0}},
            "score": 95.0,
        }

    monkeypatch.setattr(server, "run_simulation", mock_run_sim)

    # Valid POST /api/run
    url = f"{http_server}/api/run"
    payload = json.dumps({
        "scenario": "01_clear",
        "controller": "team/controller.py",
        "seed": 7,
        "cheatPose": False,
    }).encode("utf-8")

    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["exitCode"] == 0
        assert data["score"] == 95.0
        assert "logs" in data
        assert any("amrsim simulated run ok" in l for l in data["logs"])


def test_api_run_simulation_error_branch(http_server, monkeypatch):
    import server

    def mock_run_fail(*args, **kwargs):
        raise RuntimeError("Controller crash simulated")

    monkeypatch.setattr(server, "run_simulation", mock_run_fail)

    url = f"{http_server}/api/run"
    req = Request(url, data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 500


def test_server_main_execution(monkeypatch):
    import server
    from unittest.mock import MagicMock

    mock_srv = MagicMock()
    mock_srv.serve_forever.side_effect = KeyboardInterrupt
    monkeypatch.setattr(server, "ThreadingHTTPServer", MagicMock(return_value=mock_srv))
    monkeypatch.setattr(server.os, "chdir", MagicMock())

    monkeypatch.setattr(sys, "argv", ["server.py", "--port", "8888", "--host", "127.0.0.1"])
    server.main()
    mock_srv.serve_forever.assert_called_once()
    mock_srv.server_close.assert_called_once()

    # Also test main branch when FRONTEND_DIST does not exist
    monkeypatch.setattr(server, "FRONTEND_DIST", Path("/non_existent_frontend_dist_dir"))
    server.main()


def test_api_run_simulation_with_stderr_and_invalid_body(http_server, monkeypatch):
    import server

    def mock_run_with_stderr(*args, **kwargs):
        return {
            "exitCode": 0,
            "stdout": "stdout message",
            "stderr": "warning: some warning",
            "reportPath": "out.json",
            "logPath": "out.jsonl",
            "report": None,
            "score": None,
        }

    monkeypatch.setattr(server, "run_simulation", mock_run_with_stderr)

    url = f"{http_server}/api/run"
    # Send invalid json body to test payload = {}
    req = Request(url, data=b"not-json", headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert any("warning: some warning" in l for l in data["logs"])


def test_api_static_serving_404_when_no_frontend_dist(http_server, monkeypatch):
    import server
    monkeypatch.setattr(server, "FRONTEND_DIST", Path("/non_existent_frontend_dist_dir"))
    with pytest.raises(HTTPError) as exc_info:
        urlopen(f"{http_server}/nonexistent_static_path_123")
    assert exc_info.value.code == 404


def test_api_static_serving_existing_file(http_server, monkeypatch):
    import server
    # Set FRONTEND_DIST to ROOT_DIR so super().do_GET() serves pyproject.toml in cwd
    monkeypatch.setattr(server, "FRONTEND_DIST", server.ROOT_DIR)
    with urlopen(f"{http_server}/pyproject.toml") as resp:
        assert resp.status == 200


def test_get_scenario_file_edge_cases(tmp_path, monkeypatch):
    import server

    # 1. Line 165: raw_p is not a file relative to cwd, but rel_p is
    monkeypatch.chdir(tmp_path)
    found = server.get_scenario_file("amrsim-participants/scenarios/01_clear.json")
    assert found is not None

    # 2. Line 182: candidate without extension
    mock_base = tmp_path / "mock_scen"
    mock_base.mkdir()
    no_ext = mock_base / "custom_raw"
    no_ext.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server, "SCENARIOS_DIR", mock_base)
    monkeypatch.setattr(server, "TEAM_SCENARIOS_DIR", tmp_path / "non_existent_1")
    monkeypatch.setattr(server, "BACKEND_SCENARIOS_DIR", tmp_path / "non_existent_2")
    assert server.get_scenario_file("custom_raw") == no_ext

    # 3. Line 185: glob matching prefix
    prefix_file = mock_base / "testprefix_variant.json"
    prefix_file.write_text("{}", encoding="utf-8")
    assert server.get_scenario_file("testprefix") == prefix_file


def test_run_simulation_corrupt_report(tmp_path, monkeypatch):
    import server
    from unittest.mock import MagicMock

    rep_path = tmp_path / "01_clear.json"
    rep_path.write_text("not json content", encoding="utf-8")

    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: MagicMock(returncode=0, stdout="", stderr=""),
    )

    res = server.run_simulation("01_clear")
    assert res["exitCode"] == 0
    assert res["report"] is None


def test_checkpoint_spacing_skip(monkeypatch):
    import server

    # Two checkpoints very close in time (< 15.0s) to trigger line 834 skip
    ticks = [
        {"t": 1.0, "x": 0.0, "y": 0.0},
        {"t": 2.0, "x": 1.0, "y": 1.0},
        {"t": 3.0, "x": 2.0, "y": 2.0},
        {"t": 4.0, "x": 3.0, "y": 3.0},
        {"t": 5.0, "x": 4.0, "y": 4.0},
        {"t": 6.0, "x": 5.0, "y": 5.0},
        {"t": 7.0, "x": 6.0, "y": 6.0},
        {"t": 8.0, "x": 7.0, "y": 7.0},
    ]
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"raw_ticks": ticks, "ticks": ticks},
    )
    # Episode with t_start=3.0 so nearby ticks are skipped
    mock_episodes = [{"id": "ep1", "t_start": 3.0, "cost": -1.0}]
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda s: {"score": {"episodes": mock_episodes}},
    )

    vm = server.build_episodes_view_model("test_chk_skip")
    assert len(vm["episodes"]) >= 1


def test_build_episodes_with_episodes_but_empty_ticks(monkeypatch):
    import server
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"raw_ticks": [], "ticks": []},
    )
    mock_episodes = [{"id": "ep1", "t_start": 5.0, "cost": -2.0, "type": "warning"}]
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda s: {"score": {"episodes": mock_episodes}},
    )
    vm = server.build_episodes_view_model("test_empty_ticks_with_raw_eps")
    assert len(vm["episodes"]) == 1
    assert vm["episodes"][0]["telemetrySnapshot"] is None


def test_server_entrypoint_main():
    import server
    from unittest.mock import patch
    import runpy

    with patch.object(sys, "argv", ["server.py", "--help"]):
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(Path(server.__file__)), run_name="__main__")
        assert exc.value.code == 0






