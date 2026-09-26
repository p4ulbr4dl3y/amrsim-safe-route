"""Класс SafetyGovernor - арбитр безопасности и скорости платформы."""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from ..geom import inside_polygon
except (ImportError, ValueError):
    from geom import inside_polygon
try:
    from ..perceive import Track
except (ImportError, ValueError):
    from perceive import Track
from .clearance import (
    DECEL_NORMAL,
    DT,
    ESTOP_GAP,
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
from .status import determine_status


class SafetyGovernor:
    """Модуль безопасности, обеспечивающий зазор, ограничения скорости, торможение в коридоре и примечания.

    Ограничивает скорость согласно правилам безопасности:
    1. прогнозируемый зазор до пешехода/неизвестного объекта за 2 с < 0.8 м -> v = 0;
    2. текущий зазор до пешехода/неизвестного объекта < 0.8 м -> v = 0, удерживается, пока
       прогнозируемый зазор не превысит 3.3 м;
    3. текущий зазор до человекоподобного пешехода/неизвестного объекта < 3.3 м плюс упреждающий
       запас ограничивает v значением <= 0.22 м/с;
    4. три соседних отклика лидара в коридоре |y| < 1.0 м внутри тормозного пути -> v = 0;
    5. неразмеченная стена (is_wall/map_extra) и статический объект в коридоре учитываются как
       препятствие в зазоре и в проверке коридора;
    6. туман + кластер впереди < 5.0 м -> v <= 0.35, туман и чисто -> v <= 0.90;
    7. потеря позы (is_lost) -> v = 0, статус становится 'lost' только после остановки платформы;
    8. estop (2.5 м/с^2) только когда подтвержденный кластер ближе 1.2 м и штатное торможение 1.2 м/с^2
       не успевает остановиться.
    """

    NOTE_ORDER = (
        "blocked_wheels",
        "stop_person",
        "stop_object",
        "stop_corridor",
        "slow_person",
        "lost",
        "map",
        "fog",
        "zone",
        "dock",
    )

    def __init__(self, v_top: float = V_MAX_DEFAULT, dt: float = DT):
        self.v_top = float(v_top)
        self.dt = float(dt)

        self._person_hold: bool = False
        self._person_note: str = ""
        self._last_human_pred: float = math.inf
        self._lost_human_ticks: int = 0
        self._prev_min_cl: Optional[float] = None

    def get_zone_limit(
        self,
        x: float,
        y: float,
        zones: List[Tuple[Any, float]],
    ) -> float:
        """Найти минимальное применимое ограничение скорости зоны в точке (x, y) с запасом 0.05 м/с."""
        lim = self.v_top
        for poly, v_max in zones:
            if inside_polygon(x, y, poly):
                lim = min(lim, v_max - 0.05)
        return max(0.1, lim)

    def _compose_note(self, notes: Dict[str, str]) -> str:
        """Объединить активные причины в одну стабильную строку <= 200 символов без мерцания."""
        parts = [notes[k] for k in self.NOTE_ORDER if k in notes]
        if not parts:
            return ""
        return " ".join(parts)[:200]

    def evaluate(
        self,
        v_cand: float,
        w_cand: float,
        v_odom: float,
        w_odom: float,
        pose: Tuple[float, float, float],
        odom_pose: Tuple[float, float, float],
        tracks: List[Track],
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        zones: List[Tuple[Any, float]],
        is_fog: bool = False,
        is_arrived: bool = False,
        is_lost: bool = False,
        blocked_wheels: bool = False,
        perception_note: str = "",
        remaining_dist: float = 99.0,
        sigma_cross: float = 0.0,
    ) -> Tuple[float, float, str, str]:
        """Оценить ограничения безопасности и определить безопасную команду (v, w), статус и примечание."""
        x, y, th = pose
        _, _, oth = odom_pose
        v_now = abs(v_odom)

        v_lim = self.v_top
        stop_reason: Optional[str] = None
        notes: Dict[str, str] = {}
        is_estop: bool = False

        if perception_note:
            notes["map"] = perception_note

        if blocked_wheels:
            stop_reason = "blocked_wheels"
            notes["blocked_wheels"] = "blocked_wheels"
            v_lim = 0.0

        cos_th = math.cos(th)
        sin_th = math.sin(th)
        zone_curr = self.get_zone_limit(x, y, zones)
        zone_ahead = self.get_zone_limit(x + 3.0 * cos_th, y + 3.0 * sin_th, zones)
        zone_effective = min(zone_curr, zone_ahead)
        v_lim = min(v_lim, zone_effective)
        if zone_effective < self.v_top:
            notes["zone"] = f"zone v={zone_effective:.2f}"

        if is_fog:
            has_cluster_ahead = False
            for tr in tracks:
                if tr.pts is not None and len(tr.pts) > 0:
                    pts = tr.pts
                    in_front = (pts[:, 0] > 0.0) & (pts[:, 0] < 5.0) & (np.abs(pts[:, 1]) < 2.0)
                    if in_front.any():
                        has_cluster_ahead = True
                        break

            if has_cluster_ahead:
                v_lim = min(v_lim, 0.35)
                notes["fog"] = "fog_cluster"
            else:
                v_lim = min(v_lim, 0.90)
                notes["fog"] = "fog_clear"

        d_stop_corridor = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + 0.6

        min_overall_clearance = math.inf
        human_pred_min = math.inf
        person_stop = False
        person_slow = False
        person_slow_cl = math.inf
        min_point_dist = math.inf

        for tr in tracks:
            pts = tr.pts
            if pts is None or len(pts) == 0:
                continue

            d_pts = float(np.hypot(pts[:, 0], pts[:, 1]).min())
            if d_pts < min_point_dist:
                min_point_dist = d_pts

            is_human = tr.is_pedestrian or tr.is_unknown
            cl = calculate_clearance(pts, is_pedestrian=is_human)
            if cl < min_overall_clearance:
                min_overall_clearance = cl

            ahead = (pts[:, 0] > 0.0) & (np.abs(pts[:, 1]) < R_PLATFORM + 0.35)

            if is_human:
                ped_ahead = (pts[:, 0] > 0.0) & (pts[:, 0] < 4.5) & (np.abs(pts[:, 1]) < 1.8)
                person_like = len(pts) >= SLOW_PERSON_MIN_PTS
                slow_gap = SLOW_PERSON_GAP
                if person_like:
                    slow_gap += min(SLOW_PERSON_MARGIN_K * v_now, SLOW_PERSON_MARGIN_MAX)

                v_pred = v_now
                if STOP_PREDICT_WITH_CANDIDATE and v_now >= STOP_PREDICT_MIN_SPEED:
                    v_pred = max(v_now, abs(v_cand))
                pred_cl, _ = predict_ttc_clearance(
                    tr, v_platform=v_pred, oth=oth, horizon_s=2.0, dt_step=0.2
                )
                if pred_cl < human_pred_min:
                    human_pred_min = pred_cl

                if cl < STOP_GAP or pred_cl < STOP_GAP:
                    stop_reason = "stop_person"
                    notes["stop_person"] = f"stop_person d={max(0.0, min(cl, pred_cl)):.1f}"
                    v_lim = 0.0
                    person_stop = True
                elif ped_ahead.any() or cl < slow_gap:
                    person_slow = True
                    if cl < person_slow_cl:
                        person_slow_cl = cl
            else:
                cl_honest = calculate_clearance(pts, is_pedestrian=False)
                if tr.is_static_object and cl_honest < STATIC_OBJECT_NEAR_GAP:
                    pred_cl, _ = predict_ttc_clearance(
                        tr, v_platform=v_now, oth=oth, horizon_s=2.0, dt_step=0.2
                    )
                    if cl_honest < STOP_GAP or pred_cl < STOP_GAP:
                        stop_reason = stop_reason or "stop_object"
                        notes["stop_object"] = "stop_object"
                        v_lim = 0.0
                    elif cl_honest < SLOW_PERSON_GAP:
                        v_lim = min(v_lim, SLOW_PERSON_V)

                if remaining_dist > 0.35:
                    in_corridor = ahead & (pts[:, 0] < d_stop_corridor)
                    front_gap = math.inf
                    if ahead.any():
                        front_gap = calculate_clearance(pts[ahead], is_pedestrian=False)
                    if in_corridor.any() or front_gap < STOP_GAP:
                        stop_reason = stop_reason or "stop_object"
                        notes["stop_object"] = "stop_object"
                        v_lim = 0.0

        if person_slow and not person_stop:
            v_lim = min(v_lim, SLOW_PERSON_V)
            notes["slow_person"] = f"slow_person d={max(0.0, person_slow_cl):.1f}"

        saw_human = math.isfinite(human_pred_min)
        if saw_human:
            self._last_human_pred = human_pred_min
            self._lost_human_ticks = 0

        if person_stop and not self._person_hold:
            self._person_hold = True
            self._person_note = notes.get("stop_person", "stop_person")

        if self._person_hold:
            if not saw_human:
                self._lost_human_ticks += 1
                if self._lost_human_ticks <= 10:
                    human_pred_min = self._last_human_pred
            if human_pred_min > SLOW_PERSON_GAP:
                self._person_hold = False
                self._person_note = ""
            else:
                stop_reason = stop_reason or "stop_person"
                v_lim = 0.0
                notes["stop_person"] = self._person_note or notes.get("stop_person", "stop_person")

        if remaining_dist > 0.35:
            r = np.asarray(ranges, dtype=float)
            rel = np.asarray(rel_angles, dtype=float)
            if len(r) > 0 and len(rel) == len(r):
                reach = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + v_now * self.dt + 0.25
                with np.errstate(invalid="ignore"):
                    px = r * np.cos(rel)
                    py = r * np.sin(rel)
                    corridor_hit = (
                        np.isfinite(r) & (px > 0.0) & (px < reach) & (np.abs(py) < R_PLATFORM + 0.1)
                    )
                    three_hit = corridor_hit & np.roll(corridor_hit, 1) & np.roll(corridor_hit, -1)
                    if three_hit.any():
                        stop_reason = stop_reason or "too_close"
                        v_lim = 0.0
                        notes["stop_corridor"] = "stop_corridor"

        min_estop_clearance = math.inf
        estop_front_hit = False
        for tr in tracks:
            pts = tr.pts
            if pts is None or len(pts) == 0:
                continue
            if not getattr(tr, "confirmed", False):
                continue
            if getattr(tr, "coast_ticks", 0) > 0:
                continue
            if getattr(tr, "is_unknown", False) and len(pts) < 3:
                continue
            if is_fog and len(pts) < 3:
                continue
            d_pts = float(np.hypot(pts[:, 0], pts[:, 1]).min())
            if d_pts < R_PLATFORM + 0.05:
                continue
            is_human = tr.is_pedestrian or tr.is_unknown
            cl = calculate_clearance(pts, is_pedestrian=is_human)
            if cl < min_estop_clearance:
                min_estop_clearance = cl
            ahead = (pts[:, 0] > 0.0) & (np.abs(pts[:, 1]) < R_PLATFORM + 0.35)
            if (ahead & (pts[:, 0] < d_stop_corridor)).any():
                estop_front_hit = True

        closing = True
        if self._prev_min_cl is not None and math.isfinite(self._prev_min_cl):
            closing = min_estop_clearance < self._prev_min_cl - 0.005
        stopping_normal = (v_now * v_now) / (2.0 * DECEL_NORMAL) + v_now * self.dt
        if (
            math.isfinite(min_estop_clearance)
            and min_estop_clearance < ESTOP_GAP
            and min_estop_clearance < stopping_normal
            and estop_front_hit
            and v_now > 0.05
            and closing
        ):
            is_estop = True
            v_lim = 0.0
            if stop_reason is None:
                stop_reason = "estop"
        self._prev_min_cl = min_estop_clearance if math.isfinite(min_estop_clearance) else None

        if is_lost:
            v_safe = 0.0
            notes["lost"] = f"lost s_lat={sigma_cross:.1f}"
        elif stop_reason is not None and remaining_dist > 0.35:
            v_safe = 0.0
        else:
            v_safe = max(0.0, min(v_cand, v_lim))

        hull_contact = math.isfinite(min_point_dist) and min_point_dist < R_PLATFORM + 0.05
        if is_estop or blocked_wheels or hull_contact:
            w_safe = 0.0
        else:
            w_safe = w_cand

        if is_arrived:
            v_safe = 0.0
            w_safe = 0.0
            if not notes:
                notes["dock"] = "dock"

        is_slowed = v_safe <= 0.35 and v_safe > 0.0
        is_stopped_flag = (stop_reason is not None) or (v_safe == 0.0 and w_safe == 0.0)

        status = determine_status(
            v_odom=v_odom,
            w_odom=w_odom,
            is_arrived=is_arrived,
            is_lost=is_lost,
            is_stopped=is_stopped_flag,
            is_slowed=is_slowed,
            is_estop=is_estop,
            allow_slowed=False,
        )

        return v_safe, w_safe, status, self._compose_note(notes)
