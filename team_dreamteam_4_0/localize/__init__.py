"""Пакет алгоритмов локализации AMR.

Включает:
- EKF фильтрацию и чистое счисление пути (ekf);
- сопоставление лидарных сканов со стенами и ориентирами (scan_matcher);
- комплексирование GNSS измерений (gnss);
- фасад Localizer со свойствами и методами калибровки.

Строго соответствует схеме AMR-1.0 и требованиям Т3/Т5.
"""

from .ekf import EKFFilter
from .gnss import GNSSFilter
from .localizer import Localizer
from .scan_matcher import (
    ScanMatcher,
    ScanMatchResult,
    apply_landmark_correction,
    penalise_missing_near_walls,
    recover_grid_search,
    scan_has_angle,
    scan_holds_landmark,
)

__all__ = [
    "Localizer",
    "ScanMatcher",
    "ScanMatchResult",
    "GNSSFilter",
    "EKFFilter",
    "scan_has_angle",
    "scan_holds_landmark",
    "apply_landmark_correction",
    "penalise_missing_near_walls",
    "recover_grid_search",
]
