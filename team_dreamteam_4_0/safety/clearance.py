"""Модуль расчета зазоров, дистанций и прогнозирования времени до столкновения.

Строго соответствует требованиям изоляции и безопасности:
используются только стандартная библиотека math, typing и numpy.
"""

import math
from typing import Tuple

import numpy as np

try:
    from ..perceive import Track
except (ImportError, ValueError):
    from perceive import Track


# Константы платформы и безопасности
R_PLATFORM = 0.9  # Радиус платформы в метрах
R_PEDESTRIAN = 0.3  # Радиус пешехода в метрах
DECEL_NORMAL = 1.2  # Штатное служебное замедление в м/с^2
DT = 0.1  # Шаг симуляции в секундах
V_MAX_DEFAULT = 1.39  # Максимальная скорость аппарата в м/с

SLOW_PERSON_GAP = 3.3  # Текущий зазор, ниже которого скорость возле человека ограничивается до <= 0.22 м/с
SLOW_PERSON_V = 0.22  # Ограничение скорости рядом с человеком или неизвестным объектом в м/с
# Штраф начисляется при зазоре < 3.0 м и |v| > 0.28 м/с, но команда 0.22 м/с
# не приводит к мгновенной остановке: платформа тормозит с замедлением 1.2 м/с^2, поэтому
# торможение должно начинаться заранее на дистанции 3.3 м.
SLOW_PERSON_MARGIN_K = 0.28  # Дополнительный запас в секундах на каждый м/с текущей скорости для покрытия пути торможения
SLOW_PERSON_MARGIN_MAX = 0.40  # Жесткое ограничение упреждающего запаса в метрах
SLOW_PERSON_MIN_PTS = 4  # Похожий на человека кластер: снежный отклик никогда не бывает такой ширины
# Прогноз зазора на 2 с определяет попадание объекта в защитный круг. Использование
# уже заниженной скорости v_odom занижает риск: если ограничение снизило скорость до 0.22 м/с,
# прогноз кажется безопасным, остановка не срабатывает, и платформа ползет в потоке пешеходов.
# Прогноз строится по скорости, запрошенной планировщиком.
STOP_PREDICT_WITH_CANDIDATE = True
STOP_PREDICT_MIN_SPEED = 0.5  # Порог скорости в м/с: только при быстром качении платформы
STOP_GAP = 0.8  # Текущий или прогнозируемый зазор в метрах, ниже которого v = 0
# Статический объект с честным зазором без вычитания радиуса 0.3 м ниже этого порога
# находится достаточно близко, чтобы ошибка классификации стала критичной: модуль безопасности
# применяет к нему ограничения для пешеходов.
STATIC_OBJECT_NEAR_GAP = 1.5
ESTOP_GAP = 1.2  # Дистанция подтвержденного кластера для экстренного торможения в метрах

def calculate_clearance(
    pts: np.ndarray,
    is_pedestrian: bool = True,
) -> float:
    """Вычислить зазор от периметра мобильной платформы до периметра препятствия.

    Правила геометрического вычисления зазоров:
    - радиус платформы равен 0.9 м;
    - радиус пешехода равен 0.3 м и вычитается для пешеходов и неизвестных препятствий;
    - для стен, заборов и подтвержденных статических объектов вычитается только радиус платформы.

    Параметры:
      pts: двумерный массив координат точек препятствия в локальной системе координат;
      is_pedestrian: флаг применения пешеходного защитного радиуса.

    Возвращает:
      величину зазора в метрах, где отрицательные значения соответствуют пересечению контуров.
    """
    if pts is None or len(pts) == 0:
        return math.inf
    pts = np.asarray(pts)
    if pts.ndim != 2 or pts.shape[1] < 2:
        return math.inf
    valid_mask = np.isfinite(pts[:, 0]) & np.isfinite(pts[:, 1])
    if not np.any(valid_mask):
        return math.inf
    valid_pts = pts[valid_mask]
    d_min = float(np.hypot(valid_pts[:, 0], valid_pts[:, 1]).min())
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
    """Спрогнозировать минимальный зазор до препятствия на заданном временном горизонте.

    Учитывает линейную скорость платформы по курсу и векторную скорость объекта
    в чистом базисе одометрии.

    Параметры:
      track: отслеживаемый трек препятствия;
      v_platform: скорость движения платформы вперед в м/с;
      oth: курсовой угол платформы в базисе одометрии в радианах;
      horizon_s: глубина временного горизонта прогноза в секундах;
      dt_step: дискретный шаг прогнозирования в секундах.

    Возвращает:
      кортеж из минимального прогнозируемого зазора в метрах и времени его достижения в секундах.
    """
    pts = track.pts
    if pts is None or len(pts) == 0:
        return math.inf, horizon_s
    pts = np.asarray(pts)
    if pts.ndim != 2 or pts.shape[1] < 2:
        return math.inf, horizon_s

    valid_mask = np.isfinite(pts[:, 0]) & np.isfinite(pts[:, 1])
    if not np.any(valid_mask):
        return math.inf, horizon_s
    pts = pts[valid_mask]

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

    is_ped = bool(
        getattr(track, "is_pedestrian", False)
        or getattr(track, "is_unknown", False)
        or getattr(track, "dyn", None) is True
        or getattr(track, "label", None) in ("pedestrian", "unknown")
        or getattr(track, "class_label", None) in ("pedestrian", "unknown")
    )
    radius_sub = (R_PLATFORM + R_PEDESTRIAN) if is_ped else R_PLATFORM

    for t in t_steps:
        pred_x = pts[:, 0] + v_rel_x * t
        pred_y = pts[:, 1] + v_rel_y * t
        dist = np.hypot(pred_x, pred_y).min()
        cl = float(dist - radius_sub)
        if cl < min_clearance:
            min_clearance = cl
            min_t = float(t)

    return min_clearance, min_t
