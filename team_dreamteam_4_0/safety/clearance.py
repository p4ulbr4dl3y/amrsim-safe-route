"""Модуль расчета зазоров, дистанций и прогнозирования времени до столкновения (TTC).

Строго соответствует требованиям изоляции и безопасности
(только стандартная библиотека math/typing и numpy).
"""

import math
from typing import Tuple

import numpy as np

try:
    from ..perceive import Track
except (ImportError, ValueError):
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
