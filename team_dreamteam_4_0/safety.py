"""Модуль безопасности и ограничителя скорости.

Строго соответствует plan/03-vospriyatie-i-bezopasnost.md, plan/01-schet-i-ploshchadka.md
и порогам оценки (только стандартная библиотека math/typing и numpy).
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from .geom import inside_polygon
    from .perceive import Track
except ImportError:
    from geom import inside_polygon
    from perceive import Track


# Константы платформы и безопасности
R_PLATFORM = 0.9  # Радиус платформы (м)
R_PEDESTRIAN = 0.3  # Радиус пешехода (м)
DECEL_NORMAL = 1.2  # Штатное служебное замедление (м/с^2)
DT = 0.1  # Шаг симуляции (с)
V_MAX_DEFAULT = 1.39  # Максимальная скорость аппарата (м/с)

SLOW_PERSON_GAP = 3.3  # Текущий зазор, ниже которого скорость возле человека ограничивается до <= 0.22 м/с
SLOW_PERSON_V = 0.22  # Ограничение скорости рядом с человеком или неизвестным объектом
# Штраф начисляется при зазоре < 3.0 м и |v| > 0.28 м/с, но команда 0.22 м/с
# не приводит к мгновенной остановке: платформа тормозит с 1.2 м/с^2, поэтому
# торможение должно начинаться заранее на дистанции 3.3 м.
SLOW_PERSON_MARGIN_K = 0.28  # с: дополнительный запас на каждый м/с текущей скорости (покрытие торможения)
SLOW_PERSON_MARGIN_MAX = 0.40  # м: жесткое ограничение упреждающего запаса
SLOW_PERSON_MIN_PTS = 4  # Похожий на человека кластер: снежный отклик никогда не бывает такой ширины
# Прогноз зазора на 2 с определяет попадание объекта в защитный круг. Использование
# уже заниженной скорости v_odom занижает риск: если ограничение снизило скорость до 0.22 м/с,
# прогноз кажется безопасным, остановка не срабатывает, и платформа ползет в потоке пешеходов.
# Прогноз строится по скорости, запрошенной планировщиком.
STOP_PREDICT_WITH_CANDIDATE = True
STOP_PREDICT_MIN_SPEED = 0.5  # м/с: только при быстром качении платформы
STOP_GAP = 0.8  # Текущий или прогнозируемый зазор, ниже которого v = 0
# Статический объект с честным зазором (без вычитания радиуса 0.3 м) ниже этого порога
# находится достаточно близко, чтобы ошибка классификации стала критичной: модуль безопасности
# применяет к нему ограничения для пешеходов.
STATIC_OBJECT_NEAR_GAP = 1.5
ESTOP_GAP = 1.2  # Дистанция подтвержденного кластера для экстренного торможения


def calculate_clearance(
    pts: np.ndarray,
    is_pedestrian: bool = True,
) -> float:
    """Вычислить зазор от периметра AMR до периметра препятствия.

    Радиус AMR = 0.9 м.
    Радиус пешехода = 0.3 м (вычитается для пешеходов и неизвестных препятствий).
    Для стен/заборов и статических объектов вычитается только радиус AMR.

    Возвращает:
      зазор в метрах (может быть <= 0 при контакте).
    """
    if pts is None or len(pts) == 0:
        return math.inf
    d_min = float(np.hypot(pts[:, 0], pts[:, 1]).min())
    if is_pedestrian:
        return d_min - R_PLATFORM - R_PEDESTRIAN
    return d_min - R_PLATFORM


def predict_ttc_clearance(
    track: Track,
    v_platform: float,
    oth: float,
    horizon_s: float = 2.0,
    dt_step: float = 0.2,
) -> Tuple[float, float]:
    """Спрогнозировать минимальный зазор до трека на горизонте 2.0 с шагом 0.2 с.

    Учитывает скорость платформы вдоль курса и скорость трека в чистом базисе одометрии.

    Аргументы:
      track: экземпляр Track препятствия;
      v_platform: скорость платформы вперед (м/с);
      oth: курс AMR в чистом базисе одометрии (рад);
      horizon_s: горизонт прогноза (по умолчанию 2.0);
      dt_step: шаг времени прогноза (по умолчанию 0.2).

    Возвращает:
      (min_predicted_clearance, time_to_min_clearance).
    """
    pts = track.pts
    if pts is None or len(pts) == 0:
        return math.inf, horizon_s

    # Скорость трека в базисе робота
    cos_oth = math.cos(oth)
    sin_oth = math.sin(oth)
    vx_r = cos_oth * track.vx_odom + sin_oth * track.vy_odom
    vy_r = -sin_oth * track.vx_odom + cos_oth * track.vy_odom

    # Относительная скорость трека относительно движущейся платформы
    v_rel_x = vx_r - v_platform
    v_rel_y = vy_r

    t_steps = np.arange(dt_step, horizon_s + 1e-6, dt_step)
    min_clearance = math.inf
    min_t = horizon_s

    radius_sub = R_PLATFORM

    for t in t_steps:
        pred_x = pts[:, 0] + v_rel_x * t
        pred_y = pts[:, 1] + v_rel_y * t
        dist = np.hypot(pred_x, pred_y).min()
        cl = float(dist - radius_sub)
        if cl < min_clearance:
            min_clearance = cl
            min_t = float(t)

    return min_clearance, min_t


def determine_status(
    v_odom: float,
    w_odom: float = 0.0,
    is_arrived: bool = False,
    is_lost: bool = False,
    is_stopped: bool = False,
    is_slowed: bool = False,
    is_estop: bool = False,
    allow_slowed: bool = False,
) -> str:
    """Определить рабочий статус AMR.

    Соответствует правилам оценки:
    - статус ОБЯЗАН быть 'moving', когда |v_odom| >= 0.05, чтобы не допустить status_mismatch (-2);
    - статус 'arrived', когда выполнено условие прибытия в док;
    - статус 'waiting', когда платформа стоит (|v_odom| < 0.05) из-за препятствия, человека или паузы;
    - статус 'lost', когда поза потеряна И платформа уже остановилась (plan/02:145);
    - статус 'estop', когда сработало экстренное торможение;
    - если allow_slowed=True и робот движется при сниженном ограничении скорости, возвращается 'slowed'.
    """
    if is_arrived:
        return "arrived"
    if is_estop:
        return "estop"

    # Порог движения из критериев оценки: moving_v = 0.05 м/с
    if abs(v_odom) >= 0.05 or abs(w_odom) >= 0.10:
        if allow_slowed and is_slowed:
            return "slowed"
        return "moving"

    # Стационарное состояние (|v_odom| < 0.05)
    if is_lost:
        return "lost"
    if is_stopped:
        return "waiting"
    if is_slowed and allow_slowed:
        return "slowed"

    return "waiting"


class SafetyGovernor:
    """Модуль безопасности, обеспечивающий зазор, ограничения скорости, торможение в коридоре и примечания.

    Ограничивает скорость согласно plan/03 (побеждает самый жесткий лимит):
    1. Прогнозируемый зазор до пешехода/неизвестного объекта за 2 с < 0.8 м -> v = 0. Пока платформа
       еще катится быстро (>= STOP_PREDICT_MIN_SPEED), прогноз использует скорость, запрошенную
       следователем пути, а не v_odom, который мог только что обрушить наш собственный медленный
       лимит, поэтому ограничение до ползания не может подавить действительно необходимую остановку
       (см. STOP_PREDICT_WITH_CANDIDATE).
    2. Текущий зазор до пешехода/неизвестного объекта < 0.8 м -> v = 0, удерживается, пока
       прогнозируемый зазор не превысит 3.3 м (для динамических/неизвестных треков таймаута
       'подождать и поехать' нет).
    3. Текущий зазор до человекоподобного пешехода/неизвестного объекта < 3.3 м плюс упреждающий
       запас, растущий с текущей скоростью (SLOW_PERSON_MARGIN_K*|v_odom|, с ограничением),
       ограничивает v значением <= 0.22 (штраф начинается при 3.0 м / 0.28 м/с, поэтому остается
       запас на торможение 1.2 м/с^2 и на человека, идущего навстречу платформе).
    4. Три соседних отклика лидара в коридоре |y| < 1.0 м внутри тормозного пути -> v = 0.
    5. Неразмеченная стена (is_wall/map_extra) и статический объект в коридоре -> учитываются как
       препятствие в зазоре и в проверке коридора, никогда не игнорируются.
    6. Туман + необъясненный кластер впереди < 5.0 м -> v <= 0.35; туман и чисто -> v <= 0.90.
    7. Потеря позы (is_lost) -> v = 0; статус становится 'lost' только после остановки платформы.
    8. estop (2.5 м/с^2) только когда подтвержденный кластер ближе 1.2 м, зазор сокращается и
       штатное торможение 1.2 м/с^2 не успевает остановиться. Никогда выше 1.5 м (ложный estop = -1).
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

        # Триггер остановки перед человеком: после остановки удерживать v = 0 до тех пор,
        # пока прогнозируемый зазор до каждого пешехода не превысит 3.3 м.
        # Фиксированный таймаут ожидания для динамических треков запрещен.
        self._person_hold: bool = False
        self._person_note: str = ""
        self._last_human_pred: float = math.inf
        self._lost_human_ticks: int = 0
        # Предыдущий минимальный зазор для подтверждения сближения при экстренном торможении
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
                # Запас 0.05 для предотвращения превышения скорости
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
        """Оценить ограничения безопасности и определить безопасную команду (v, w), статус и примечание.

        Аргументы:
          v_cand: запрошенная скорость вперед от следователя пути (м/с);
          w_cand: запрошенная угловая скорость от следователя пути (рад/с);
          v_odom: текущая скорость вперед по одометрии (м/с);
          w_odom: текущая угловая скорость по одометрии (рад/с);
          pose: мировая поза (x, y, th);
          odom_pose: чистая поза одометрии (ox, oy, oth);
          tracks: активные треки распознавания (включая неразмеченные стены, is_wall=True);
          ranges: дальности лучей лидара (360,);
          rel_angles: относительные углы лучей в базисе робота (360,);
          zones: зоны ограничения скорости [(polygon, v_max), ...];
          is_fog: активен ли режим тумана;
          is_arrived: достигнута ли цель дока;
          is_lost: потерян ли локализатор (v принудительно 0);
          blocked_wheels: обнаружено ли проскальзывание колес или контакт со стеной;
          perception_note: существующее примечание распознавания (например map_missing/map_extra);
          remaining_dist: оставшееся расстояние до дока, метры;
          sigma_cross: поперечная сигма позы, выводимая в примечании `lost s_lat=`.

        Возвращает:
          (v_safe, w_safe, status, note).
        """
        x, y, th = pose
        _, _, oth = odom_pose
        v_now = abs(v_odom)

        v_lim = self.v_top
        stop_reason: Optional[str] = None
        notes: Dict[str, str] = {}
        is_estop: bool = False

        # Примечание распознавания (map_missing / map_extra) сохраняется на время действия причины
        if perception_note:
            notes["map"] = perception_note

        # 1. Блокировка колес или контакт со стеной
        if blocked_wheels:
            stop_reason = "blocked_wheels"
            notes["blocked_wheels"] = "blocked_wheels"
            v_lim = 0.0

        # 2. Зональные ограничения скорости: текущая позиция и упреждение на 3.0 м вперед
        cos_th = math.cos(th)
        sin_th = math.sin(th)
        zone_curr = self.get_zone_limit(x, y, zones)
        zone_ahead = self.get_zone_limit(x + 3.0 * cos_th, y + 3.0 * sin_th, zones)
        zone_effective = min(zone_curr, zone_ahead)
        v_lim = min(v_lim, zone_effective)
        if zone_effective < self.v_top:
            notes["zone"] = f"zone v={zone_effective:.2f}"

        # 3. Ограничения в тумане
        if is_fog:
            # Проверка наличия необъясненного кластера впереди ближе 5.0 м
            has_cluster_ahead = False
            for tr in tracks:
                if tr.pts is not None and len(tr.pts) > 0:
                    pts = tr.pts
                    # Впереди робота и ближе 5.0 м
                    in_front = (pts[:, 0] > 0.0) & (pts[:, 0] < 5.0) & (np.abs(pts[:, 1]) < 2.0)
                    if in_front.any():
                        has_cluster_ahead = True
                        break

            if has_cluster_ahead:
                v_lim = min(v_lim, 0.35)
                notes["fog"] = "fog_cluster"
            else:
                # Туман при чистом пути впереди: до 0.9 м/с для соблюдения дедлайна
                v_lim = min(v_lim, 0.90)
                notes["fog"] = "fog_clear"

        # 4. Зазоры до треков и предиктивное время до столкновения TTC.
        # Неразмеченные стены (is_wall=True, map_extra) обязательно учитываются как препятствия.
        d_stop_corridor = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + 0.6

        min_overall_clearance = math.inf
        human_pred_min = math.inf
        person_stop = False
        person_slow = False
        person_slow_cl = math.inf
        front_hit = False  # Кластер находится строго впереди в пределах коридора
        # Флаг истинного контакта: минимальное расстояние от центра до точки по всем кластерам.
        # Тормозной путь относится к поступательному движению, но корпус представляет собой диск 0.9 м,
        # поэтому разворот на месте безопасен, пока ближайшая точка лежит вне диска.
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
            if (ahead & (pts[:, 0] < d_stop_corridor)).any():
                front_hit = True

            if is_human:
                ped_ahead = (pts[:, 0] > 0.0) & (pts[:, 0] < 4.5) & (np.abs(pts[:, 1]) < 1.8)
                person_like = len(pts) >= SLOW_PERSON_MIN_PTS
                slow_gap = SLOW_PERSON_GAP
                if person_like:
                    slow_gap += min(SLOW_PERSON_MARGIN_K * v_now, SLOW_PERSON_MARGIN_MAX)
                # При быстром движении прогноз использует скорость, запрошенную планировщиком,
                # а не уже замедленную одометрию. Когда платформа уже замедлилась (<= 0.5 м/с),
                # зазор 2.5 м удерживает скорость 0.22 м/с.

                # A. Текущий или прогнозируемый (горизонт 2 с) зазор < 0.8 м -> остановка
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
                # B. Человек впереди в коридоре ближе 4.5 м или зазор ниже порога реагирования.
                # Порог реагирования составляет 3.3 м плюс упреждающий запас для человекоподобного кластера.
                # Одиночные снежные отклики запаса не получают и движение не замедляют.
                elif ped_ahead.any() or cl < slow_gap:
                    person_slow = True
                    if cl < person_slow_cl:
                        person_slow_cl = cl
            else:
                # Подтвержденный статический объект или неразмеченная стена: человеческие лимиты не действуют.
                # Ограничения остановки:
                # - кластер находится в коридоре торможения;
                # - честный зазор точки во фронтальной полосе ниже STOP_GAP.
                # Защита от ошибок классификации: статический объект с зазором ниже STATIC_OBJECT_NEAR_GAP
                # получает человеческие ограничения.
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

        # 5. Триггер остановки перед человеком. Скорость v остается равной 0, пока прогнозируемый
        # зазор до каждого пешехода не станет больше 3.3 м.
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

        # 6. Проверка сырого коридора лидара (|y| < 1.0 м в пределах дистанции торможения)
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
                    # Три соседних луча: реальное препятствие, не снежинка
                    three_hit = corridor_hit & np.roll(corridor_hit, 1) & np.roll(corridor_hit, -1)
                    if three_hit.any():
                        stop_reason = stop_reason or "too_close"
                        v_lim = 0.0
                        notes["stop_corridor"] = "stop_corridor"

        # 7. Экстренное торможение 2.5 м/с^2 только при сближении с подтвержденным кластером
        # ближе 1.2 м, когда штатного торможения 1.2 м/с^2 недостаточно.
        # Ложное экстренное торможение при зазоре >= 1.5 м штрафуется.
        closing = True
        if self._prev_min_cl is not None and math.isfinite(self._prev_min_cl):
            closing = min_overall_clearance < self._prev_min_cl - 0.005
        stopping_normal = (v_now * v_now) / (2.0 * DECEL_NORMAL) + v_now * self.dt
        if (
            math.isfinite(min_overall_clearance)
            and min_overall_clearance < ESTOP_GAP
            and min_overall_clearance < stopping_normal
            and front_hit
            and v_now > 0.05
            and closing
        ):
            is_estop = True
            v_lim = 0.0
            if stop_reason is None:
                stop_reason = "estop"
        self._prev_min_cl = min_overall_clearance if math.isfinite(min_overall_clearance) else None

        # 8. Арбитраж линейной скорости v
        if is_lost:
            # Поза неизвестна: остановка и учет только подтвержденного движения между сканами
            v_safe = 0.0
            notes["lost"] = f"lost s_lat={sigma_cross:.1f}"
        elif stop_reason is not None and remaining_dist > 0.35:
            v_safe = 0.0
        else:
            v_safe = max(0.0, min(v_cand, v_lim))

        # 9. Арбитраж угловой скорости w. Разворот на месте рядом с препятствием разрешен:
        # корпус представляет собой диск 0.9 м, разворот на месте не приближает робота к объекту.
        # Стена или объект в коридоре обнуляют линейную скорость v, но не блокируют угловую w,
        # позволяя планировщику выполнить объезд. Блокировка w происходит только при физическом
        # контакте с корпусом, экстренной остановке или блокировке колес.
        hull_contact = math.isfinite(min_point_dist) and min_point_dist < R_PLATFORM + 0.05
        if is_estop or blocked_wheels or hull_contact:
            w_safe = 0.0
        else:
            w_safe = w_cand

        # 10. Удержание прибытия: удержание нулевой скорости в доке
        if is_arrived:
            v_safe = 0.0
            w_safe = 0.0
            if not notes:
                notes["dock"] = "dock"

        # 11. Определение статуса
        is_slowed = v_safe <= 0.35 and v_safe > 0.0
        is_stopped_flag = (stop_reason is not None) or (v_safe == 0.0 and w_safe == 0.0)

        # Статус симулятора: строго moving при |v_odom| >= 0.05
        status = determine_status(
            v_odom=v_odom,
            w_odom=w_odom,
            is_arrived=is_arrived,
            is_lost=is_lost,
            is_stopped=is_stopped_flag,
            is_slowed=is_slowed,
            is_estop=is_estop,
            allow_slowed=False,  # Строго moving при движении во избежание status_mismatch
        )

        return v_safe, w_safe, status, self._compose_note(notes)
