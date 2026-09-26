"""Утверждения колоды не расходятся с логами и не тащат чужой sha на речь."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from presentation_claims import (  # noqa: E402
    assert_cbf_not_wired,
    assert_moment_on_tick,
    assert_pure_pursuit_combat,
    assert_spoken_text,
    efficiency_is_only_gap,
    format_score_span,
    lost_run,
    nearest_tick,
    numpy_only,
    open_packet_subtitle,
    open_packet_title,
    parse_distance,
)

CURRENT = hashlib.sha256((ROOT / "team_dreamteam_4_0" / "controller.py").read_bytes()).hexdigest()[:16]
PACKET = "2f4a721eafcfb6ed"  # исторический хеш первого пакета, упоминаемый в PITCH и README


def test_spoken_text_rejects_report_sha():
    with pytest.raises(SystemExit, match="sha отчета"):
        assert_spoken_text("пакет %s" % PACKET, [PACKET, CURRENT])


def test_spoken_text_rejects_current_sha_too():
    with pytest.raises(SystemExit, match="sha отчета"):
        assert_spoken_text("файл %s" % CURRENT, [CURRENT])


def test_spoken_text_allows_scores():
    assert assert_spoken_text("свои прогоны 99.44-100", [PACKET]) == (
        "свои прогоны 99.44-100"
    )


def test_score_span_drops_trailing_zeros():
    assert format_score_span([99.44, 100.0, 99.97]) == "99.44-100"
    assert format_score_span([100.0, 100.0]) == "100"


def test_open_packet_title_names_foreign_sha():
    title = open_packet_title(28, [PACKET, PACKET], CURRENT, "99.22")
    assert PACKET in title
    assert "99.22" in title
    assert "этого кода" not in title


def test_open_packet_title_when_sha_matches():
    title = open_packet_title(28, [CURRENT], CURRENT, "99.22")
    assert title.startswith("28 прогонов этого кода")
    subtitle = open_packet_subtitle([CURRENT], CURRENT, False)
    assert "не результат" not in subtitle
    assert "Скрытых прогонов" in subtitle


def test_numpy_only_accepts_version_pin():
    assert numpy_only(["numpy>=1.24.0"])
    assert not numpy_only(["numpy>=1.24.0", "requests"])
    assert not numpy_only([])


def test_lost_run_is_contiguous_and_resumes():
    ticks = [
        {"t": 27.1, "st": "moving", "v": 1.0},
        {"t": 27.2, "st": "lost", "v": 0.0},
        {"t": 27.3, "st": "lost", "v": 0.0},
        {"t": 28.0, "st": "waiting", "v": 0.0},
        {"t": 28.1, "st": "moving", "v": 0.05},
    ]
    found = lost_run(ticks)
    assert found["count"] == 2
    assert found["t0"] == 27.2
    assert found["resume_t"] == 28.1


def test_lost_run_rejects_a_gap():
    ticks = [
        {"t": 1.0, "st": "lost", "v": 0.0},
        {"t": 1.1, "st": "moving", "v": 0.2},
        {"t": 1.2, "st": "lost", "v": 0.0},
    ]
    with pytest.raises(ValueError, match="не сплошным"):
        lost_run(ticks)


def test_moment_must_match_tick_note():
    moment = {"status": "moving", "v": 0.78, "t": 87.0}
    tick = {"t": 87.0, "st": "moving", "v": 0.78, "nt": "stop_person d=0.7"}
    assert nearest_tick([tick], 87.0) is tick
    assert_moment_on_tick(moment, tick, "stop_person")
    assert parse_distance(tick["nt"]) == 0.7
    with pytest.raises(ValueError, match="фрагмента"):
        assert_moment_on_tick(moment, tick, "dock")


def test_moments_json_matches_actual_logs():
    """Каждый найденный момент в moments.json обязан совпадать со строкой фактического лога."""
    moments_data = json.loads(
        (ROOT / "results" / "own_scenarios" / "moments.json").read_text(encoding="utf-8")
    )
    assert moments_data["controller_sha256"] == CURRENT
    for scen_entry in moments_data["scenarios"]:
        log_path = ROOT / scen_entry["log"]
        ticks = _ticks(str(log_path.relative_to(ROOT)))
        for m in scen_entry["moments"]:
            if not m.get("found"):
                continue
            tick = nearest_tick(ticks, m["t"])
            assert_moment_on_tick(m, tick, None)
            if "offset" in m["key"]:
                assert "offset" in (tick.get("note") or tick.get("nt") or "")
            elif "replan" in m["key"]:
                assert "replan" in (tick.get("note") or tick.get("nt") or "")
            elif "map_missing" in m["key"]:
                assert "map_missing" in (tick.get("note") or tick.get("nt") or "")
            elif "arrival" in m["key"]:
                assert "dock" in (tick.get("note") or tick.get("nt") or "")
            elif "lane_lost_status" in m["key"]:
                assert tick.get("st") == "lost"


def test_efficiency_gap_is_only_that_block():
    blocks = {"delivery": 40.0, "efficiency": 14.4, "safety": 25.0}
    maxima = {"delivery": 40.0, "efficiency": 15.0, "safety": 25.0}
    assert efficiency_is_only_gap(blocks, maxima)
    blocks["safety"] = 20.0
    assert not efficiency_is_only_gap(blocks, maxima)


def test_combat_path_rejects_wired_alternatives():
    assert_pure_pursuit_combat("v, w = self.pure_pursuit(pose, path)\n")
    with pytest.raises(ValueError, match="stanley"):
        assert_pure_pursuit_combat("self.pure_pursuit(pose, path)\nself.stanley(pose, path)\n")
    assert_cbf_not_wired("self.safety.limit(v)\n")
    with pytest.raises(ValueError, match="cbf_velocity_limit"):
        assert_cbf_not_wired("cbf_velocity_limit(d)\n")

    # Пакет контроллера не должен содержать неиспользуемые функции-альтернативы
    controller_pkg = ROOT / "team_dreamteam_4_0"
    for py_file in controller_pkg.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "def compute_stanley_cmd" not in text, f"Found compute_stanley_cmd in {py_file}"
        assert "def smooth_yaw_rate_quintic" not in text, f"Found smooth_yaw_rate_quintic in {py_file}"
        assert "def cbf_velocity_limit" not in text, f"Found cbf_velocity_limit in {py_file}"
        assert "CBF_ALPHA" not in text, f"Found CBF_ALPHA in {py_file}"
        assert "CBF_D_MIN_PED" not in text, f"Found CBF_D_MIN_PED in {py_file}"
        assert "CBF_D_MIN_STATIC" not in text, f"Found CBF_D_MIN_STATIC in {py_file}"
        assert "QuinticSpline1D" not in text, f"Found QuinticSpline1D in {py_file}"


def test_controller_package_has_no_quintic_spline():
    """Боевой пакет team_dreamteam_4_0 не содержит класс QuinticSpline1D."""
    controller_pkg = ROOT / "team_dreamteam_4_0"
    for py_file in controller_pkg.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "class QuinticSpline1D" not in text, f"Found QuinticSpline1D in {py_file}"
        assert "QuinticSpline1D" not in text, f"Found QuinticSpline1D reference in {py_file}"


def test_controller_package_has_no_cbf_constants():
    """Боевой пакет team_dreamteam_4_0 не содержит константы CBF."""
    controller_pkg = ROOT / "team_dreamteam_4_0"
    banned_cbf = ("CBF_ALPHA", "CBF_D_MIN_PED", "CBF_D_MIN_STATIC")
    for py_file in controller_pkg.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for sym in banned_cbf:
            assert sym not in text, f"Found {sym} in {py_file}"



def _ticks(relative):
    rows = []
    path = ROOT / relative
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "tick":
                rows.append(row)
    return rows


def test_pitch_matches_logged_moments_and_drops_old_claims():
    moments = json.loads(
        (ROOT / "results" / "own_scenarios" / "moments.json").read_text(encoding="utf-8")
    )
    pitch = (ROOT / "PITCH.md").read_text(encoding="utf-8")
    by_key = {}
    for section in moments["scenarios"]:
        for moment in section["moments"]:
            if moment.get("found"):
                by_key[(section["scenario"], section["seed"], moment["key"])] = moment
    for key in (
        ("s4_shadow_start_charger", 7, "arrival_charger"),
        ("s5_fog_inattentive", 7, "stop_person"),
        ("04_busy_yard", 7, "stop_person"),
        ("s4b_shadow_lane_lost", 1, "lane_lost_status"),
        ("s3_wall_removed", 7, "map_missing"),
        ("s1_pallet_2m", 7, "offset"),
        ("s2_container_block", 7, "replan"),
    ):
        moment = by_key[key]
        assert ("%.1f" % float(moment["t"])) in pitch
    person = by_key[("04_busy_yard", 7, "stop_person")]
    assert ("t=%.1f" % float(person["t"])) in pitch
    assert "04_busy_yard" in pitch
    assert person["status"] in pitch
    assert person["note"] in pitch
    assert "hum=0.311" in pitch
    lost = lost_run(
        _ticks("results/own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl")
    )
    assert "t=%.1f" % lost["resume_t"] in pitch
    assert "%d тактов" % lost["count"] in pitch
    assert "s4b_shadow_lane_lost_seed1" in pitch
    assert PACKET in pitch
    assert CURRENT in pitch
    for banned in ("98.88", "IMM", "60 сквозных", "Нагумо", "до 0.22"):
        assert banned not in pitch


def test_s4b_lost_sequence_and_recovery():
    """Сценарий s4b seed 1: сплошной участок lost со стоянкой v=0 и возобновление движения."""
    ticks = _ticks("results/own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl")
    info = lost_run(ticks)
    assert info["count"] == 8
    assert info["t0"] == 27.2
    assert info["t1"] == 27.9
    assert info["resume_t"] == 28.1


    # Во время lost платформа строго неподвижна (v=0.0)
    for tick in ticks:
        if tick.get("st") == "lost":
            assert float(tick.get("v", 0.0)) == 0.0


def test_readme_claims_no_batch_teams_and_valid_eval():
    """README не содержит несуществующий вызов batch teams, не заявляет 99.7 по 03 и команда eval валидна."""
    import re
    import shlex
    import subprocess

    from eval import build_parser

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "batch teams" not in readme
    assert "99.7" not in readme

    match = re.search(r"### Пакетный прогон по набору сидов:\s*```bash\s*\n([^\n]+)", readme)
    assert match, "Не найдена секция пакетного прогона в README.md"
    cmd_str = match.group(1).strip()

    parts = shlex.split(cmd_str)
    eval_idx = next((i for i, p in enumerate(parts) if "eval.py" in p), None)
    assert eval_idx is not None, f"Команда не вызывает eval.py: {cmd_str}"

    args_to_check = parts[eval_idx + 1 :]
    parser = build_parser()
    parsed_args = parser.parse_args(args_to_check)
    assert parsed_args.seeds is not None
    assert "1,2,3,7,11,21,42" in parsed_args.seeds

    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "eval.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--seeds" in res.stdout


def test_alternatives_does_not_attribute_stanley_cbf_to_controller():
    """ALTERNATIVES.md не приписывает Стэнли и CBF боевому пакету controller."""
    alternatives = (ROOT / "results" / "ALTERNATIVES.md").read_text(encoding="utf-8")
    assert "team_dreamteam_4_0/route/follower.py" not in alternatives
    assert "team_dreamteam_4_0/safety/clearance.py" not in alternatives
    assert "team_dreamteam_4_0/route/spline.py" not in alternatives
    assert "tests/test_route.py" in alternatives
    assert "tests/test_safety.py" in alternatives
    assert "compute_stanley_cmd" in alternatives
    assert "cbf_velocity_limit" in alternatives


def test_pedestrian_demo_claim_tick_hum_and_zero_v():
    """Утверждение демо о пешеходе проверяет такт с hum < 1.0 и v == 0."""
    moments = json.loads(
        (ROOT / "results" / "own_scenarios" / "moments.json").read_text(encoding="utf-8")
    )
    yard_moment = None
    log_path = None
    for section in moments["scenarios"]:
        if section["scenario"] == "04_busy_yard" and section["seed"] == 7:
            for m in section["moments"]:
                if m["key"] == "stop_person":
                    yard_moment = m
                    log_path = ROOT / section["log"]
                    break
    assert yard_moment is not None
    assert log_path is not None
    ticks = _ticks(str(log_path.relative_to(ROOT)))
    tick = nearest_tick(ticks, yard_moment["t"])
    assert float(tick.get("v", 1.0)) == 0.0
    assert float(tick.get("hum", 99.0)) < 1.0
    assert tick.get("st") == "waiting"
    assert "stop_person" in (tick.get("nt") or "")


def test_readme_scenario_and_seed_claims():
    """README точно указывает 6 пешеходов на 04_busy_yard, поддон s1 в 2 м от оси и seed 1 для lost."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "6 пешеходов" in readme
    assert "2 м от осевой линии" in readme or "2 м от оси" in readme
    assert "s4b_shadow_lane_lost" in readme
    assert "seed 1" in readme

    results_readme = (ROOT / "results" / "README.md").read_text(encoding="utf-8")
    assert "350 тестов" in results_readme
    assert "90 тестов Vitest" in results_readme

    arm_readme = (ROOT / "arm" / "README.md").read_text(encoding="utf-8")
    assert "90 автоматических тестов Vitest" in arm_readme


def test_s5_fog_moment_stop_person():
    """Момент s5_fog_inattentive фиксирует остановку перед пешеходом в тумане на t=87.4."""
    moments = json.loads(
        (ROOT / "results" / "own_scenarios" / "moments.json").read_text(encoding="utf-8")
    )
    s5_moments = None
    for section in moments["scenarios"]:
        if section["scenario"] == "s5_fog_inattentive" and section["seed"] == 7:
            s5_moments = section["moments"]
            break
    assert s5_moments is not None
    stop_moment = next((m for m in s5_moments if m["key"] == "stop_person"), None)
    assert stop_moment is not None
    assert stop_moment["t"] == 87.4
    assert stop_moment["status"] == "waiting"
    assert stop_moment["v"] == 0.0
    assert "stop_person" in stop_moment["note"]


def test_gnss_filtering_no_direct_pose_overwrite_and_smooth_blend():
    """Боевой GNSSFilter не переписывает координаты напрямую, а использует сглаживание k <= 0.15."""
    gnss_code = (ROOT / "team_dreamteam_4_0" / "localize" / "gnss.py").read_text(encoding="utf-8")
    assert "new_x = x + shift_x" not in gnss_code
    assert "new_y = y + shift_y" not in gnss_code
    assert "k = 0.15" in gnss_code or "0.15" in gnss_code

    pitch = (ROOT / "PITCH.md").read_text(encoding="utf-8")
    assert "0.15" in pitch
    assert "копирования фикса в pose_est" in pitch or "копирования фикса" in pitch

    approach = (ROOT / "APPROACH.md").read_text(encoding="utf-8")
    assert "0.15" in approach
    assert "прямого копирования в позу" in approach or "копирования сырого ГНСС" in approach


def test_alternatives_has_no_unsubstantiated_claims():
    """ALTERNATIVES.md не содержит неподтвержденных утверждений о субмиллиметрах, задержках и диапазонах."""
    alternatives = (ROOT / "results" / "ALTERNATIVES.md").read_text(encoding="utf-8")
    for banned in (
        "< 0.01",
        "субмиллиметр",
        "14.6",
        "+0.70",
        "0.70",
        "14-16",
        "130 мс",
        "около 1.3 мс",
        "не превышает лимит 100 мс",
        "1.3-3.9 мс",
    ):
        assert banned not in alternatives, f"Found unverified claim '{banned}' in ALTERNATIVES.md"
    assert "1.1-3.9 мс" in alternatives
    assert "205.4 мс" in alternatives
    # 0.25 м - порог отсечки инлайнеров, а не порог функции Хубера (0.08 м)
    assert "функцией потерь Хубера (порог 0.25" not in alternatives
    assert "функция потерь Хубера с порогом перехода" in alternatives
    assert "0.08" in alternatives






