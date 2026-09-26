"""Фасадный модуль Perception: интеграция фильтрации, кластеризации и отслеживания.

Строго соответствует схеме AMR-1.0 и требованиям изоляции (только stdlib и numpy).
"""

import math
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from .clustering import extract_clusters, group_unexplained_rays
from .filtering import check_map_discrepancies, filter_map_walls, filter_snow_artifacts
from .tracking import (
    Track,
    associate_and_update_tracks,
    classify_tracks,
    predict_unmatched_tracks,
    prune_tracks,
)

__all__ = ["Perception"]


class Perception:
    """Конвейер распознавания для навигации AMR.

    - выделяет динамические треки в чистом базисе одометрии (ox, oy, oth);
    - кластеризует необъясненные отклики лидара (> 0.35 + sigma_pose короче карты, > 0.4 м от стены карты);
    - фильтрация снега: одиночные изолированные лучи отбрасываются;
    - классифицирует треки: pedestrian, wall_extra, static_object, unknown;
    - сохраняет динамические треки при пропусках (до 1.0 с) с прогнозом скорости;
    - обнаруживает расхождения карты: map_missing (снесенные стены), map_extra (новые препятствия).
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
        """Только подтвержденные треки: два соседних детектирования, увиденные хотя бы раз."""
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
        """Обработать скан лидара и обновить треки препятствий и расхождения карты."""
        x, y, th = pose
        ox, oy, oth = odom_pose
        self._last_pose = (float(x), float(y), float(th))
        self._last_odom_pose = (float(ox), float(oy), float(oth))
        r = np.asarray(ranges, dtype=float)
        rel = np.asarray(rel_angles, dtype=float)
        n = len(r)

        if n == 0 or map_segs is None:
            return []

        # 1. Фильтрация откликов стен карты
        bad, exp, _ = filter_map_walls(
            ranges=r,
            rel_angles=rel,
            pose=pose,
            map_segs=map_segs,
            sigma_pose=sigma_pose,
            removed_segment_ids=self.removed_segment_ids,
        )

        # 2. Фильтрация артефактов снега
        bad = filter_snow_artifacts(r, rel, bad)

        # 3. Сборка кластеров лучей
        cluster_indices = group_unexplained_rays(r, rel, bad)

        # 4. Преобразование точек и геометрии кластеров
        detected_clusters, _ = extract_clusters(r, rel, cluster_indices, odom_pose)

        # 5. Ассоциация и обновление треков в базисе одометрии
        self.tracks, self._next_track_id, used_tracks = associate_and_update_tracks(
            tracks=self.tracks,
            detected_clusters=detected_clusters,
            next_track_id=self._next_track_id,
            dt=self.dt,
            is_fog=is_fog,
        )

        # 6. Экстраполяция несопоставленных динамических треков
        predict_unmatched_tracks(
            tracks=self.tracks,
            used_tracks=used_tracks,
            odom_pose=odom_pose,
            dt=self.dt,
        )

        # 7. Классификация треков и анализ истории
        classify_tracks(self.tracks, v_odom)

        # 8. Удаление устаревших треков
        self.tracks = prune_tracks(self.tracks)

        # 9. Проверка расхождений карты
        self._check_map_discrepancies(r, exp, x, y, th, map_segs, scan_inliers)

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
        """Обнаружить снесенные стены карты (map_missing) или подтвержденные лишние конструкции (map_extra)."""
        has_wall = any(tr.is_wall for tr in self.tracks)
        detected_note = check_map_discrepancies(
            ranges=ranges,
            exp_ranges=exp_ranges,
            x=x,
            y=y,
            th=th,
            map_segs=map_segs,
            scan_inliers=scan_inliers,
            removed_segment_ids=self.removed_segment_ids,
            missing_wall_votes=self._missing_wall_votes,
            has_wall_tracks=has_wall,
        )

        if detected_note is not None:
            self.note = detected_note
            self._note_hold = 20
        elif self._note_hold > 0:
            self._note_hold -= 1
            if self._note_hold == 0:
                self.note = ""

    def get_extra_obstacles(self) -> List[Tuple[float, float, float]]:
        """Вернуть неразмеченные и лишние препятствия для планировщика маршрута: список (x, y, radius)."""
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

            dx_o = tr.ox - ox
            dy_o = tr.oy - oy
            rx = cos_o * dx_o + sin_o * dy_o
            ry = -sin_o * dx_o + cos_o * dy_o
            wx = x + cos_w * rx - sin_w * ry
            wy = y + sin_w * rx + cos_w * ry
            r_eff = max(0.4, 0.5 * min(2.0, tr.length))
            obs.append((float(wx), float(wy), float(r_eff)))
        return obs
