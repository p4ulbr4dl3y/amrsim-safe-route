"""Подмодуль отслеживания препятствий: класс Track, фильтрация состояния, ассоциация и классификация.

Требования изоляции: только стандартная библиотека и numpy.
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

__all__ = [
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
    "KalmanFilter2D",
    "Track",
    "associate_and_update_tracks",
    "predict_unmatched_tracks",
    "classify_tracks",
    "prune_tracks",
]

# Пороги классификации треков.
PEDESTRIAN_SHIFT_M = 0.6
STATIC_SHIFT_M = 0.25
STATIC_OBJECT_V_GATE = 0.35
STATIC_HISTORY_TICKS = 15
FRONTAL_STATIC_HISTORY_TICKS = 20
FRONTAL_CORRIDOR_FWD_M = 5.0
FRONTAL_CORRIDOR_LAT_M = 1.6
COMPACT_CLUSTER_LENGTH_M = 1.0
PEDESTRIAN_CONTOUR_MAX_M = 1.2
PLATFORM_RADIUS_M = 0.9
PLATFORM_BODY_MARGIN_M = 0.05


def seen_has_pair(seen: List[int]) -> bool:
    """Истина, когда seen содержит два соседних попадания детектора (1, 1)."""
    for i in range(len(seen) - 1):
        if seen[i] == 1 and seen[i + 1] == 1:
            return True
    return False


def track_forward_lateral(tr: "Track") -> Tuple[float, float]:
    """Центроид трека в текущем базисе робота: (вперед, вбок), метры."""
    pts = tr.pts
    if pts is None or len(pts) == 0:
        return math.inf, math.inf
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def track_world_shift(tr: "Track") -> float:
    """Смещение трека в чистом базисе одометрии за окно его истории."""
    if len(tr.hist) < 2:
        return 0.0
    return math.hypot(tr.hist[-1][0] - tr.hist[0][0], tr.hist[-1][1] - tr.hist[0][1])


class KalmanFilter2D:
    """Фильтр Калмана постоянной скорости для слежения за объектом в плоскости одометрии."""

    def __init__(self, x: float = 0.0, y: float = 0.0, dt: float = 0.1):
        self.dt = float(dt)
        self.state = np.array([float(x), float(y), 0.0, 0.0], dtype=float)
        self.cov = np.diag([0.2**2, 0.2**2, 1.0**2, 1.0**2])
        self.F = np.array(
            [
                [1.0, 0.0, self.dt, 0.0],
                [0.0, 1.0, 0.0, self.dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        self.H = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
            ]
        )
        q_pos = 0.05
        q_vel = 0.2
        self.Q = np.diag([q_pos**2, q_pos**2, q_vel**2, q_vel**2])
        r_pos = 0.15
        self.R = np.diag([r_pos**2, r_pos**2])

    def predict(self) -> np.ndarray:
        """Экстраполяция состояния."""
        self.state = self.F @ self.state
        self.cov = self.F @ self.cov @ self.F.T + self.Q
        return self.state

    def update(self, z_x: float, z_y: float) -> np.ndarray:
        """Коррекция состояния по измеренной позиции."""
        z = np.array([float(z_x), float(z_y)])
        y = z - self.H @ self.state
        S = self.H @ self.cov @ self.H.T + self.R
        K = self.cov @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y
        eye4 = np.eye(4)
        self.cov = (eye4 - K @ self.H) @ self.cov
        return self.state


class Track:
    """Трек препятствия, поддерживаемый в чистых координатах одометрии (ox, oy, oth)."""

    __slots__ = (
        "track_id",
        "ox",
        "oy",
        "hist",
        "seen",
        "dyn",
        "class_label",
        "still_ticks",
        "vx_odom",
        "vy_odom",
        "pts",
        "length",
        "thickness",
        "coast_ticks",
        "confirmed",
    )

    def __init__(self, track_id: int, ox: float, oy: float, pts: Optional[np.ndarray] = None):
        self.track_id = track_id
        self.ox = float(ox)
        self.oy = float(oy)
        self.hist: List[Tuple[float, float]] = [(self.ox, self.oy)]
        self.seen: List[int] = [1]
        self.dyn: Optional[bool] = None
        self.class_label: str = "unknown"
        self.still_ticks: int = 0
        self.vx_odom: float = 0.0
        self.vy_odom: float = 0.0
        self.pts: np.ndarray = pts if pts is not None else np.empty((0, 2), dtype=float)
        self.length: float = 0.0
        self.thickness: float = 0.0
        self.coast_ticks: int = 0
        self.confirmed: bool = False

    def inside_platform_body(self) -> bool:
        """Истина, когда текущий контур находится внутри корпуса платформы."""
        pts = self.pts
        if pts is None or len(pts) == 0:
            return False
        return float(np.hypot(pts[:, 0], pts[:, 1]).min()) < (
            PLATFORM_RADIUS_M - PLATFORM_BODY_MARGIN_M
        )

    def refresh_confirmed(self) -> bool:
        """Зафиксировать подтверждение, когда seen содержит два соседних попадания."""
        if self.inside_platform_body():
            return self.confirmed
        if not self.confirmed and seen_has_pair(self.seen):
            self.confirmed = True
        return self.confirmed

    @property
    def is_pedestrian(self) -> bool:
        return self.class_label == "pedestrian" or self.dyn is True

    @property
    def is_wall(self) -> bool:
        return self.class_label == "wall_extra"

    @property
    def is_static_object(self) -> bool:
        return self.class_label == "static_object" or (
            self.dyn is False and self.class_label != "wall_extra"
        )

    @property
    def is_unknown(self) -> bool:
        return self.dyn is None and self.class_label == "unknown"


def associate_and_update_tracks(
    tracks: List[Track],
    detected_clusters: List[Dict[str, Any]],
    next_track_id: int,
    dt: float,
    is_fog: bool,
) -> Tuple[List[Track], int, Set[int]]:
    """Сопоставить детекции с треками и создать новые треки при отсутствии пары."""
    assoc_thresh = 1.5 if is_fog else 1.0
    used_tracks: Set[int] = set()

    for c_dict in detected_clusters:
        c_ox, c_oy = c_dict["ox"], c_dict["oy"]
        best_idx = None
        best_dist = assoc_thresh

        for t_idx, tr in enumerate(tracks):
            if t_idx in used_tracks:
                continue
            d = math.hypot(tr.ox - c_ox, tr.oy - c_oy)
            if d < best_dist:
                best_idx = t_idx
                best_dist = d

        if best_idx is not None:
            tr = tracks[best_idx]
            used_tracks.add(best_idx)

            dx = c_ox - tr.ox
            dy = c_oy - tr.oy
            inst_vx = dx / dt
            inst_vy = dy / dt
            tr.vx_odom = 0.6 * tr.vx_odom + 0.4 * inst_vx
            tr.vy_odom = 0.6 * tr.vy_odom + 0.4 * inst_vy

            tr.ox = c_ox
            tr.oy = c_oy
            tr.pts = c_dict["pts"]
            tr.length = c_dict["length"]
            tr.thickness = c_dict["thickness"]
            tr.hist.append((c_ox, c_oy))
            tr.seen.append(1)
            tr.coast_ticks = 0

            if (
                (c_dict["is_wall"] or c_dict["is_wall_piece"])
                and tr.dyn is not True
                and track_world_shift(tr) < PEDESTRIAN_SHIFT_M
            ):
                tr.class_label = "wall_extra"
                tr.dyn = False
        else:
            tr = Track(next_track_id, c_ox, c_oy, c_dict["pts"])
            next_track_id += 1
            tr.length = c_dict["length"]
            tr.thickness = c_dict["thickness"]

            if c_dict["is_wall"] or c_dict["is_wall_piece"]:
                tr.class_label = "wall_extra"
                tr.dyn = False
            else:
                if any(
                    other.is_pedestrian
                    and math.hypot(other.ox - c_ox, other.oy - c_oy) < assoc_thresh
                    for other in tracks
                ):
                    tr.dyn = True
                    tr.class_label = "pedestrian"

            tracks.append(tr)
            used_tracks.add(len(tracks) - 1)

    return tracks, next_track_id, used_tracks


def predict_unmatched_tracks(
    tracks: List[Track],
    used_tracks: Set[int],
    odom_pose: Tuple[float, float, float],
    dt: float,
) -> None:
    """Экстраполировать положение несопоставленных динамических треков."""
    ox, oy, oth = odom_pose
    cos_oth = math.cos(oth)
    sin_oth = math.sin(oth)

    for t_idx, tr in enumerate(tracks):
        if t_idx not in used_tracks:
            tr.seen.append(0)
            tr.coast_ticks += 1

            if tr.is_pedestrian and tr.coast_ticks <= 10:
                tr.ox += tr.vx_odom * dt
                tr.oy += tr.vy_odom * dt
                tr.hist.append((tr.ox, tr.oy))

                rel_ox = tr.ox - ox
                rel_oy = tr.oy - oy
                rx = cos_oth * rel_ox + sin_oth * rel_oy
                ry = -sin_oth * rel_ox + cos_oth * rel_oy
                tr.pts = np.array(
                    [
                        [rx - 0.15, ry],
                        [rx + 0.15, ry],
                        [rx, ry - 0.15],
                        [rx, ry + 0.15],
                    ]
                )
            else:
                tr.hist.append((tr.ox, tr.oy))
                rel_ox = tr.ox - ox
                rel_oy = tr.oy - oy
                rx = cos_oth * rel_ox + sin_oth * rel_oy
                ry = -sin_oth * rel_ox + cos_oth * rel_oy
                tr.pts = np.array([[rx, ry]])


def classify_tracks(tracks: List[Track], v_odom: float) -> None:
    """Классифицировать объекты по истории движения и геометрии контура."""
    slow_platform = abs(v_odom) < STATIC_OBJECT_V_GATE

    for tr in tracks:
        tr.hist = tr.hist[-11:]
        tr.seen = tr.seen[-11:]
        tr.refresh_confirmed()

        shift = 0.0
        if len(tr.hist) >= 5:
            shift = track_world_shift(tr)
            if shift >= PEDESTRIAN_SHIFT_M and tr.length <= PEDESTRIAN_CONTOUR_MAX_M:
                tr.class_label = "pedestrian"
                tr.dyn = True
                tr.still_ticks = 0
                continue

        if tr.is_wall:
            continue

        if tr.dyn is True:
            tr.class_label = "pedestrian"
            tr.still_ticks = 0
            continue

        if tr.length > PEDESTRIAN_CONTOUR_MAX_M:
            tr.class_label = "wall_extra"
            tr.dyn = False
            tr.still_ticks = 0
            continue

        if len(tr.hist) >= 5:
            stable = shift < STATIC_SHIFT_M
            if stable and slow_platform:
                tr.still_ticks += 1
            else:
                tr.still_ticks = 0

            if stable and slow_platform and tr.length <= COMPACT_CLUSTER_LENGTH_M:
                fwd, lat = track_forward_lateral(tr)
                in_corridor = (0.0 < fwd < FRONTAL_CORRIDOR_FWD_M) and (
                    abs(lat) < FRONTAL_CORRIDOR_LAT_M
                )
                required_ticks = (
                    FRONTAL_STATIC_HISTORY_TICKS if in_corridor else STATIC_HISTORY_TICKS
                )
                if tr.still_ticks >= required_ticks:
                    tr.class_label = "static_object"
                    tr.dyn = False

        if tr.dyn is None:
            tr.class_label = "unknown"


def prune_tracks(tracks: List[Track]) -> List[Track]:
    """Удалить устаревшие треки."""
    return [
        tr
        for tr in tracks
        if (sum(tr.seen[-6:]) > 0) or (tr.is_pedestrian and tr.coast_ticks <= 10)
    ]
