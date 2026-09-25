"""Perception module: unexplained lidar clustering, odometry tracking, classification, map discrepancies.

Strictly conforms to plan/03-vospriyatie-i-bezopasnost.md and isolation requirements
(standard library math/typing and numpy only).
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

try:
    from .geom import raycast, seg_dist, wrap_angle
except ImportError:
    from geom import raycast, seg_dist, wrap_angle


# Пороги классификации треков.
# Трек со смещением >= 0.6 м за окно ~1 с считается человеком навсегда.
# При меньшем смещении за полное окно трек не имеет глобального движения.
PEDESTRIAN_SHIFT_M = 0.6
# Ниже этого смещения за окно трек считается неподвижным в мире
STATIC_SHIFT_M = 0.25
# Фиксация объекта только при медленном движении платформы или остановке:
# порог 0.35 м/с сохраняет работу при скорости 0.22 м/с.
STATIC_OBJECT_V_GATE = 0.35
# Окно истории 1.5 с при dt = 0.1 с для фиксации неподвижного кластера как объекта:
# снег не повторяется в одной точке, объекту требуется стабильный трек.
STATIC_HISTORY_TICKS = 15
# Кластер перед платформой внутри коридора считается человеком,
# пока не пробудет стабильным в мире >= 2.0 с.
FRONTAL_STATIC_HISTORY_TICKS = 20
FRONTAL_CORRIDOR_FWD_M = 5.0
FRONTAL_CORRIDOR_LAT_M = 1.6
# Компактный кластер: коробка или палета, не стена и не длинный забор
COMPACT_CLUSTER_LENGTH_M = 1.0
# Верхняя граница контура пешехода. След человека имеет длину 0.3-0.6 м,
# поэтому более длинный кластер не может быть человеком. Крупное статическое тело
# смещает центроид при изменении видимой части контура, оставаясь на месте.
# Фиксация человека применяется только к компактным контурам.
PEDESTRIAN_CONTOUR_MAX_M = 1.2
# Радиус корпуса платформы (м). Кандидат ближе R_PLATFORM - 0.05
# находится внутри корпуса и является фантомным откликом.
PLATFORM_RADIUS_M = 0.9
PLATFORM_BODY_MARGIN_M = 0.05


def seen_has_pair(seen: List[int]) -> bool:
    """True when `seen` contains two adjacent detection hits (1, 1).

    A track confirmed by an adjacent pair stays confirmed forever (coasting through
    fog must not drop an already validated person back to unknown, plan/03:20).
    """
    for i in range(len(seen) - 1):
        if seen[i] == 1 and seen[i + 1] == 1:
            return True
    return False


def track_forward_lateral(tr: "Track") -> Tuple[float, float]:
    """Centroid of a track in the current robot frame: (forward, lateral) metres.

    ``Track.pts`` already lives in the robot frame (relative to the pure odometry
    pose of the last step). An empty footprint is reported as (inf, inf) so it is
    never mistaken for a cluster inside the swept corridor.
    """
    pts = tr.pts
    if pts is None or len(pts) == 0:
        return math.inf, math.inf
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def track_world_shift(tr: "Track") -> float:
    """Displacement of a track in the pure odometry frame over its history window."""
    if len(tr.hist) < 2:
        return 0.0
    return math.hypot(tr.hist[-1][0] - tr.hist[0][0], tr.hist[-1][1] - tr.hist[0][1])


class Track:
    """Obstacle track maintained in pure odometry coordinates (ox, oy, oth).

    Tracking in pure odometry prevents artificial position jumps caused by
    GNSS corrections or scan-matching pose updates.
    """

    __slots__ = (
        "track_id",
        "ox",
        "oy",  # Центроид в чистом базисе одометрии (м)
        "hist",  # История координат (ox, oy)
        "seen",  # История попаданий (1) и пропусков (0) детектора
        "dyn",  # True (пешеход), False (статический объект или стена), None (неизвестно)
        "class_label",  # Классы: pedestrian, wall_extra, static_object, unknown
        "still_ticks",  # Число тактов без движения при стоящем роботе
        "vx_odom",
        "vy_odom",  # Оценка скорости в базисе одометрии (м/с)
        "pts",  # Текущие точки в базисе робота (N, 2)
        "length",  # Длина кластера вдоль главной оси (м)
        "thickness",  # Толщина кластера по 80-му перцентилю (м)
        "coast_ticks",  # Число тактов с последнего обнаружения сенсором
        "confirmed",  # Флаг фиксации: два последовательных детектирования хотя бы один раз
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
        """True when the current footprint sits inside the platform hull.

        A return closer than ``R_PLATFORM - 0.05`` m is physically impossible without a
        reported contact: it is a phantom (a stray snowflake or a lidar artifact), so
        its points are discarded from the active obstacle set (plan/03:18).
        """
        pts = self.pts
        if pts is None or len(pts) == 0:
            return False
        return float(np.hypot(pts[:, 0], pts[:, 1]).min()) < (
            PLATFORM_RADIUS_M - PLATFORM_BODY_MARGIN_M
        )

    def refresh_confirmed(self) -> bool:
        """Latch confirmation once `seen` holds two adjacent hits; never unset it.

        A cluster whose points currently lie inside the platform body cannot confirm:
        that is the close-phantom safeguard (plan/03:18). Discarding the points here,
        rather than at cluster assembly, keeps the segmentation of real returns -- and
        therefore track association -- untouched. A track that is already confirmed
        never loses the flag, so a real body at contact still brakes.
        """
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


def fit_cluster_geometry(pts: np.ndarray) -> Tuple[float, float]:
    """Calculate length and 80th-percentile thickness using PCA (SVD).

    pts: (N, 2) array of 2D points in Cartesian plane.
    Returns:
      (length, thickness) in meters.
    """
    if len(pts) < 2:
        return 0.0, 0.0
    if len(pts) == 2:
        length = float(np.hypot(pts[1, 0] - pts[0, 0], pts[1, 1] - pts[0, 1]))
        return length, 0.0

    c = pts.mean(axis=0)
    centered = pts - c
    try:
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        along = centered @ vt[0]
        across = centered @ vt[1]
        length = float(along.max() - along.min())
        thickness = float(np.percentile(np.abs(across), 80))
        return length, thickness
    except Exception:
        length = float(np.ptp(pts[:, 0]) + np.ptp(pts[:, 1]))
        return length, 0.0


def is_wall_cluster(pts: np.ndarray) -> bool:
    """Determine if cluster geometry represents an unmapped wall or fence.

    Criterion: length > 1.0 m and 80th-percentile thickness < 0.1 m.
    """
    if len(pts) < 3:
        return False
    length, thickness = fit_cluster_geometry(pts)
    return length > 1.0 and thickness < 0.10


def is_wall_continuation(pts: np.ndarray, wall_point_clouds: List[np.ndarray]) -> bool:
    """Determine if a short cluster continues an unmapped wall.

    Criterion: cluster is closer than 0.6 m to a known wall cluster and its
    80th-percentile lateral deviation from the wall principal axis is < 0.15 m.
    """
    if len(pts) == 0 or not wall_point_clouds:
        return False

    for w_pts in wall_point_clouds:
        if len(w_pts) < 3:
            continue
        # Расстояние между точками кластера и точками стены
        dists = np.hypot(pts[:, None, 0] - w_pts[None, :, 0], pts[:, None, 1] - w_pts[None, :, 1])
        if float(dists.min()) > 0.6:
            continue

        c = w_pts.mean(axis=0)
        try:
            _, _, vt = np.linalg.svd(w_pts - c, full_matrices=False)
            proj_across = (pts - c) @ vt[1]
            if float(np.percentile(np.abs(proj_across), 80)) < 0.15:
                return True
        except Exception:
            continue

    return False


class Perception:
    """Perception pipeline for AMR navigation.

    - Isolates dynamic tracks into pure odometry frame (ox, oy, oth).
    - Clusters unexplained lidar returns (> 0.35 + sigma_pose shorter than map, > 0.4m from map wall).
    - Snow filtering: isolated single beams rejected.
    - Classifies tracks: pedestrian, wall_extra, static_object, unknown.
    - Preserves dynamic tracks across dropouts (up to 1.0s) with velocity prediction.
    - Detects map discrepancies: map_missing (sensed demolished walls), map_extra (new obstacles).
    """

    def __init__(self, dt: float = 0.1):
        self.dt = float(dt)
        self.tracks: List[Track] = []
        self._next_track_id: int = 1

        # Отслеживание расхождений карты
        self.removed_segment_ids: Set[int] = set()
        self._missing_wall_votes: Dict[int, int] = {}
        self.note: str = ""
        # Число тактов действия примечания карты без повторного подтверждения
        self._note_hold: int = 0
        # Последняя пара поз для перевода треков одометрии в глобальные координаты
        self._last_pose: Optional[Tuple[float, float, float]] = None
        self._last_odom_pose: Optional[Tuple[float, float, float]] = None

    @property
    def active_tracks(self) -> List[Track]:
        """Confirmed tracks only: two adjacent detections seen at least once.

        A lone or paired snow return never repeats in one world point from tick to
        tick (plan/03:18), so it can never confirm; a confirmed track stays
        confirmed while it coasts through fog (plan/03:20). Safety and the route
        obstacle layer must consume this list, ``tracks`` stays the full set used
        for association and coasting.
        """
        active: List[Track] = []
        for tr in self.tracks:
            if tr.refresh_confirmed():
                active.append(tr)
        return active

    def step(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        pose: Tuple[float, float, float],
        odom_pose: Tuple[float, float, float],
        map_segs: np.ndarray,
        sigma_pose: float = 0.0,
        is_fog: bool = False,
        v_odom: float = 0.0,
        scan_inliers: int = 0,
    ) -> List[Track]:
        """Process lidar scan and update obstacle tracks and map discrepancies.

        Args:
          ranges: 1D array of lidar ranges (360 beams, 1 deg step)
          rel_angles: 1D array of beam angles in robot frame (rad)
          pose: estimated world pose (x, y, th)
          odom_pose: pure odometry pose (ox, oy, oth)
          map_segs: (M, 4) line segments of mapped buildings
          sigma_pose: current localizer pose uncertainty (m)
          is_fog: whether fog condition is active
          v_odom: current forward velocity from odometry (m/s)
          scan_inliers: number of scan-matching inliers from localizer

        Returns:
          Active confirmed tracks.
        """
        x, y, th = pose
        ox, oy, oth = odom_pose
        self._last_pose = (float(x), float(y), float(th))
        self._last_odom_pose = (float(ox), float(oy), float(oth))
        r = np.asarray(ranges, dtype=float)
        rel = np.asarray(rel_angles, dtype=float)
        n = len(r)

        if n == 0 or map_segs is None:
            return []

        # 1. Ожидаемые расстояния до стен карты
        # Фильтрация активных отрезков (исключая удаленные)
        active_segs = map_segs
        if self.removed_segment_ids:
            mask = np.ones(len(map_segs), dtype=bool)
            for sid in self.removed_segment_ids:
                if 0 <= sid < len(map_segs):
                    mask[sid] = False
            active_segs = map_segs[mask]

        exp = raycast(x, y, th + rel, active_segs)

        # 2. Кандидаты в необъясненные лучи: короче карты с запасом
        margin = 0.35 + min(1.5, max(0.0, sigma_pose))
        bad = np.isfinite(r) & (r < exp - margin)

        # Исключение лучей, чьи концы попадают в пределы 0.4 м от стены карты
        if bad.any():
            bad_idx = np.flatnonzero(bad)
            beam_world_angles = th + rel[bad_idx]
            wx = x + r[bad_idx] * np.cos(beam_world_angles)
            wy = y + r[bad_idx] * np.sin(beam_world_angles)
            wall_margin = max(0.85, 0.4 + min(1.5, 2.0 * sigma_pose))
            near_wall = seg_dist(wx, wy, active_segs) < wall_margin
            bad[bad_idx[near_wall]] = False

        # 3. Фильтр снега: изолированные одиночные короткие отклики (0.3-3.0 м) отбрасываются
        if bad.any():
            bad_idx = np.flatnonzero(bad)
            # Проверка декартова расстояния до ближайших соседей по углу
            cos_rel = np.cos(rel)
            sin_rel = np.sin(rel)
            px_all = r * cos_rel
            py_all = r * sin_rel

            for k in bad_idx:
                prev_k = (k - 1) % n
                next_k = (k + 1) % n
                has_prev = bad[prev_k] and (
                    math.hypot(px_all[k] - px_all[prev_k], py_all[k] - py_all[prev_k]) < 0.6
                )
                has_next = bad[next_k] and (
                    math.hypot(px_all[k] - px_all[next_k], py_all[k] - py_all[next_k]) < 0.6
                )
                if not (has_prev or has_next):
                    # Одиночный луч: артефакт снегопада
                    bad[k] = False

        # 4. Сборка кластеров
        finite = np.isfinite(r)
        breaks = finite & ~bad  # Луч, объясненный стеной карты, завершает текущий объект
        clusters: List[List[int]] = []

        if bad.any():
            start = (
                int(np.argmax(breaks))
                if breaks.any()
                else int(np.argmax(~finite))
                if (~finite).any()
                else 0
            )
            run: List[int] = []
            skipped = 0

            for j in range(1, n + 1):
                k = (start + j) % n
                if bad[k]:
                    if not run:
                        run.append(k)
                        skipped = 0
                        continue
                    # Проверка разрыва в декартовой плоскости
                    gap = math.hypot(
                        r[k] * math.cos(rel[k]) - r[run[-1]] * math.cos(rel[run[-1]]),
                        r[k] * math.sin(rel[k]) - r[run[-1]] * math.sin(rel[run[-1]]),
                    )
                    if gap < 0.6:
                        run.append(k)
                        skipped = 0
                        continue

                # До 2 пропущенных лучей не разрывают кластер для устойчивости в тумане
                if run and skipped < 2:
                    nxt = [(start + j + d) % n for d in (1, 2)]
                    # Проверка возобновления кластера следующим лучом в пределах 0.6 м
                    can_resume = not finite[k] or any(
                        bad[q]
                        and (
                            math.hypot(
                                r[q] * math.cos(rel[q]) - r[run[-1]] * math.cos(rel[run[-1]]),
                                r[q] * math.sin(rel[q]) - r[run[-1]] * math.sin(rel[run[-1]]),
                            )
                            < 0.6
                        )
                        for q in nxt
                    )
                    if can_resume:
                        skipped += 1
                        continue

                if len(run) >= 2:
                    clusters.append(run)
                run = [k] if bad[k] else []
                skipped = 0

            if len(run) >= 2:
                clusters.append(run)

        # 5. Извлечение точек кластеров и перевод центроидов в чистый базис одометрии
        cos_oth = math.cos(oth)
        sin_oth = math.sin(oth)
        cos_rel = np.cos(rel)
        sin_rel = np.sin(rel)

        detected_clusters: List[Dict[str, Any]] = []
        confirmed_wall_pts: List[np.ndarray] = []

        for run_indices in clusters:
            idx = np.array(run_indices)
            px = r[idx] * cos_rel[idx]
            py = r[idx] * sin_rel[idx]
            pts = np.column_stack([px, py])

            mean_px = float(px.mean())
            mean_py = float(py.mean())

            # Перевод центроида в чистый базис одометрии (ox, oy, oth)
            cluster_ox = ox + cos_oth * mean_px - sin_oth * mean_py
            cluster_oy = oy + sin_oth * mean_px + cos_oth * mean_py

            length, thickness = fit_cluster_geometry(pts)
            is_wall = length > 1.0 and thickness < 0.10
            if is_wall:
                confirmed_wall_pts.append(pts)

            detected_clusters.append(
                {
                    "pts": pts,
                    "ox": cluster_ox,
                    "oy": cluster_oy,
                    "length": length,
                    "thickness": thickness,
                    "is_wall": is_wall,
                }
            )

        # Второй проход: проверка продолжений стен
        for c_dict in detected_clusters:
            if not c_dict["is_wall"]:
                if is_wall_continuation(c_dict["pts"], confirmed_wall_pts):
                    c_dict["is_wall_piece"] = True
                else:
                    c_dict["is_wall_piece"] = False
            else:
                c_dict["is_wall_piece"] = False

        # 6. Ассоциация детекций с существующими треками в чистом базисе одометрии
        assoc_thresh = 1.5 if is_fog else 1.0
        used_tracks: Set[int] = set()
        matched_cluster_indices: Set[int] = set()

        for c_idx, c_dict in enumerate(detected_clusters):
            c_ox, c_oy = c_dict["ox"], c_dict["oy"]
            best_idx = None
            best_dist = assoc_thresh

            for t_idx, tr in enumerate(self.tracks):
                if t_idx in used_tracks:
                    continue
                d = math.hypot(tr.ox - c_ox, tr.oy - c_oy)
                if d < best_dist:
                    best_idx = t_idx
                    best_dist = d

            if best_idx is not None:
                tr = self.tracks[best_idx]
                used_tracks.add(best_idx)
                matched_cluster_indices.add(c_idx)

                # Обновление оценки скорости в базисе одометрии
                dx = c_ox - tr.ox
                dy = c_oy - tr.oy
                inst_vx = dx / self.dt
                inst_vy = dy / self.dt
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

                # Классификация геометрии. Трек с историей движения человека никогда не понижается
                # до стены: стена неподвижна в одометрии, а силуэт человека может временно казаться тонким.
                if (
                    (c_dict["is_wall"] or c_dict["is_wall_piece"])
                    and tr.dyn is not True
                    and track_world_shift(tr) < PEDESTRIAN_SHIFT_M
                ):
                    tr.class_label = "wall_extra"
                    tr.dyn = False
            else:
                # Новый трек
                tr = Track(self._next_track_id, c_ox, c_oy, c_dict["pts"])
                self._next_track_id += 1
                tr.length = c_dict["length"]
                tr.thickness = c_dict["thickness"]

                if c_dict["is_wall"] or c_dict["is_wall_piece"]:
                    tr.class_label = "wall_extra"
                    tr.dyn = False
                else:
                    # Наследование класса пешехода при соседстве с известным динамическим треком
                    if any(
                        other.is_pedestrian
                        and math.hypot(other.ox - c_ox, other.oy - c_oy) < assoc_thresh
                        for other in self.tracks
                    ):
                        tr.dyn = True
                        tr.class_label = "pedestrian"

                self.tracks.append(tr)
                used_tracks.add(len(self.tracks) - 1)
                matched_cluster_indices.add(c_idx)

        # 7. Несопоставленные треки: экстраполяция движения для динамических треков
        slow_platform = abs(v_odom) < STATIC_OBJECT_V_GATE
        for t_idx, tr in enumerate(self.tracks):
            if t_idx not in used_tracks:
                tr.seen.append(0)
                tr.coast_ticks += 1

                # Если трек был пешеходом и потерян менее 1.0 с назад (10 тактов), прогнозировать движение
                if tr.is_pedestrian and tr.coast_ticks <= 10:
                    tr.ox += tr.vx_odom * self.dt
                    tr.oy += tr.vy_odom * self.dt
                    tr.hist.append((tr.ox, tr.oy))

                    # Прогноз точек в базисе робота
                    rel_ox = tr.ox - ox
                    rel_oy = tr.oy - oy
                    rx = cos_oth * rel_ox + sin_oth * rel_oy
                    ry = -sin_oth * rel_ox + cos_oth * rel_oy
                    # Синтез примерного контура кластера вокруг прогнозируемой позиции
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

        # 8. Классификация треков и анализ истории:
        # - трек со смещением >= 0.6 м за ~1 с навсегда остается пешеходом;
        # - компактный стабильный кластер без движения становится статическим объектом;
        # - кластер перед платформой в коридоре остается человеком до стабильности >= 2.0 с.
        for tr in self.tracks:
            tr.hist = tr.hist[-11:]
            tr.seen = tr.seen[-11:]
            tr.refresh_confirmed()

            # Движение в мире важнее геометрической метки: реальная стена неподвижна в базисе одометрии,
            # смещение >= 0.6 м указывает на человека. Правило ограничено компактными контурами.
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

            # Зафиксированный пешеход: сохраняет класс человека и не становится препятствием карты.
            # Правило приоритетнее длинных кластеров при частичной видимости.
            if tr.dyn is True:
                tr.class_label = "pedestrian"
                tr.still_ticks = 0
                continue

            # Длинный кластер, отсутствующий на карте, является физическим объектом (wall_extra),
            # а не человеком. Это позволяет планировщику построить объезд и избежать тупика.
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

        # 9. Удаление устаревших треков.
        # Трек сохраняется при недавнем наблюдении или экстраполяции пешехода <= 10 тактов.
        self.tracks = [
            tr
            for tr in self.tracks
            if (sum(tr.seen[-6:]) > 0) or (tr.is_pedestrian and tr.coast_ticks <= 10)
        ]

        # 10. Проверка расхождений карты: отсутствующие и лишние стены
        self._check_map_discrepancies(r, exp, x, y, th, map_segs, scan_inliers)

        # Возврат только подтвержденных треков: снежные отклики отсекаются,
        # а подтвержденный трек сохраняется при экстраполяции.
        return self.active_tracks

    def _check_map_discrepancies(
        self,
        ranges: np.ndarray,
        exp_ranges: np.ndarray,
        x: float,
        y: float,
        th: float,
        map_segs: np.ndarray,
        scan_inliers: int,
    ) -> None:
        """Detect demolished mapped walls (map_missing) or confirmed extra structures (map_extra)."""
        if len(map_segs) == 0:
            return

        detected_note: Optional[str] = None

        # Обнаруженные отсутствующие стены: конечные лучи длиннее карты более чем на 1.2 м
        if scan_inliers >= 40:
            overshoot = (
                (exp_ranges < 15.0)
                & np.isfinite(ranges)
                & (ranges < 19.5)
                & (ranges > exp_ranges + 1.2)
            )
            if overshoot.any():
                over_indices = np.flatnonzero(overshoot)
                # Подсчет числа лучей, пересекающих каждый отрезок в текущем такте
                tick_votes: Dict[int, int] = {}
                for idx in over_indices:
                    for s_idx, seg in enumerate(map_segs):
                        if s_idx in self.removed_segment_ids:
                            continue
                        ang = wrap_angle(th + np.radians(float(idx)))
                        r_s = raycast(x, y, np.array([ang]), seg[None, :])
                        if np.isfinite(r_s[0]) and abs(r_s[0] - exp_ranges[idx]) < 0.25:
                            tick_votes[s_idx] = tick_votes.get(s_idx, 0) + 1

                for s_idx, count in tick_votes.items():
                    # Не менее 5 одновременных пересекающих лучей для фиксации события
                    if count >= 5:
                        self._missing_wall_votes[s_idx] = self._missing_wall_votes.get(s_idx, 0) + 1
                        if self._missing_wall_votes[s_idx] >= 20:
                            self.removed_segment_ids.add(s_idx)
                            detected_note = "map_missing"

        # Проверка подтвержденных лишних стен
        if detected_note is None and any(tr.is_wall for tr in self.tracks):
            detected_note = "map_extra"

        # Заметки перепроверяются каждый такт и сбрасываются при исчезновении причины,
        # не перекрывая активные уведомления маршрута.
        if detected_note is not None:
            self.note = detected_note
            self._note_hold = 20
        elif self._note_hold > 0:
            self._note_hold -= 1
            if self._note_hold == 0:
                self.note = ""

    def get_extra_obstacles(self) -> List[Tuple[float, float, float]]:
        """Return unmapped/extra obstacles for the route planner: list of (x, y, radius).

        Tracks are maintained in the pure odometry frame; they are transformed back
        into world coordinates using the pose pair of the most recent step().
        Only confirmed tracks are exported: an unconfirmed phantom wall must not
        rewrite the route (frozen wave-3 interface).
        """
        obs: List[Tuple[float, float, float]] = []
        if self._last_pose is None or self._last_odom_pose is None:
            return obs

        x, y, th = self._last_pose
        ox, oy, oth = self._last_odom_pose
        cos_o, sin_o = math.cos(oth), math.sin(oth)
        cos_w, sin_w = math.cos(th), math.sin(th)

        for tr in self.tracks:
            if not (tr.is_wall or tr.is_static_object):
                continue
            if not tr.refresh_confirmed():
                continue
            # Перевод координат: одометрия -> робот -> глобальный мир
            dx_o = tr.ox - ox
            dy_o = tr.oy - oy
            rx = cos_o * dx_o + sin_o * dy_o
            ry = -sin_o * dx_o + cos_o * dy_o
            wx = x + cos_w * rx - sin_w * ry
            wy = y + sin_w * rx + cos_w * ry
            # Оценка радиуса по длине кластера с ограничениями
            r_eff = max(0.4, 0.5 * min(2.0, tr.length))
            obs.append((float(wx), float(wy), float(r_eff)))
        return obs
