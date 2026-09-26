"""Пакет perceive: конвейер распознавания, фильтрация, кластеризация и отслеживание объектов.

Обеспечивает 100% обратную совместимость с экспортом прежнего модуля perceive.py.
"""

from .clustering import (
    euclidean_cluster_points,
    extract_clusters,
    fit_cluster_geometry,
    group_unexplained_rays,
    is_wall_cluster,
    is_wall_continuation,
)
from .filtering import (
    check_map_discrepancies,
    filter_map_walls,
    filter_snow_artifacts,
    preprocess_scan,
)
from .perception import Perception
from .tracking import (
    COMPACT_CLUSTER_LENGTH_M,
    FRONTAL_CORRIDOR_FWD_M,
    FRONTAL_CORRIDOR_LAT_M,
    FRONTAL_STATIC_HISTORY_TICKS,
    PEDESTRIAN_CONTOUR_MAX_M,
    PEDESTRIAN_SHIFT_M,
    PLATFORM_BODY_MARGIN_M,
    PLATFORM_RADIUS_M,
    STATIC_HISTORY_TICKS,
    STATIC_OBJECT_V_GATE,
    STATIC_SHIFT_M,
    KalmanFilter2D,
    Track,
    associate_and_update_tracks,
    classify_tracks,
    predict_unmatched_tracks,
    prune_tracks,
    seen_has_pair,
    track_forward_lateral,
    track_world_shift,
)

__all__ = [
    "Perception",
    "Track",
    "KalmanFilter2D",
    "PEDESTRIAN_SHIFT_M",
    "STATIC_SHIFT_M",
    "STATIC_OBJECT_V_GATE",
    "STATIC_HISTORY_TICKS",
    "FRONTAL_STATIC_HISTORY_TICKS",
    "FRONTAL_CORRIDOR_FWD_M",
    "FRONTAL_CORRIDOR_LAT_M",
    "COMPACT_CLUSTER_LENGTH_M",
    "PEDESTRIAN_CONTOUR_MAX_M",
    "PLATFORM_RADIUS_M",
    "PLATFORM_BODY_MARGIN_M",
    "seen_has_pair",
    "track_forward_lateral",
    "track_world_shift",
    "fit_cluster_geometry",
    "is_wall_cluster",
    "is_wall_continuation",
    "group_unexplained_rays",
    "extract_clusters",
    "euclidean_cluster_points",
    "filter_map_walls",
    "filter_snow_artifacts",
    "preprocess_scan",
    "check_map_discrepancies",
    "associate_and_update_tracks",
    "predict_unmatched_tracks",
    "classify_tracks",
    "prune_tracks",
]
