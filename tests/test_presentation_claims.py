"""Утверждения колоды не расходятся с логами и не тащат чужой sha на речь."""

from __future__ import annotations

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

CURRENT = "b63ab91caa9194b0"
PACKET = "2f4a721eafcfb6ed"


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
        ("s5_fog_inattentive", 7, "fog_clear"),
        ("s5_fog_inattentive", 7, "stop_person"),
        ("s4b_shadow_lane_lost", 1, "lane_lost_status"),
        ("s3_wall_removed", 7, "map_missing"),
        ("s1_pallet_2m", 7, "offset"),
        ("s2_container_block", 7, "replan"),
    ):
        moment = by_key[key]
        assert ("%.1f" % float(moment["t"])) in pitch
    person = by_key[("s5_fog_inattentive", 7, "stop_person")]
    assert ("%.2f" % float(person["v"])).rstrip("0").rstrip(".") in pitch
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

