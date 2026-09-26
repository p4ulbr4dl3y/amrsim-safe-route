"""Модуль расширенного фильтра Калмана (EKF) и счисления пути.

Включает:
- распространение позы по одометрии и IMU с калибровкой масштаба;
- сторожевой таймер курса IMU (watchdog по скачкам > 0.05 рад);
- распространение дисперсий вдоль и поперек пути;
- обновление дисперсий по нормалям наблюдаемых стен;
- откат прогноза при пробуксовке колес.

Соответствует требованиям Т3 и Т5 (только stdlib и numpy, относительные импорты).
"""

import math
from typing import Tuple

import numpy as np

try:
    from ..geom import wrap_angle
except (ImportError, ValueError):
    from geom import wrap_angle


class EKFFilter:
    """Оценщик состояния EKF для мобильной платформы."""

    @staticmethod
    def along_bound_m(unconfirmed_dist: float, scale_locked: bool) -> float:
        """Граница погрешности вдоль пути, задаваемая смещением масштаба одометрии."""
        scale_err = 0.01 if scale_locked else 0.04
        beyond = unconfirmed_dist - 0.2 / scale_err
        return scale_err * beyond if beyond > 0.0 else 0.0

    @staticmethod
    def predict(
        x: float,
        y: float,
        th: float,
        ox: float,
        oy: float,
        oth: float,
        var_along: float,
        var_cross: float,
        var_th: float,
        scale: float,
        unconfirmed_dist: float,
        scale_locked: bool,
        odom_dx: float,
        odom_dy: float,
        odom_dth: float,
        imu_heading: float,
        imu_yaw_rate: float,
        dt: float,
        heading_bias: float,
        bias_initialized: bool,
    ) -> Tuple[
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        bool,
        Tuple[float, float, float],
        float,
    ]:
        """Выполнить шаг прогноза EKF по одометрии и IMU."""
        cos_oth = math.cos(oth)
        sin_oth = math.sin(oth)
        new_ox = ox + cos_oth * odom_dx - sin_oth * odom_dy
        new_oy = oy + sin_oth * odom_dx + cos_oth * odom_dy
        new_oth = wrap_angle(oth + odom_dth)

        step_dist = math.hypot(odom_dx, odom_dy)

        s = scale if (0.90 <= scale <= 1.10) else 1.0
        scaled_dx = odom_dx / s
        scaled_dy = odom_dy / s

        cos_th = math.cos(th)
        sin_th = math.sin(th)
        world_dx = cos_th * scaled_dx - sin_th * scaled_dy
        world_dy = sin_th * scaled_dx + cos_th * scaled_dy
        new_x = x + world_dx
        new_y = y + world_dy

        cur_bias = heading_bias
        cur_init = bias_initialized
        if not cur_init and not math.isnan(imu_heading):
            cur_bias = wrap_angle(imu_heading - th)
            cur_init = True

        expected_th = wrap_angle(th + imu_yaw_rate * dt)
        if math.isnan(imu_heading):
            new_th = expected_th
        else:
            measured_th = wrap_angle(imu_heading - cur_bias)
            if abs(wrap_angle(measured_th - expected_th)) > 0.05:
                new_th = expected_th
            else:
                new_th = measured_th

        new_unconfirmed = unconfirmed_dist + step_dist
        scale_err = 0.01 if scale_locked else 0.04
        beyond = new_unconfirmed - 0.2 / scale_err
        bound = scale_err * beyond if beyond > 0.0 else 0.0
        new_var_along = max(var_along, bound**2) if bound > 0.0 else var_along
        d_var_along = 0.0

        yaw_drift_var = (0.00067**2) * dt
        new_var_th = var_th + yaw_drift_var
        d_var_cross = (
            (step_dist * math.sin(math.sqrt(new_var_th))) ** 2 + (0.005 * step_dist) ** 2 + 1e-5
        )
        new_var_cross = var_cross + d_var_cross
        predict_var = (d_var_along, d_var_cross, yaw_drift_var)

        return (
            new_x,
            new_y,
            new_th,
            new_ox,
            new_oy,
            new_oth,
            new_var_along,
            new_var_cross,
            new_var_th,
            new_unconfirmed,
            cur_bias,
            cur_init,
            predict_var,
            step_dist,
        )

    @staticmethod
    def rollback_predict(
        pre_predict_xy: Tuple[float, float],
        predict_var: Tuple[float, float, float],
        odom_step_tick: float,
        var_along: float,
        var_cross: float,
        var_th: float,
        pending_odom_step: float,
        unconfirmed_dist: float,
    ) -> Tuple[float, float, float, float, float, float, float]:
        """Отменить шаг прогноза при пробуксовке колес."""
        restored_x, restored_y = pre_predict_xy
        da, dc, dth = predict_var
        new_var_along = max(0.0, var_along - da)
        new_var_cross = max(0.0, var_cross - dc)
        new_var_th = max(0.0, var_th - dth)
        new_pending = max(0.0, pending_odom_step - odom_step_tick)
        new_unconfirmed = max(0.0, unconfirmed_dist - odom_step_tick)
        return (
            restored_x,
            restored_y,
            new_var_along,
            new_var_cross,
            new_var_th,
            new_pending,
            new_unconfirmed,
        )

    @staticmethod
    def update_variances_from_walls(
        th: float,
        var_along: float,
        var_cross: float,
        var_th: float,
        normals: np.ndarray,
        weights: np.ndarray,
    ) -> Tuple[float, float, float, bool]:
        """Обновить дисперсии по нормалям и касательным наблюдаемых стен."""
        n_x = float(np.average(normals[:, 0], weights=weights))
        n_y = float(np.average(normals[:, 1], weights=weights))
        norm_mag = math.hypot(n_x, n_y)
        if norm_mag <= 1e-3:
            return var_along, var_cross, var_th, False

        n_x /= norm_mag
        n_y /= norm_mag

        alpha = math.atan2(n_y, n_x)
        d_angle = wrap_angle(alpha - th)
        cos_d2 = math.cos(d_angle) ** 2
        sin_d2 = math.sin(d_angle) ** 2

        var_wall = 0.02**2
        new_var_cross = var_cross * cos_d2 + var_wall * sin_d2
        new_var_along = var_along * sin_d2 + var_wall * cos_d2
        new_var_th = min(var_th, 0.01**2)

        reset_unconfirmed = False
        if normals.size:
            head = normals[:, 0] * math.cos(th) + normals[:, 1] * math.sin(th)
            if float(np.max(np.abs(head))) > 0.87:
                reset_unconfirmed = True

        return new_var_along, new_var_cross, new_var_th, reset_unconfirmed
