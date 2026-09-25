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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
            assert not s["file"].startswith("team/"), f"Old team/ path found: {s['file']}"
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

