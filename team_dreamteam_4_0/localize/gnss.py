"""Модуль стробирования точности ГНСС и комплексирования измерений."""

import math
from typing import List, Tuple

import numpy as np


class GNSSFilter:
    """Стробирование измерений ГНСС и комплексирование с фильтром состояния."""

    def __init__(self) -> None:
        self.rejections: List[Tuple[float, float]] = []
        self.last_accepted: bool = False
        self.fix_ticks: int = 10**9

    def update(
        self,
        x: float,
        y: float,
        var_along: float,
        var_cross: float,
        gnss_x: float,
        gnss_y: float,
        gnss_valid: bool,
        gnss_hdop: float,
        in_shadow: bool = False,
        scan_inliers: int = 0,
        fog_active: bool = False,
    ) -> Tuple[bool, float, float, float, float, bool]:
        """Обновить оценку позы по измерению ГНСС со стробированием невязки.

        Параметры:
          x: текущая координата x платформы;
          y: текущая координата y платформы;
          var_along: дисперсия позы вдоль направления движения;
          var_cross: дисперсия позы поперек направления движения;
          gnss_x: координата x по измерению приемника ГНСС;
          gnss_y: координата y по измерению приемника ГНСС;
          gnss_valid: флаг валидности решения навигационного приемника;
          gnss_hdop: геометрический фактор снижения точности в горизонтальной плоскости;
          in_shadow: признак нахождения платформы в зоне радиотени;
          scan_inliers: количество точек лидарного скана, сопоставленных со стенами;
          fog_active: флаг активности детектора тумана.

        Возвращает:
          кортеж флага принятия измерения, обновленных координат x и y,
          дисперсий вдоль и поперек пути, а также флага сброса дистанции.
        """
        self.last_accepted = False

        # Отсечение измерений при радиотени, невалидном статусе или высоком факторе снижения точности
        if in_shadow or not gnss_valid or gnss_hdop > 2.0:
            self.rejections.clear()
            self.fix_ticks += 1
            return False, x, y, var_along, var_cross, False

        dx = gnss_x - x
        dy = gnss_y - y
        dist = math.hypot(dx, dy)

        # Стробирование невязки ГНСС: базовый допуск составляет 1.5 м
        if dist < 1.5:
            scan_ok = (scan_inliers >= 30) or fog_active
            if not scan_ok and dist > 0.6:
                # Карта не подтверждает позу: удержание до восстановления совпадения
                self.fix_ticks += 1
                self.rejections.append((dx, dy))
                return False, x, y, var_along, var_cross, False

            self.rejections.clear()
            # Модель шума измерения ГНСС с масштабированием по геометрическому фактору точности
            r_var = (0.3 * max(1.0, gnss_hdop)) ** 2
            k_x = var_along / (var_along + r_var)
            k_y = var_cross / (var_cross + r_var)
            # Ограничение коэффициента подмешивания значением не более 0.15 (запрет прямого копирования)
            k = max(0.01, min(0.15, 0.5 * (k_x + k_y)))
            if gnss_hdop > 1.4:
                k *= 0.5
            if not scan_ok:
                k *= 0.3

            # Плавная коррекция позы без скачков
            new_x = x + k * dx
            new_y = y + k * dy
            new_var_along = max(0.04, var_along * (1.0 - k))
            new_var_cross = max(0.04, var_cross * (1.0 - k))

            self.last_accepted = True
            self.fix_ticks = 0
            return True, new_x, new_y, new_var_along, new_var_cross, True

        # Отклоненная невязка: проверка устойчивого согласия измерений
        self.fix_ticks += 1
        self.rejections.append((dx, dy))

        if len(self.rejections) >= 60:
            recent = np.array(self.rejections[-40:])
            shift_x = float(recent[:, 0].mean())
            shift_y = float(recent[:, 1].mean())
            shift = math.hypot(shift_x, shift_y)
            if recent.std(axis=0).max() < 0.5 and scan_inliers >= 60 and 1.5 < shift < 3.0:
                # Фильтр сдрейфовал вдоль гладкой стены: коррекция с коэффициентом k <= 0.15 без прямого присвоения
                k = 0.15
                new_x = x + k * shift_x
                new_y = y + k * shift_y
                new_var_along = max(0.04, var_along * (1.0 - k))
                new_var_cross = max(0.04, var_cross * (1.0 - k))
                self.rejections.clear()
                self.last_accepted = True
                return True, new_x, new_y, new_var_along, new_var_cross, False
            if len(self.rejections) > 80:
                self.rejections.pop(0)

        return False, x, y, var_along, var_cross, False
