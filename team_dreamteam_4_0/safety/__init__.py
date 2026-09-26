"""Пакет безопасности и ограничителя скорости.

Строго соответствует требованиям изоляции и безопасности
(только стандартная библиотека math/typing и numpy).
"""

from .clearance import (
    DECEL_NORMAL,
    DT,
    ESTOP_GAP,
    R_PEDESTRIAN,
    R_PLATFORM,
    SLOW_PERSON_GAP,
    SLOW_PERSON_MARGIN_K,
    SLOW_PERSON_MARGIN_MAX,
    SLOW_PERSON_MIN_PTS,
    SLOW_PERSON_V,
    STATIC_OBJECT_NEAR_GAP,
    STOP_GAP,
    STOP_PREDICT_MIN_SPEED,
    STOP_PREDICT_WITH_CANDIDATE,
    V_MAX_DEFAULT,
    calculate_clearance,
    predict_ttc_clearance,
)
from .governor import SafetyGovernor
from .status import determine_status

__all__ = [
    "R_PLATFORM",
    "R_PEDESTRIAN",
    "DECEL_NORMAL",
    "DT",
    "V_MAX_DEFAULT",
    "SLOW_PERSON_GAP",
    "SLOW_PERSON_V",
    "SLOW_PERSON_MARGIN_K",
    "SLOW_PERSON_MARGIN_MAX",
    "SLOW_PERSON_MIN_PTS",
    "STOP_PREDICT_WITH_CANDIDATE",
    "STOP_PREDICT_MIN_SPEED",
    "STOP_GAP",
    "STATIC_OBJECT_NEAR_GAP",
    "ESTOP_GAP",
    "calculate_clearance",
    "predict_ttc_clearance",
    "determine_status",
    "SafetyGovernor",
]
