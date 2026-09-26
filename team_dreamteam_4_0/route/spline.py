"""Квинтовый сплайн (полином 5-й степени) для гладкой интерполяции и ограничения рывка (jerk).

Изоляция: используются только math, typing и numpy.
"""


import numpy as np


class QuinticSpline1D:
    """Одномерный квинтовый сплайн s(t): гладкая траектория c непрерывными v(t) и a(t)."""

    def __init__(
        self,
        x0: float,
        v0: float,
        a0: float,
        x1: float,
        v1: float,
        a1: float,
        duration: float,
    ) -> None:
        self.t_total = max(1e-4, float(duration))
        self.a0 = float(x0)
        self.a1 = float(v0)
        self.a2 = 0.5 * float(a0)

        t = self.t_total
        t2 = t * t
        t3 = t2 * t
        t4 = t3 * t
        t5 = t4 * t

        h = float(x1) - float(x0)

        # Решение системы уравнений граничных условий на t_total:
        # [t^3,    t^4,    t^5  ] [a3]   [h]
        # [3*t^2,  4*t^3,  5*t^4] [a4] = [v]
        # [6*t,   12*t^2, 20*t^3] [a5]   [a]
        # Аналитическое решение:
        self.a3 = (10.0 * h - (4.0 * float(v1) + 6.0 * float(v0)) * t + 0.5 * (float(a1) - 3.0 * float(a0)) * t2) / t3
        self.a4 = (-15.0 * h + (7.0 * float(v1) + 8.0 * float(v0)) * t - (float(a1) - 1.5 * float(a0)) * t2) / t4
        self.a5 = (6.0 * h - 3.0 * (float(v1) + float(v0)) * t + 0.5 * (float(a1) - float(a0)) * t2) / t5

    def calc_point(self, t: float) -> float:
        """Положение s(t)."""
        t = np.clip(t, 0.0, self.t_total)
        return float(
            self.a0
            + self.a1 * t
            + self.a2 * (t**2)
            + self.a3 * (t**3)
            + self.a4 * (t**4)
            + self.a5 * (t**5)
        )

    def calc_first_derivative(self, t: float) -> float:
        """Первая производная s'(t) (скорость)."""
        t = np.clip(t, 0.0, self.t_total)
        return float(
            self.a1
            + 2.0 * self.a2 * t
            + 3.0 * self.a3 * (t**2)
            + 4.0 * self.a4 * (t**3)
            + 5.0 * self.a5 * (t**4)
        )

    def calc_second_derivative(self, t: float) -> float:
        """Вторая производная s''(t) (ускорение)."""
        t = np.clip(t, 0.0, self.t_total)
        return float(
            2.0 * self.a2
            + 6.0 * self.a3 * t
            + 12.0 * self.a4 * (t**2)
            + 20.0 * self.a5 * (t**3)
        )


def smooth_yaw_rate_quintic(
    w_curr: float,
    w_target: float,
    dt: float = 0.1,
    horizon_s: float = 0.3,
) -> float:
    """Сглаживание угловой скорости с помощью квинтового сплайна для устранения осцилляций."""
    if abs(w_target - w_curr) < 1e-4:
        return float(w_target)
    spline = QuinticSpline1D(
        x0=w_curr,
        v0=0.0,
        a0=0.0,
        x1=w_target,
        v1=0.0,
        a1=0.0,
        duration=max(dt, horizon_s),
    )
    return spline.calc_point(dt)
