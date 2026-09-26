"""Tests for AMR SafeRoute SDUI server, scenario management, and CSV export."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "arm"))

import server
from server import (
    AMRServerHandler,
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
    assert (
        normalize_scenario_id("backend\\scenarios\\s2_container_block.json") == "s2_container_block"
    )
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
    """Проверка контракта эпизодов: непустой список, поле source и нулевые вехи миссий."""
    valid_sources = {"report", "mission", "telemetry", "checkpoint"}

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
            assert "source" in ep, f"Episode without source for {sc_id}: {ep}"
            assert ep["source"] in valid_sources, f"Unknown episode source: {ep['source']}"

        # Вехи миссий информационные: недоставка в amrsim не штрафуется, цена всегда 0.0
        mission_eps = [e for e in episodes if e.get("source") == "mission"]
        for ep in mission_eps:
            assert ep["cost"] == 0.0, f"Mission milestone with non-zero cost: {ep}"

        # Журнал штрафов считается только по эпизодам отчета, без вех и пометок телеметрии
        report_eps = [e for e in episodes if e.get("source") == "report"]
        expected_warnings = len(
            [e for e in report_eps if e.get("severity") in ("warning", "critical")]
        )
        assert ep_vm["summary"]["warningsCount"] == expected_warnings, (
            f"warningsCount must count only report episodes for {sc_id}"
        )


def test_replay_view_model_missions_match_report():
    """Подписи миссий в модели Replay совпадают с точками отчета и метками POINT_LABELS."""
    for sc_id in ["04_busy_yard", "s1_pallet_2m"]:
        sc = normalize_scenario_id(sc_id)
        rep_vm = build_replay_view_model(sc)
        missions = rep_vm.get("missions")
        assert missions, f"Replay missions are empty for scenario: {sc}"

        report = get_scenario_report(sc)
        assert report is not None, f"Report not found for scenario: {sc}"
        report_missions = report.get("missions", [])
        assert report_missions, f"Report missions are empty for scenario: {sc}"
        report_pairs = {(m.get("id"), m.get("from"), m.get("to")) for m in report_missions}

        for m in missions:
            assert "id" in m
            assert "from" in m
            assert "to" in m
            assert "deadline_s" in m
            assert "t_start" in m
            assert m["t_start"] >= 0.0
            # Подписи строятся из POINT_LABELS с fallback на сам ключ точки
            assert m["fromLabel"] == server.POINT_LABELS.get(m["from"], m["from"])
            assert m["toLabel"] == server.POINT_LABELS.get(m["to"], m["to"])
            assert (m["id"], m["from"], m["to"]) in report_pairs, (
                f"Replay mission {m} does not match report missions for {sc}"
            )

    # Контрольная проверка известных меток для сценария с реальным логом тактов
    known = build_replay_view_model("04_busy_yard")
    first = known["missions"][0]
    assert first["from"] == "warehouse"
    assert first["fromLabel"] == "Склад"
    assert first["toLabel"] == server.POINT_LABELS[first["to"]]
    assert first["deadline_s"] > 0.0


def test_get_scenario_log_path_prefers_own_scenario_log(tmp_path, monkeypatch):
    """Лог своего сценария из results/own_scenarios/logs приоритетнее образца."""
    logs_dir = tmp_path / "results" / "own_scenarios" / "logs"
    logs_dir.mkdir(parents=True)
    own_log = logs_dir / "s1_pallet_2m.jsonl"
    own_log.write_text("", encoding="utf-8")

    monkeypatch.setattr(server, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(server, "OUT_DIR", tmp_path / "out")

    assert get_scenario_log_path("s1_pallet_2m") == own_log


def test_csv_export_format_and_rows():
    """Verify that CSV export contains valid columns and multiple data rows for every scenario."""
    expected_headers = [
        "Episode ID",
        "Type",
        "Category",
        "Severity",
        "Start (s)",
        "End (s)",
        "X",
        "Y",
        "Speed (m/s)",
        "Hum Dist (m)",
        "Obj Dist (m)",
        "PE Error (m)",
        "Cost (pts)",
        "Explanation",
    ]

    for sc_id in ALL_SCENARIO_IDS:
        ep_vm = build_episodes_view_model(sc_id)
        episodes = ep_vm.get("episodes", [])
        assert len(episodes) > 0

        lines = [",".join(expected_headers)]
        for ep in episodes:
            tk_snap = ep.get("telemetrySnapshot") or {}
            v_val = (
                f"{tk_snap.get('v', ''):.2f}" if isinstance(tk_snap.get("v"), (int, float)) else ""
            )
            hum_val = (
                f"{tk_snap.get('hum', ''):.2f}"
                if isinstance(tk_snap.get("hum"), (int, float))
                else ""
            )
            obj_val = (
                f"{tk_snap.get('obj', ''):.2f}"
                if isinstance(tk_snap.get("obj"), (int, float))
                else ""
            )
            pe_val = (
                f"{tk_snap.get('pe_error', ''):.4f}"
                if isinstance(tk_snap.get("pe_error"), (int, float))
                else ""
            )
            cost_val = f"{ep.get('cost', 0.0):.2f}"
            expl = str(ep.get("ruleExplanation", "")).replace('"', '""')

            lines.append(
                f"{ep.get('id')},{ep.get('type')},{ep.get('category')},{ep.get('severity', 'info')},"
                f"{ep.get('t_start')},{ep.get('t_end')},{ep.get('x')},{ep.get('y')},"
                f'{v_val},{hum_val},{obj_val},{pe_val},{cost_val},"{expl}"'
            )

        csv_content = "\n".join(lines)
        csv_lines = [line for line in csv_content.splitlines() if line.strip()]

        # Ensure header + at least 1 data row
        assert len(csv_lines) >= 2, f"CSV has no data rows for {sc_id}"
        assert csv_lines[0] == ",".join(expected_headers)


@pytest.fixture(scope="module")
def http_server():
    """Start local test server on a free port."""
    from http.server import ThreadingHTTPServer

    dist_created = False
    index_created = False
    index_file = server.FRONTEND_DIST / "index.html"
    if not server.FRONTEND_DIST.exists():
        server.FRONTEND_DIST.mkdir(parents=True, exist_ok=True)
        dist_created = True
    if not index_file.exists():
        index_file.write_text(
            "<!DOCTYPE html><html><body>ARM Safe Route</body></html>", encoding="utf-8"
        )
        index_created = True

    srv = ThreadingHTTPServer(("127.0.0.1", 0), AMRServerHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()

    if index_created and index_file.exists():
        index_file.unlink()
    if dist_created and server.FRONTEND_DIST.exists():
        try:
            server.FRONTEND_DIST.rmdir()
        except OSError:
            pass


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
    for test_sc in [
        "01_clear",
        "02_gnss_shadow_easy",
        "s1_pallet_2m",
        "s2_container_block",
        "s3_wall_removed",
    ]:
        url = f"{http_server}/api/export/csv?scenario={test_sc}"
        with urlopen(url) as resp:
            assert resp.status == 200
            assert "text/csv" in resp.headers.get("Content-Type", "")
            content = resp.read().decode("utf-8")
            lines = [line for line in content.splitlines() if line.strip()]
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
    from server import get_scenario_file

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
    # Force report load error
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(server, "RESULTS_DIR", tmp_path)
    bad_rep = tmp_path / "bad_rep.json"
    bad_rep.write_text("{broken json", encoding="utf-8")
    res = server.get_scenario_report("bad_rep")
    assert res is None


def test_get_scenario_log_path_none(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)
    monkeypatch.setattr(server, "ROOT_DIR", tmp_path)
    assert server.get_scenario_log_path("missing") is None


def test_get_scenario_log_path_unknown_returns_none_without_mock():
    """Неизвестный сценарий возвращает None и не подставляет чужой образец 04_busy_yard."""
    assert server.get_scenario_log_path("totally_unknown_scenario_xyz") is None


def test_run_simulation_missing_scen():
    from server import run_simulation

    with pytest.raises(FileNotFoundError):
        run_simulation("non_existent_scen_xyz")


def test_resolve_python_command_prefers_uv(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    cmd = server.resolve_python_command()
    assert cmd == ["/usr/bin/uv", "run", "--project", str(server.ROOT_DIR), "python"]


def test_resolve_python_command_falls_back_to_supported_interpreter(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        server.shutil,
        "which",
        lambda name: "/usr/bin/python3.13" if name == "python3.13" else None,
    )

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0 if cmd[0].endswith("python3.13") else 1)

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.sys, "executable", "/usr/bin/python3.9")

    assert server.resolve_python_command() == ["/usr/bin/python3.13"]


def test_resolve_python_command_raises_when_no_supported_interpreter(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(server.shutil, "which", lambda name: None)
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: MagicMock(returncode=1))
    monkeypatch.setattr(server.sys, "executable", "/usr/bin/python3.9")

    with pytest.raises(RuntimeError, match="3.10"):
        server.resolve_python_command()


def test_resolve_python_command_probe_requires_numpy(monkeypatch):
    """Проба отсеивает >= 3.10 без numpy: иначе amrsim падает ModuleNotFoundError."""
    from unittest.mock import MagicMock

    seen: list[list[str]] = []

    monkeypatch.setattr(
        server.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in ("python3.13", "python3.12") else None,
    )
    monkeypatch.setattr(server.sys, "executable", "/usr/bin/python3.13")

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        # только 3.13 годен (3.12 числится без numpy)
        return MagicMock(returncode=0 if cmd[0].endswith("python3.13") else 1)

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    cmd = server.resolve_python_command()

    assert cmd == ["/usr/bin/python3.13"]
    assert all("-c" in probe for probe in seen)
    assert all("numpy" in probe[probe.index("-c") + 1] for probe in seen)


def test_run_simulation_mocked(tmp_path, monkeypatch):
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
    assert empty_map["referencePaths"] == []

    # Header with map and missions
    header = {
        "map": {
            "bounds": [0, 0, 100, 100],
            "points": {"ptA": {"x": 10.0, "y": 20.0}},
            "buildings": [],
            "zones": [],
        },
        "missions": [
            {"id": "m1", "reference_path": [[10.0, 20.0], [30.0, 40.0]]}
        ],
    }
    header_map = extract_map_data(None, header)
    assert header_map["bounds"] == [0, 0, 100, 100]
    assert "ptA" in header_map["points"]
    assert header_map["referencePaths"] == [[[10.0, 20.0], [30.0, 40.0]]]


def test_parse_ticks_log_edge_cases(tmp_path, monkeypatch):

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
    payload = json.dumps(
        {
            "scenario": "01_clear",
            "controller": "team/controller.py",
            "seed": 7,
            "cheatPose": False,
        }
    ).encode("utf-8")

    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["exitCode"] == 0
        assert data["score"] == 95.0
        assert "logs" in data
        assert any("amrsim simulated run ok" in line for line in data["logs"])


def test_api_run_simulation_error_branch(http_server, monkeypatch):

    def mock_run_fail(*args, **kwargs):
        raise RuntimeError("Controller crash simulated")

    monkeypatch.setattr(server, "run_simulation", mock_run_fail)

    url = f"{http_server}/api/run"
    req = Request(url, data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 500


def test_server_main_execution(monkeypatch):
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
        assert any("warning: some warning" in line for line in data["logs"])


def test_api_static_serving_404_when_no_frontend_dist(http_server, monkeypatch):
    monkeypatch.setattr(server, "FRONTEND_DIST", Path("/non_existent_frontend_dist_dir"))
    with pytest.raises(HTTPError) as exc_info:
        urlopen(f"{http_server}/nonexistent_static_path_123")
    assert exc_info.value.code == 404


def test_api_static_serving_existing_file(http_server, monkeypatch):
    # Set FRONTEND_DIST to ROOT_DIR so super().do_GET() serves pyproject.toml in cwd
    monkeypatch.setattr(server, "FRONTEND_DIST", server.ROOT_DIR)
    with urlopen(f"{http_server}/pyproject.toml") as resp:
        assert resp.status == 200


def test_get_scenario_file_edge_cases(tmp_path, monkeypatch):

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
    import runpy
    from unittest.mock import patch

    with patch.object(sys, "argv", ["server.py", "--help"]):
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(Path(server.__file__)), run_name="__main__")
        assert exc.value.code == 0


def test_checkpoint_telemetry_snapshot_matches_tick_clearance(monkeypatch):
    """Снимок контрольной точки берет hum и obj из своего тика tk, а не из предыдущего цикла."""
    ticks = [
        {"t": 0.0, "x": 0.0, "y": 0.0, "v": 0.5, "hum": 9.99, "obj": 8.88},
        {"t": 20.0, "x": 10.0, "y": 5.0, "v": 0.8, "hum": 2.34, "obj": 1.56},
        {"t": 40.0, "x": 20.0, "y": 10.0, "v": 0.7, "hum": 3.45, "obj": 2.67},
        {"t": 60.0, "x": 30.0, "y": 15.0, "v": 0.6, "hum": 4.56, "obj": 3.78},
        {"t": 80.0, "x": 40.0, "y": 20.0, "v": 0.0, "hum": 5.67, "obj": 4.89},
    ]
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"raw_ticks": ticks, "ticks": ticks, "totalTicks": len(ticks), "duration": 80.0},
    )
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda s: {"score": {"episodes": []}, "missions": []},
    )

    vm = server.build_episodes_view_model("test_checkpoint_clearance")
    checkpoints = [e for e in vm["episodes"] if e.get("source") == "checkpoint"]
    assert len(checkpoints) >= 1

    for chk in checkpoints:
        t_chk = chk["t_start"]
        matching_tick = next((tk for tk in ticks if abs(tk["t"] - t_chk) < 1e-3), None)
        assert matching_tick is not None, f"No matching tick found for checkpoint at t={t_chk}"
        snap = chk["telemetrySnapshot"]
        assert snap is not None
        assert snap["hum"] == round(matching_tick["hum"], 2)
        assert snap["obj"] == round(matching_tick["obj"], 2)


# ==============================================================================
# Tests for Defect Fixes (1 through 8)
# ==============================================================================


def test_api_run_malformed_payload_non_dict(http_server):
    url = f"{http_server}/api/run"
    req = Request(url, data=b"[1, 2, 3]", headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 400
    err_body = json.loads(exc_info.value.read().decode("utf-8"))
    assert "error" in err_body
    assert "Bad Request" in err_body["error"]


def test_api_run_malformed_payload_invalid_seed(http_server):
    url = f"{http_server}/api/run"
    payload = json.dumps({"scenario": "01_clear", "seed": "not-an-integer"}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 400
    err_body = json.loads(exc_info.value.read().decode("utf-8"))
    assert "seed must be an integer" in err_body["error"]


def test_api_run_malformed_payload_invalid_controller(http_server):
    url = f"{http_server}/api/run"
    payload = json.dumps({"scenario": "01_clear", "controller": "unauthorized/path.py"}).encode(
        "utf-8"
    )
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 400
    err_body = json.loads(exc_info.value.read().decode("utf-8"))
    assert "invalid controller path" in err_body["error"]


def test_api_run_malformed_payload_invalid_scenario(http_server):
    url = f"{http_server}/api/run"
    payload = json.dumps({"scenario": ""}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req)
    assert exc_info.value.code == 400
    err_body = json.loads(exc_info.value.read().decode("utf-8"))
    assert "scenario must be a non-empty string" in err_body["error"]


def test_api_ui_replay_invalid_seed_query_param(http_server):
    url = f"{http_server}/api/ui/replay?scenario=01_clear&seed=invalid_seed_val"
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["seed"] == 7


def test_api_ui_replay_error_handling(http_server, monkeypatch):
    monkeypatch.setattr(
        server,
        "build_replay_view_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Replay crash")),
    )
    url = f"{http_server}/api/ui/replay?scenario=01_clear"
    with pytest.raises(HTTPError) as exc_info:
        urlopen(url)
    assert exc_info.value.code == 500


def test_parse_ticks_log_corrupt_lines(tmp_path, monkeypatch):
    log_file = tmp_path / "corrupt_scenario.jsonl"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write('{"type": "header", "map": {}}\n')
        f.write("corrupted json not a valid line\n")
        f.write("{broken json}\n")
        f.write('{"type": "tick", "t": 1.0, "x": 0.0, "y": 0.0}\n')
        f.write("\n")
        f.write('{"type": "tick", "t": 2.0, "x": 1.0, "y": 0.0}\n')

    monkeypatch.setattr(server, "get_scenario_log_path", lambda s: log_file)
    monkeypatch.setattr(server, "_TICKS_CACHE", server.BoundedCache(maxsize=10))

    ticks_data = server.parse_ticks_log("corrupt_scenario")
    assert ticks_data["header"] is not None
    assert ticks_data["totalTicks"] == 2
    assert len(ticks_data["raw_ticks"]) == 2


def test_api_ticks_error_handling(http_server, monkeypatch):
    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Ticks error")),
    )
    url = f"{http_server}/api/ticks?scenario=01_clear"
    with pytest.raises(HTTPError) as exc_info:
        urlopen(url)
    assert exc_info.value.code == 500


def test_format_time_edge_cases():
    from server import format_time

    assert format_time(0.0) == "00:00"
    assert format_time(65.0) == "01:05"
    assert format_time(-65.0) == "-01:05"
    assert format_time(-5.0) == "-00:05"
    assert format_time(-0.0) == "00:00"
    assert format_time(None) == "--:--"
    assert format_time(float("nan")) == "--:--"
    assert format_time(float("inf")) == "--:--"
    assert format_time("invalid") == "--:--"


def test_compute_step_distribution_zero_or_negative():
    from server import compute_step_distribution

    dist_zero = compute_step_distribution(0, 2.5, 30.0)
    assert len(dist_zero) == 18
    assert all(b["count"] == 0 for b in dist_zero)
    assert sum(b["count"] for b in dist_zero) == 0

    dist_neg = compute_step_distribution(-5, 2.5, 30.0)
    assert all(b["count"] == 0 for b in dist_neg)
    assert sum(b["count"] for b in dist_neg) == 0


def test_run_simulation_concurrency_mutex(monkeypatch):
    import time
    from unittest.mock import MagicMock

    active_runs = []
    max_active = 0
    lock = threading.Lock()

    def mock_subp_run(*args, **kwargs):
        nonlocal max_active
        with lock:
            active_runs.append(1)
            current_active = len(active_runs)
            if current_active > max_active:
                max_active = current_active
        time.sleep(0.05)
        with lock:
            active_runs.pop()
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(server.subprocess, "run", mock_subp_run)

    threads = []
    for _ in range(4):
        t = threading.Thread(target=server.run_simulation, args=("01_clear",))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # With _SIM_LOCK, concurrent runs are serialized, so max_active is 1
    assert max_active == 1


def test_view_models_null_fields_tolerance(monkeypatch):
    mock_ticks = [
        {"t": None, "v": None, "x": None, "y": None, "pe": [1.0, 2.0], "pe_error": None},
        {"t": 1.0, "v": 1.2, "x": 0.5, "y": 0.5, "pe": None},
    ]
    mock_episodes = [
        {"id": "ep1", "t_start": None, "t_end": None, "cost": None, "x": None, "y": None},
    ]
    mock_missions = [
        {
            "id": "m1",
            "t_start": None,
            "t_arrival": None,
            "max_hold_dist": None,
            "reference_length_m": None,
        }
    ]

    monkeypatch.setattr(
        server,
        "parse_ticks_log",
        lambda s: {"raw_ticks": mock_ticks, "ticks": mock_ticks, "header": None},
    )
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda s: {
            "score": {
                "total": None,
                "episodes": mock_episodes,
                "blocks": {"delivery": None},
                "max": {"delivery": None},
            },
            "missions": mock_missions,
            "step_time_ms": {"n": None, "mean": None, "max": None},
        },
    )

    dash_vm = server.build_dashboard_view_model("01_clear")
    assert dash_vm["totalScore"] == 0.0

    rep_vm = server.build_replay_view_model("01_clear")
    assert rep_vm["episodes"][0]["cost"] == 0.0

    ep_vm = server.build_episodes_view_model("01_clear")
    assert ep_vm["summary"]["totalCost"] == 0.0

    miss_vm = server.build_missions_view_model("01_clear")
    assert miss_vm["summary"]["deliveryScore"] == 40.0

    an_vm = server.build_analytics_view_model("01_clear")
    assert an_vm["totalScore"] == 0.0


def test_api_export_csv_error_handling(http_server, monkeypatch):
    monkeypatch.setattr(
        server,
        "build_episodes_view_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("CSV generation error")),
    )
    url = f"{http_server}/api/export/csv?scenario=01_clear"
    with pytest.raises(HTTPError) as exc_info:
        urlopen(url)
    assert exc_info.value.code == 500
    err = json.loads(exc_info.value.read().decode("utf-8"))
    assert "CSV generation error" in err["error"]


def test_bounded_cache_eviction_and_lru():
    cache = server.BoundedCache(maxsize=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    assert len(cache) == 3
    assert list(cache.keys()) == ["a", "b", "c"]

    # Access 'a' to make it most recently used
    _ = cache["a"]
    assert list(cache.keys()) == ["b", "c", "a"]

    # Insert 4th item, 'b' (oldest) should be evicted
    cache["d"] = 4
    assert len(cache) == 3
    assert "b" not in cache
    assert list(cache.keys()) == ["c", "a", "d"]

    # get() also updates LRU
    assert cache.get("c") == 3
    assert list(cache.keys()) == ["a", "d", "c"]
    cache["e"] = 5
    assert "a" not in cache
    assert len(cache) == 3


def test_get_scenario_file_none():
    res = get_scenario_file(None)
    assert res is not None
    assert res.exists()
    assert res.name == "04_busy_yard.json"


def test_extract_map_data_null_points():
    # Null map object
    d1 = server.extract_map_data({"map": None}, None)
    assert d1["points"] == {}

    # Null points dictionary
    d2 = server.extract_map_data({"map": {"points": None}}, None)
    assert d2["points"] == {}

    # Null point within points dictionary
    d3 = server.extract_map_data(
        {"map": {"points": {"p1": None, "p2": {"x": None, "y": None}}}}, None
    )
    assert "p1" in d3["points"]
    assert d3["points"]["p1"]["x"] == 0.0
    assert d3["points"]["p1"]["y"] == 0.0
    assert d3["points"]["p2"]["x"] == 0.0
    assert d3["points"]["p2"]["y"] == 0.0


def test_view_models_with_null_report_collections(monkeypatch):
    """View models handle report with null episodes, null missions, null blocks without crash."""
    mock_report = {
        "scenario": "01_clear",
        "missions": None,
        "score": {
            "total": None,
            "deliveries": None,
            "episodes": None,
            "blocks": None,
            "max": None,
        },
    }
    monkeypatch.setattr(server, "get_scenario_report", lambda *args, **kwargs: mock_report)

    dash_vm = server.build_dashboard_view_model("01_clear")
    assert dash_vm["deliveriesTotal"] == 2
    assert dash_vm["safetyWarnings"] == 0

    rep_vm = server.build_replay_view_model("01_clear")
    assert rep_vm["episodes"] == []

    ep_vm = server.build_episodes_view_model("01_clear")
    assert isinstance(ep_vm["episodes"], list)

    miss_vm = server.build_missions_view_model("01_clear")
    assert miss_vm["missions"] == []
    assert miss_vm["summary"]["total"] == 0


def test_build_dashboard_view_model_non_string_or_null_mission_id(monkeypatch):
    """build_dashboard_view_model handles null or non-string (int, bool) mission ID."""
    mock_report = {
        "scenario": "01_clear",
        "missions": [
            {"id": None, "to": "shop_a", "delivered": True, "t_arrival": 10.0},
            {"id": 42, "to": "warehouse", "delivered": False, "t_end": 20.0},
            {"id": "", "to": "shop_b", "delivered": True, "t_arrival": 30.0},
        ],
        "score": {"total": 50, "episodes": []},
    }
    monkeypatch.setattr(server, "get_scenario_report", lambda *args, **kwargs: mock_report)

    dash_vm = server.build_dashboard_view_model("01_clear")
    assert len(dash_vm["recentEvents"]) >= 3
    event_ids = [e["id"] for e in dash_vm["recentEvents"]]
    assert "e-m-m1" in event_ids
    assert "e-m-42" in event_ids


def test_parse_ticks_log_null_coordinates(tmp_path, monkeypatch):
    """parse_ticks_log handles null coordinates and telemetry gracefully."""
    log_file = tmp_path / "null_coords.jsonl"
    lines = [
        json.dumps({"type": "header", "scenario": "null_coords", "missions": []}),
        json.dumps({
            "type": "tick",
            "t": 1.0,
            "x": None,
            "y": None,
            "th": None,
            "pe": [None, None],
            "obj": None,
            "hum": None,
            "v": None,
        }),
        json.dumps({
            "type": "tick",
            "t": 2.0,
            "x": 1.0,
            "y": 2.0,
            "th": 0.5,
            "pe": None,
            "obj": 0.5,
            "hum": 2.0,
            "v": 0.2,
        }),
    ]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setattr(server, "get_scenario_log_path", lambda *args: log_file)
    server._TICKS_CACHE.clear()

    res = server.parse_ticks_log("null_coords")
    assert res["totalTicks"] == 2
    ticks = res["ticks"]
    assert len(ticks) >= 1
    t0 = res["raw_ticks"][0]
    assert t0["pe_error"] == 0.0
    assert "lidarRays" in ticks[0]


def test_build_analytics_view_model_null_score_and_blocks(monkeypatch):
    """build_analytics_view_model handles null score and null blocks/max safely."""
    # Test with {"score": {"blocks": None, "max": None}}
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {"score": {"blocks": None, "max": None}},
    )
    vm = build_analytics_view_model("01_clear")
    assert vm["totalScore"] == 0.0
    assert len(vm["blocks"]) == 6
    for b in vm["blocks"]:
        assert b["achieved"] == 0.0

    # Test with {"score": None}
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {"score": None},
    )
    vm_none = build_analytics_view_model("01_clear")
    assert vm_none["totalScore"] == 0.0
    assert len(vm_none["blocks"]) == 6
    for b in vm_none["blocks"]:
        assert b["achieved"] == 0.0


def test_view_models_null_step_time_ms(monkeypatch):
    """build_dashboard_view_model and build_analytics_view_model handle null step_time_ms."""
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {"step_time_ms": None, "score": {"total": 85.0}},
    )
    dash_vm = build_dashboard_view_model("01_clear")
    assert dash_vm["controllerState"]["meanDelayMs"] == 2.7
    assert dash_vm["controllerState"]["maxDelayMs"] == 35.0

    analytics_vm = build_analytics_view_model("01_clear")
    assert analytics_vm["computeBudget"]["mean_step_ms"] == 2.7
    assert analytics_vm["computeBudget"]["max_step_ms"] == 35.0


def test_api_scenarios_null_score(http_server, monkeypatch):
    """/api/scenarios endpoint handles scenario reports where score is None."""
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda sc_id: {"score": None},
    )
    url = f"{http_server}/api/scenarios"
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert len(data) >= 1
        for sc in data:
            assert sc["hasReport"] is True
            assert sc["score"] is None


def test_build_missions_view_model_unrun_or_none_report(monkeypatch):
    """build_missions_view_model handles unrun scenario and None report safely."""
    # 1. Nonexistent/unrun scenario directly without monkeypatch
    vm = build_missions_view_model("nonexistent_or_unrun")
    assert vm["scenario"] == "nonexistent_or_unrun"
    assert vm["missions"] == []
    assert vm["summary"]["completed"] == 0
    assert vm["summary"]["total"] == 0
    assert vm["summary"]["deliveryScore"] == 40.0
    assert vm["summary"]["maxDeliveryScore"] == 40.0
    assert vm["summary"]["efficiencyScore"] == 14.0
    assert vm["summary"]["maxEfficiencyScore"] == 15.0

    # 2. Monkeypatch get_scenario_report to return None
    monkeypatch.setattr(server, "get_scenario_report", lambda *args: None)
    vm_none = build_missions_view_model("01_clear")
    assert vm_none["scenario"] == "01_clear"
    assert vm_none["missions"] == []
    assert vm_none["summary"]["completed"] == 0
    assert vm_none["summary"]["total"] == 0

    # 3. Monkeypatch get_scenario_report with None score and None missions
    monkeypatch.setattr(server, "get_scenario_report", lambda *args: {"score": None, "missions": None})
    vm_empty = build_missions_view_model("01_clear")
    assert vm_empty["missions"] == []
    assert vm_empty["summary"]["completed"] == 0


def test_build_dashboard_view_model_null_items_in_lists(monkeypatch):
    """build_dashboard_view_model handles null/non-dict items in missions and episodes."""
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {
            "missions": [None, {"id": "m1", "to": "shop_a", "delivered": True, "t_arrival": 50.0}],
            "score": {
                "total": 85.0,
                "deliveries": 1,
                "episodes": [None, {"type": "collision", "cost": -30.0, "t_start": 10.0}],
            },
        },
    )
    dash_vm = build_dashboard_view_model("01_clear")
    assert "recentEvents" in dash_vm
    event_ids = [e["id"] for e in dash_vm["recentEvents"]]
    assert "e-m-m1" in event_ids
    assert "e-ep-1" in event_ids

    # Completely null items list test
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {
            "missions": [None],
            "score": {"total": 50.0, "episodes": [None]},
        },
    )
    dash_vm_all_null = build_dashboard_view_model("01_clear")
    assert "recentEvents" in dash_vm_all_null
    # Only the default system startup event is present, no mission or episode events
    non_sys_events = [e for e in dash_vm_all_null["recentEvents"] if e["id"] != "e-sys-start"]
    assert len(non_sys_events) == 0


def test_get_scenario_report_non_dict_json(tmp_path, monkeypatch):
    """get_scenario_report strictly returns None if the report JSON is non-dict (e.g. list, string)."""
    server._REPORT_CACHE.clear()
    monkeypatch.setattr(server, "_REPORT_CACHE", server.BoundedCache(maxsize=10))

    # Test 1: JSON array [1, 2, 3]
    list_json_path = tmp_path / "list_report.json"
    list_json_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    monkeypatch.setattr(
        server,
        "OUT_DIR",
        tmp_path,
    )
    # Target "list_report"
    assert get_scenario_report("list_report") is None

    # Test 2: JSON string "error"
    str_json_path = tmp_path / "str_report.json"
    str_json_path.write_text(json.dumps("error"), encoding="utf-8")
    assert get_scenario_report("str_report") is None

    # Test 3: JSON number 123
    num_json_path = tmp_path / "num_report.json"
    num_json_path.write_text(json.dumps(123), encoding="utf-8")
    assert get_scenario_report("num_report") is None


def test_build_replay_missions_null_or_non_dict_items():
    """build_replay_missions ignores non-dict items in header missions and raw_ticks without failing."""
    header = {
        "missions": [
            None,
            "not-a-dict",
            123,
            {"id": "m1", "from": "warehouse", "to": "shop_a", "deadline_s": 50.0},
            {"id": "m2", "from": "shop_a", "to": "shop_b", "deadline_s": 60.0},
        ]
    }
    raw_ticks = [
        None,
        "invalid_tick",
        42,
        {"t": 1.5, "m": "m1"},
        {"t": 3.0, "m": "m2"},
    ]

    missions = server.build_replay_missions(header, raw_ticks)
    assert len(missions) == 2
    assert missions[0]["id"] == "m1"
    assert missions[0]["t_start"] == 1.5
    assert missions[0]["deadline_s"] == 50.0
    assert missions[1]["id"] == "m2"
    assert missions[1]["t_start"] == 3.0
    assert missions[1]["deadline_s"] == 60.0


def test_view_models_non_dict_score_and_blocks(monkeypatch):
    """View models handle reports where score, score.blocks, or score.max are non-dict types."""
    # 1. score is string
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {"score": "not_a_dict", "missions": []},
    )
    dash_vm = build_dashboard_view_model("01_clear")
    assert dash_vm["totalScore"] == 0.0

    missions_vm = build_missions_view_model("01_clear")
    assert missions_vm["summary"]["deliveryScore"] == 40.0
    assert missions_vm["summary"]["maxDeliveryScore"] == 40.0

    analytics_vm = build_analytics_view_model("01_clear")
    assert analytics_vm["totalScore"] == 0.0
    for block in analytics_vm["blocks"]:
        assert block["achieved"] == 0.0

    episodes_vm = build_episodes_view_model("01_clear")
    assert episodes_vm["summary"]["fatalCount"] == 0

    replay_vm = build_replay_view_model("01_clear")
    assert isinstance(replay_vm["episodes"], list)

    # 2. score is int, blocks is string, max is list
    monkeypatch.setattr(
        server,
        "get_scenario_report",
        lambda *args: {
            "score": {
                "total": 75.0,
                "blocks": "invalid_blocks",
                "max": [1, 2, 3],
            },
            "missions": [],
        },
    )
    dash_vm2 = build_dashboard_view_model("01_clear")
    assert dash_vm2["totalScore"] == 75.0

    missions_vm2 = build_missions_view_model("01_clear")
    assert missions_vm2["summary"]["deliveryScore"] == 40.0
    assert missions_vm2["summary"]["maxDeliveryScore"] == 40.0

    analytics_vm2 = build_analytics_view_model("01_clear")
    assert analytics_vm2["totalScore"] == 75.0
    for block in analytics_vm2["blocks"]:
        assert block["achieved"] == 0.0


def test_api_scenarios_non_dict_report(http_server, monkeypatch):
    """/api/scenarios endpoint safely handles non-dict reports and non-dict score values."""
    # Report itself is non-dict
    monkeypatch.setattr(server, "get_scenario_report", lambda sc_id: "error_not_dict")
    url = f"{http_server}/api/scenarios"
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        for sc in data:
            assert sc["hasReport"] is False
            assert sc["score"] is None

def test_openapi_and_docs_endpoints(http_server):
    """Verify that /api/openapi.json returns valid OpenAPI 3.0 spec and /docs returns HTML."""
    openapi_url = f"{http_server}/api/openapi.json"
    with urlopen(openapi_url) as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        spec = json.loads(resp.read().decode("utf-8"))
        assert spec["openapi"] == "3.0.0"
        assert "paths" in spec
        assert "/api/scenarios" in spec["paths"]
        assert "/api/run" in spec["paths"]
        assert "/api/ui/replay" in spec["paths"]
        assert "components" in spec
        assert "ControlStepOutput" in spec["components"]["schemas"]

    docs_url = f"{http_server}/docs"
    with urlopen(docs_url) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        html = resp.read().decode("utf-8")
        assert "swagger-ui" in html
        assert "/api/openapi.json" in html


def test_arm_readme_and_openapi_status_contract(http_server):
    """Проверить строгое соответствие статусов схеме amr-1.0 в arm/README.md и OpenAPI."""
    readme_path = Path(__file__).resolve().parent.parent / "arm" / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    assert "holding" not in readme_text
    assert "docked" not in readme_text
    for st in ("moving", "waiting", "arrived", "lost", "estop"):
        assert st in readme_text

    openapi_url = f"{http_server}/api/openapi.json"
    with urlopen(openapi_url) as resp:
        spec = json.loads(resp.read().decode("utf-8"))
        status_schema = spec["components"]["schemas"]["ControlStepOutput"]["properties"]["status"]
        assert status_schema["enum"] == ["moving", "waiting", "arrived", "lost", "estop"]
        assert "holding" not in status_schema["enum"]
        assert "docked" not in status_schema["enum"]




