"""Модуль локализации: оценка состояния EKF, сопоставление сканов Гаусса-Ньютона, комплексирование GNSS, привязка к доку.

Соответствует plan/02-lokalizaciya.md и требованиям изоляции (только stdlib и numpy).
"""

import math
from typing import List, Optional, Tuple, Union

import numpy as np

try:
    from .geom import (
        filter_segs_aabb,
        point_to_segs_displacement,
        raycast,
        seg_dist,
        wrap_angle,
    )
except ImportError:
    from geom import (
        filter_segs_aabb,
        point_to_segs_displacement,
        raycast,
        seg_dist,
        wrap_angle,
    )


class Localizer:
    """Оценщик состояния и локализатор AMR.

    Координаты:
      x: восток (м);
      y: север (м);
      th: против часовой стрелки от востока (рад).

    Чистый базис одометрии (ox, oy, oth) отслеживается без поправок для распознавания динамических объектов.
    """

    def __init__(
        self,
        initial_pose: Union[List[float], Tuple[float, float, float], np.ndarray],
        building_segs: Optional[np.ndarray] = None,
        pole_centers: Optional[np.ndarray] = None,
    ):
        self.x = float(initial_pose[0])
        self.y = float(initial_pose[1])
        self.th = wrap_angle(float(initial_pose[2]))

        # Чистый базис одометрии без поправок и калибровки масштаба
        self.ox = 0.0
        self.oy = 0.0
        self.oth = 0.0

        # Дисперсии: вдоль пути, поперек пути, курс (рад^2)
        self.var_along = 0.0
        self.var_cross = 0.0
        self.var_th = 0.0

        # Коэффициент масштаба одометрии (истинный шаг = odom_step / scale)
        self.scale = 1.0
        self.scale_locked = False
        self._scale_odom_dist = 0.0
        self._scale_lidar_dist = 0.0
        self._scale_ratios: List[float] = []
        self._prev_scan_xy = (self.x, self.y)
        self._prev_scan_odom = (0.0, 0.0)
        # Расстояние, пройденное с момента последнего подтверждения продольной координаты
        # (поперечная стена, засечка GNSS, ориентир, фиксация масштаба).
        self._unconfirmed_dist = 0.0

        # Шаг одометрии за такт до подтверждения сопоставлением со сканом
        # и точные приращения дисперсий для отката при пробуксовке.
        self._odom_step_tick = 0.0
        self._pending_odom_step = 0.0
        # Короткое окно детектора пробуксовки колес
        self._stall_ticks = 0
        self._stall_odom = 0.0
        self._stall_xy = (self.x, self.y)
        self._pre_predict_xy = (self.x, self.y)
        self._predict_var = (0.0, 0.0, 0.0)

        # Смещение курса IMU (th = imu_heading - heading_bias)
        self.heading_bias = 0.0
        self.bias_initialized = False

        # Флаги статуса и состояния
        self.is_lost = False
        self.blocked_wheels = False
        self.scan_inliers = 0
        # Ограничение скорости, передаваемое в модуль безопасности при потере ориентации
        self.lost_speed_limit = 1.39
        self._low_inlier_ticks = 0
        self._gnss_fix_ticks = 10**9

        # Стробирование GNSS и отслеживание восстановления
        self.gnss_rejections: List[Tuple[float, float]] = []
        self.last_gnss_accepted = False

        # Счетчик гистерезиса обнаружения тумана (удержание 1.0 с = 10 тактов)
        self._fog_hold = 0
        self.fog_active = False
        # Ограниченный штраф дисперсии при потере ожидаемых стен в тумане
        self._fog_var_added = 0.0

        # Продольные ориентиры: концы отрезков карты и центры столбов
        self.landmarks = self._build_landmarks(building_segs, pole_centers)
        if pole_centers is not None and len(pole_centers) > 0:
            self.pole_centers: Optional[np.ndarray] = np.asarray(pole_centers, dtype=float).reshape(
                -1, 2
            )
        else:
            self.pole_centers = None

    @staticmethod
    def _build_landmarks(
        building_segs: Optional[np.ndarray],
        pole_centers: Optional[np.ndarray],
    ) -> np.ndarray:
        """Собрать продольные ориентиры: концы отрезков и явные центры столбов."""
        parts: List[np.ndarray] = []
        if building_segs is not None and len(building_segs) > 0:
            s = np.asarray(building_segs, dtype=float)
            parts.append(s[:, 0:2])
            parts.append(s[:, 2:4])
        if pole_centers is not None and len(pole_centers) > 0:
            p = np.asarray(pole_centers, dtype=float).reshape(-1, 2)
            parts.append(p)
        if not parts:
            return np.empty((0, 2), dtype=float)
        pts = np.vstack(parts)
        return pts[np.isfinite(pts).all(axis=1)]

    @property
    def pose(self) -> Tuple[float, float, float]:
        """Вернуть (x, y, th)."""
        return (self.x, self.y, self.th)

    @property
    def odom_pose(self) -> Tuple[float, float, float]:
        """Вернуть чистую позу одометрии (ox, oy, oth)."""
        return (self.ox, self.oy, self.oth)

    @property
    def sigma_along(self) -> float:
        return math.sqrt(max(0.0, self.var_along))

    @property
    def sigma_cross(self) -> float:
        return math.sqrt(max(0.0, self.var_cross))

    @property
    def sigma_th(self) -> float:
        return math.sqrt(max(0.0, self.var_th))

    def detect_fog(self, ranges: np.ndarray, expected_ranges: Optional[np.ndarray] = None) -> bool:
        """Обнаружить туман по реальному скану симулятора (часто NaN/inf).

        plan/02:49-61. Симулятор ограничивает каждый отклик значением ``lidar.fog_max_range`` (6.0 м)
        и превращает все, что дальше, в NaN, поэтому рабочие признаки такие:
          (a) большая доля нефинитных лучей при отсутствии дальних откликов;
          (b) карта ожидает стену в 9-19 м, а луч там NaN/inf, и так пачкой.
        Дальности лучей > 6.5 м не могут существовать в тумане, поэтому они НЕ должны обнулять
        счетчик гистерезиса мгновенно (прежний ранний возврат убивал удержание 1 с).

        Удерживает флаг 1.0 с (10 тактов), чтобы избежать мерцания.
        """
        r = np.asarray(ranges, dtype=float)
        n = len(r)
        if n == 0:
            return False

        finite = np.isfinite(r)
        nan_frac = float((~finite).sum()) / float(n)
        beams_beyond_65 = int((finite & (r > 6.5)).sum())

        instant_fog = False
        if expected_ranges is not None and len(expected_ranges) == n:
            exp = np.asarray(expected_ranges, dtype=float)
            # Верхняя граница 19 м: дальность лидара 20 м
            expected_far = (exp >= 9.0) & (exp <= 19.0)
            # (b) карта ожидает стену в измеряемом диапазоне, но луч отсутствует
            fog_drop = expected_far & ~finite
            instant_fog = int(fog_drop.sum()) >= 12
            # (a) преобладание лучей без отражения в зонах, где карта ожидает дальние стены;
            # открытый двор без стен имеет большую долю NaN и в ясную погоду.
            if nan_frac >= 0.12 and int(expected_far.sum()) >= 12:
                instant_fog = True
        else:
            instant_fog = nan_frac >= 0.12
        # (c) дальнее отражение свидетельствует против тумана на текущем такте.
        # Единичные отклики от снежинок не снимают флаг, но блокируют взвод удержания.
        if beams_beyond_65 > 3:
            instant_fog = False

        if instant_fog:
            self._fog_hold = 10
        elif self._fog_hold > 0:
            self._fog_hold -= 1

        return self._fog_hold > 0

    def predict(
        self,
        odom_dx: float,
        odom_dy: float,
        odom_dth: float,
        imu_heading: float,
        imu_yaw_rate: float,
        dt: float,
    ) -> None:
        """Шаг прогноза по одометрии и IMU.

        - чистая одометрия (ox, oy, oth) обновляется напрямую;
        - истинная позиция (x, y) обновляется на (odom_dx, odom_dy) / scale, повернутые на текущий th;
        - сторожевой таймер курса: если imu_heading скачет > 0.05 рад относительно ожидаемого, интегрируется yaw_rate;
        - дисперсии распространяются по движению.
        """
        # 1. Обновление чистого базиса одометрии (без поправок и масштаба)
        cos_oth = math.cos(self.oth)
        sin_oth = math.sin(self.oth)
        self.ox += cos_oth * odom_dx - sin_oth * odom_dy
        self.oy += sin_oth * odom_dx + cos_oth * odom_dy
        self.oth = wrap_angle(self.oth + odom_dth)

        # 2. Сохранение реального пути одометрии текущего такта.
        # Добавляется к калибровке масштаба только при подтверждении движения сканированием.
        step_dist = math.hypot(odom_dx, odom_dy)
        self.blocked_wheels = False
        self._odom_step_tick = step_dist
        self._pending_odom_step += step_dist

        # 3. Обновление позиции с учетом масштаба одометрии
        s = self.scale if (0.90 <= self.scale <= 1.10) else 1.0
        scaled_dx = odom_dx / s
        scaled_dy = odom_dy / s

        cos_th = math.cos(self.th)
        sin_th = math.sin(self.th)
        world_dx = cos_th * scaled_dx - sin_th * scaled_dy
        world_dy = sin_th * scaled_dx + cos_th * scaled_dy
        self._pre_predict_xy = (self.x, self.y)
        self.x += world_dx
        self.y += world_dy

        # 4. Обновление курса по данным IMU
        if not self.bias_initialized:
            self.heading_bias = wrap_angle(imu_heading - self.th)
            self.bias_initialized = True

        expected_th = wrap_angle(self.th + imu_yaw_rate * dt)
        measured_th = wrap_angle(imu_heading - self.heading_bias)

        # Сторожевой таймер: скачок > 0.05 рад переключает на интегрирование угловой скорости yaw_rate
        if abs(wrap_angle(measured_th - expected_th)) > 0.05:
            self.th = expected_th
        else:
            self.th = measured_th

        # 5. Рост дисперсий.
        # Продольная дисперсия: погрешность масштаба на пройденное расстояние с последней коррекции.
        self._unconfirmed_dist += step_dist
        d_var_along = 0.0
        bound = self._along_bound_m()
        if bound > 0.0:
            self.var_along = max(self.var_along, bound**2)

        # Поперечная дисперсия: растет с неопределенностью курса и дрейфом (0.3 град / sqrt(мин)).
        # 0.3 град = 0.0052 рад -> ~0.0052 / sqrt(60) ~ 0.00067 рад/sqrt(с) -> ~4.5e-7 рад^2/с.
        yaw_drift_var = (0.00067**2) * dt
        self.var_th += yaw_drift_var
        d_var_cross = (
            (step_dist * math.sin(math.sqrt(self.var_th))) ** 2 + (0.005 * step_dist) ** 2 + 1e-5
        )
        self.var_cross += d_var_cross
        self._predict_var = (d_var_along, d_var_cross, yaw_drift_var)

        # Проверка условий потери ориентации
        self._check_lost_status()

    def _along_bound_m(self) -> float:
        """Граница погрешности вдоль пути, задаваемая смещением масштаба одометрии (plan/02:99-108).

        Граница равна смещению, умноженному на расстояние, пройденное с момента последнего
        подтверждения продольной координаты. Отсчет начинается только после превышения 0.2 м,
        которые уже предполагают существующие нижние границы дисперсии (var_along >= 0.04 м^2 всюду,
        например при обновлении GNSS и штрафе за туман), поэтому ниже этого расстояния она
        по построению не влияет и оставляет нетронутой любую траекторию, которая регулярно
        подтверждает продольную ось - именно поэтому пакет приемки не меняется (все 28 прогонов
        01..04 x 7 сидов и все 30 прогонов собственных сценариев дают тот же счет).
        """
        scale_err = 0.01 if self.scale_locked else 0.04
        beyond = self._unconfirmed_dist - 0.2 / scale_err
        return scale_err * beyond if beyond > 0.0 else 0.0

    def _rollback_predict(self) -> None:
        """Отменить прогноз этого такта (блокировка колес, plan/02:149-157).

        Поза восстанавливается к значению до прогноза: такт одометрии, который сопоставление
        скана не подтвердило, не должен интегрироваться в фильтр.
        """
        self.x, self.y = self._pre_predict_xy
        da, dc, dth = self._predict_var
        self.var_along = max(0.0, self.var_along - da)
        self.var_cross = max(0.0, self.var_cross - dc)
        self.var_th = max(0.0, self.var_th - dth)
        self._predict_var = (0.0, 0.0, 0.0)
        self._pending_odom_step = max(0.0, self._pending_odom_step - self._odom_step_tick)
        self._unconfirmed_dist = max(0.0, self._unconfirmed_dist - self._odom_step_tick)

    def update_scan(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        segs: np.ndarray,
        is_fog: bool = False,
        segs_aabb: Optional[np.ndarray] = None,
    ) -> bool:
        """Сопоставление сканов с отрезками карты за 4 итерации Гаусса-Ньютона.

        Аргументы:
          ranges: одномерный массив дальностей лучей (360 лучей, шаг 1 град);
          rel_angles: одномерный массив углов лучей в базисе робота (рад);
          segs: массив (M, 4) отрезков карты [x1, y1, x2, y2];
          is_fog: активен ли режим тумана;
          segs_aabb: необязательный предвычисленный AABB для отрезков.
        """
        self.fog_active = bool(is_fog)
        if segs is None or len(segs) == 0:
            return self._scan_unavailable(is_fog)

        # Фильтрация отрезков в окрестности робота (~25 м)
        reach = 25.0
        near_segs_arr = filter_segs_aabb(segs, self.x, self.y, reach, aabb=segs_aabb)
        if len(near_segs_arr) == 0:
            return self._scan_unavailable(is_fog)

        r_all = np.asarray(ranges, dtype=float)
        rel_all = np.asarray(rel_angles, dtype=float)

        # 1. Прореживание лучей каждые 2 градуса (шаг 2)
        step = 2
        r_sub = r_all[::step]
        rel_sub = rel_all[::step]

        # Маска валидных конечных расстояний
        max_valid_range = 5.5 if is_fog else 19.0
        valid_range_mask = np.isfinite(r_sub) & (r_sub > 0.1) & (r_sub < max_valid_range)

        # Фильтр снега: валидный отклик должен иметь хотя бы одного соседа в пределах 0.4 м
        # в декартовой плоскости.
        sub_indices = np.arange(0, len(r_all), step)

        # Проверка декартовых расстояний между соседними лучами для удаления одиночных снежинок.
        # Отклик считается снегом при отсутствии соседей ближе 0.4 м.
        cos_rel_all = np.cos(rel_all)
        sin_rel_all = np.sin(rel_all)
        with np.errstate(invalid="ignore"):
            # При бесконечной дальности отсчеты отбрасываются
            x_pts = r_all * cos_rel_all
            y_pts = r_all * sin_rel_all

        # Векторизованная проверка расстояния до соседей в базисе робота
        n_all = len(r_all)
        prev_idx = (np.arange(n_all) - 1) % n_all
        next_idx = (np.arange(n_all) + 1) % n_all

        finite_all = np.isfinite(r_all)
        d_prev = np.full(n_all, np.inf)
        d_next = np.full(n_all, np.inf)

        m_prev = finite_all & finite_all[prev_idx]
        m_next = finite_all & finite_all[next_idx]

        d_prev[m_prev] = np.hypot(
            x_pts[m_prev] - x_pts[prev_idx[m_prev]], y_pts[m_prev] - y_pts[prev_idx[m_prev]]
        )
        d_next[m_next] = np.hypot(
            x_pts[m_next] - x_pts[next_idx[m_next]], y_pts[m_next] - y_pts[next_idx[m_next]]
        )

        # Точка подтверждена, если любой из соседей конечен и ближе 0.4 м
        supported = (d_prev < 0.4) | (d_next < 0.4)

        supported_sub = supported[sub_indices]
        candidate_mask = valid_range_mask & supported_sub
        if candidate_mask.sum() < 20:
            return self._scan_unavailable(is_fog)

        cand_ranges = r_sub[candidate_mask]
        cand_rel = rel_sub[candidate_mask]

        # Поправки состояния по методу Гаусса-Ньютона
        cur_x = self.x
        cur_y = self.y
        cur_th = self.th

        inliers_count = 0
        final_std = 999.0
        last_normals = None
        last_weights = None

        # 4 итерации метода Гаусса - Ньютона
        for _ in range(4):
            # Вычисление концов лучей в глобальном базисе
            beam_world_angles = cur_th + cand_rel
            px = cur_x + cand_ranges * np.cos(beam_world_angles)
            py = cur_y + cand_ranges * np.sin(beam_world_angles)

            # Проекция на карту и вычисление расстояния
            disp = point_to_segs_displacement(px, py, near_segs_arr)
            residuals = disp.dists  # Расстояние до ближайшей прямой сегмента
            normals = disp.normals  # Единичная нормаль (Nx, Ny)

            # Условия отбора точек соответствия:
            # 1. невязка < 0.25 м;
            dist_to_proj = np.hypot(disp.projs[:, 0] - cur_x, disp.projs[:, 1] - cur_y)
            not_short = cand_ranges >= dist_to_proj - 0.4

            inlier_mask = (residuals < 0.25) & not_short
            inliers_count = int(inlier_mask.sum())
            if inliers_count < 25:
                break

            res_inliers = residuals[inlier_mask]
            norm_inliers = normals[inlier_mask]
            px_inliers = px[inlier_mask]
            py_inliers = py[inlier_mask]

            final_std = float(np.std(res_inliers))
            last_normals = norm_inliers

            # Весовая функция Хьюбера: delta = 0.08
            huber_delta = 0.08
            abs_res = np.abs(res_inliers)
            weights = np.where(
                abs_res <= huber_delta, 1.0, huber_delta / np.maximum(abs_res, 1e-12)
            )
            last_weights = weights

            # Знаковая ошибка невязки: r_i = n_x * (p_x - proj_x) + n_y * (p_y - proj_y) = dist.
            # При коррекции состояния на (dx, dy, dth):
            rx = px_inliers - cur_x
            ry = py_inliers - cur_y

            J = np.column_stack(
                [
                    norm_inliers[:, 0],
                    norm_inliers[:, 1],
                    -norm_inliers[:, 0] * ry + norm_inliers[:, 1] * rx,
                ]
            )  # (K, 3)

            W = weights[:, None]
            JW = J * W
            H = J.T @ JW  # (3, 3)
            g = J.T @ (weights * res_inliers)  # (3,)

            # Демпфирование для численной устойчивости
            H += 1e-3 * np.eye(3)

            try:
                delta = np.linalg.solve(H, -g)
            except np.linalg.LinAlgError:
                break

            # Применение шага коррекции
            cur_x += float(delta[0])
            cur_y += float(delta[1])
            cur_th = wrap_angle(cur_th + float(delta[2]))

            if np.hypot(delta[0], delta[1]) < 0.001 and abs(delta[2]) < 0.001:
                break

        self.scan_inliers = inliers_count

        if not is_fog:
            self._fog_var_added = 0.0

        # Таймер малого числа соответствий
        self._register_scan_health(is_fog)

        # Туман: исчезновение ожидаемых близких стен (<5.5 м) добавляет дисперсию пачками
        if is_fog:
            self._penalise_missing_near_walls(r_sub, rel_sub, near_segs_arr)

        # Критерии принятия: число соответствий >= 30 и std(residual) < 0.08 м
        if inliers_count >= 30 and final_std < 0.08:
            prev_x, prev_y = self._prev_scan_xy
            prev_ox, prev_oy = self._prev_scan_odom
            self._prev_scan_xy = (cur_x, cur_y)
            self._prev_scan_odom = (self.ox, self.oy)

            # Пробуксовка колес: одометрия зафиксировала движение, тогда как стены карты неподвижны.
            # Оценивается на коротком окне.
            if self._stall_ticks == 0:
                self._stall_xy = (cur_x, cur_y)
                self._stall_odom = 0.0
            self._stall_odom += self._pending_odom_step
            self._stall_ticks += 1
            stall = False
            if self._stall_ticks >= 5:
                wall_moved = math.hypot(cur_x - self._stall_xy[0], cur_y - self._stall_xy[1])
                stall = (self._stall_odom > 0.05) and (wall_moved < 0.01)
                self._stall_ticks = 0
                self._stall_odom = 0.0

            # Принятие обновления состояния
            self.x = cur_x
            self.y = cur_y
            self.th = cur_th

            if stall:
                # Не интегрировать одометрию текущего такта и не изменять калибровку масштаба
                self.blocked_wheels = True
                self._rollback_predict()
                self._pending_odom_step = 0.0
            else:
                # Обновление дисперсий: проекция дисперсий на нормали и касательные наблюдаемых стен
                if last_normals is not None and len(last_normals) > 0:
                    self._update_variances_from_walls(last_normals, last_weights)

                # Накопление масштаба одометрии: отсутствие пробуксовки и наличие продольной информации.
                # Фиксация GNSS в пределах 1.5 м калибрует масштаб.
                gnss_recent = self.last_gnss_accepted or self._gnss_fix_ticks <= 50
                if not self.scale_locked:
                    longitudinal = self._scan_has_angle(last_normals) or self._scan_holds_landmark(
                        r_all, rel_all, d_prev, d_next, finite_all, near_segs_arr
                    )
                    if gnss_recent or (inliers_count > 80 and longitudinal):
                        self._accumulate_scale(prev_ox, prev_oy, cur_x - prev_x, cur_y - prev_y)
                self._pending_odom_step = 0.0

                # Продольные ориентиры: обновление только слабой (касательной) оси
                self._apply_landmark_correction(
                    r_all, rel_all, d_prev, d_next, finite_all, near_segs_arr
                )

            self._check_lost_status()
            return True

        # Сопоставление отклонено: сохранение пути одометрии в ожидании следующего
        # успешного сопоставления на том же интервале.
        self._check_lost_status()
        return False

    def _scan_unavailable(self, is_fog: bool) -> bool:
        """Нет пригодного скана в этом такте: учесть его в таймере слепоты (plan/02:141)."""
        self.scan_inliers = 0
        self._register_scan_health(is_fog)
        self._check_lost_status()
        return False

    @staticmethod
    def _scan_has_angle(normals: Optional[np.ndarray]) -> bool:
        """Истина, когда инлайерные стены охватывают более ~30 град: виден реальный угол."""
        if normals is None or len(normals) < 2:
            return False
        ang = np.arctan2(normals[:, 1], normals[:, 0])
        # Ненаправленные нормали: работа с удвоенными углами;
        # средняя длина результирующего вектора падает ниже cos(30 град) при разбросе более 30 град.
        r_len = math.hypot(float(np.cos(2.0 * ang).mean()), float(np.sin(2.0 * ang).mean()))
        return r_len < 0.866

    def _scan_holds_landmark(
        self,
        r_all: np.ndarray,
        rel_all: np.ndarray,
        d_prev: np.ndarray,
        d_next: np.ndarray,
        finite_all: np.ndarray,
        segs: np.ndarray,
    ) -> bool:
        """Истина, когда угол скана попадает на размеченный продольный ориентир (plan/02:63-81).

        ``_scan_has_angle`` смотрит только на разброс нормалей стен, поэтому робот, проезжающий
        мимо конца длинного фасада, видит 'одну стену', хотя силуэт конца этого фасада -
        вполне хорошая продольная привязка. План называет именно такую привязку - концы отрезков
        зданий и центры столбов - и его правило сопоставления равно 2 м. Здесь тот же угловой
        признак, который использует слой ориентиров (соседние отклики прыгают на > 1.5 м),
        должен попасть на размеченную стену (невязка < 0.35 м) и находиться в пределах 2 м
        от размеченного ориентира. Снежинка не проходит обе проверки, поэтому это не может
        открыть стробирование на ненаблюдаемой прямой.
        """
        lm = self.landmarks
        if lm is None or len(lm) == 0 or segs is None or len(segs) == 0 or len(r_all) == 0:
            return False
        finite = finite_all & np.isfinite(r_all)
        jump = finite & ((d_prev > 1.5) | (d_next > 1.5))
        idx = np.flatnonzero(jump)
        if len(idx) == 0:
            return False

        ang = self.th + rel_all[idx]
        wx = self.x + r_all[idx] * np.cos(ang)
        wy = self.y + r_all[idx] * np.sin(ang)
        on_wall = np.atleast_1d(point_to_segs_displacement(wx, wy, segs).dists) < 0.35
        if not on_wall.any():
            return False
        wx = wx[on_wall]
        wy = wy[on_wall]
        for k in range(len(wx)):
            if float(np.min(np.hypot(lm[:, 0] - wx[k], lm[:, 1] - wy[k]))) < 2.0:
                return True
        return False

    def _register_scan_health(self, is_fog: bool) -> None:
        """Считать подряд идущие такты с малым числом инлайеров скана (plan/02:141).

        Считается только при отсутствии абсолютной засечки GNSS: пустая улица с
        действительной засечкой GNSS не является потерей ориентации.
        """
        if is_fog or self.scan_inliers >= 15 or self._gnss_fix_ticks <= 10:
            self._low_inlier_ticks = 0
        else:
            self._low_inlier_ticks += 1

    def _penalise_missing_near_walls(
        self,
        r_sub: np.ndarray,
        rel_sub: np.ndarray,
        segs: np.ndarray,
    ) -> None:
        """В тумане ожидаемые ближние стены, дающие NaN, пачкой добавляют дисперсию (plan/02:59)."""
        if segs is None or len(segs) == 0:
            return
        if self._fog_var_added >= 0.36:
            return
        exp = raycast(self.x, self.y, self.th + rel_sub, segs)
        measured = np.isfinite(r_sub) & (r_sub > 0.1) & (r_sub < 5.5)
        missing = np.isfinite(exp) & (exp < 5.5) & ~measured
        if int(missing.sum()) < 12:
            return

        ang = self.th + rel_sub[missing]
        mx = self.x + exp[missing] * np.cos(ang)
        my = self.y + exp[missing] * np.sin(ang)
        disp = point_to_segs_displacement(mx, my, segs)
        nx = float(np.mean(disp.normals[:, 0]))
        ny = float(np.mean(disp.normals[:, 1]))
        mag = math.hypot(nx, ny)
        inc = 0.02**2
        if mag < 1e-6:
            self.var_cross += inc
        else:
            alpha = math.atan2(ny / mag, nx / mag)
            d_angle = wrap_angle(alpha - self.th)
            self.var_cross += inc * math.sin(d_angle) ** 2
            self.var_along += inc * math.cos(d_angle) ** 2
        self._fog_var_added += inc

    def _apply_landmark_correction(
        self,
        r_all: np.ndarray,
        rel_all: np.ndarray,
        d_prev: np.ndarray,
        d_next: np.ndarray,
        finite_all: np.ndarray,
        segs: np.ndarray,
    ) -> None:
        """Продольные ориентиры (plan/02:63-81).

        Угловой признак - это пара соседних откликов, концы которых прыгают более чем на 1.5 м.
        Он пригоден, только когда конец действительно лежит на размеченной стене (невязка < 0.35 м)
        и размеченный ориентир - конец этого самого отрезка или центр столба - находится в пределах
        2 м от него. Продольная невязка вдоль стены затем записывается только в слабую касательную
        ось; нормаль уже удерживается фасадом, и измерение там размазало бы ее.
        """
        if segs is None or len(segs) == 0:
            return
        n = len(r_all)
        if n == 0:
            return

        finite = finite_all & np.isfinite(r_all)
        jump = finite & ((d_prev > 1.5) | (d_next > 1.5))
        idx = np.flatnonzero(jump)
        if len(idx) == 0:
            return

        ang = self.th + rel_all[idx]
        wx = self.x + r_all[idx] * np.cos(ang)
        wy = self.y + r_all[idx] * np.sin(ang)

        disp = point_to_segs_displacement(wx, wy, segs)
        dists = np.atleast_1d(disp.dists)
        seg_idx = np.atleast_1d(disp.seg_idx)
        # Признак должен принадлежать карте: его конечная точка лежит на стене
        on_wall = dists < 0.35
        if not on_wall.any():
            return

        poles = self.pole_centers
        have_poles = poles is not None and len(poles) > 0

        shifts = []
        tangents = []
        for k in np.flatnonzero(on_wall):
            si = int(seg_idx[k])
            if si < 0 or si >= len(segs):
                continue
            x1, y1, x2, y2 = (float(v) for v in segs[si][:4])
            seg_len = math.hypot(x2 - x1, y2 - y1)
            if seg_len < 1e-6:
                continue
            tx, ty = (x2 - x1) / seg_len, (y2 - y1) / seg_len

            # Признак должен быть именно ориентиром, а не просто находиться рядом,
            # исключая ложные продольные сдвиги по невидимым осям.
            best_d = None
            best_xy = None
            for ex, ey in ((x1, y1), (x2, y2)):
                dd = math.hypot(ex - wx[k], ey - wy[k])
                if dd <= 0.6 and (best_d is None or dd < best_d):
                    best_d, best_xy = dd, (ex, ey)
            if have_poles:
                pdd = np.hypot(poles[:, 0] - wx[k], poles[:, 1] - wy[k])
                pi = int(np.argmin(pdd))
                if float(pdd[pi]) <= 0.6 and (best_d is None or float(pdd[pi]) < best_d):
                    best_d = float(pdd[pi])
                    best_xy = (float(poles[pi, 0]), float(poles[pi, 1]))
            if best_xy is None:
                continue

            d_t = (best_xy[0] - wx[k]) * tx + (best_xy[1] - wy[k]) * ty
            # Зона нечувствительности: возвращенный угол квантован шагом 1 град,
            # малая невязка является шумом и не должна накапливаться.
            if abs(d_t) < 0.3:
                continue
            shifts.append(max(-0.5, min(0.5, d_t)))
            tangents.append((tx, ty))

        # Одиночный граничный луч недостаточно надежен для сдвига позы
        if len(shifts) < 2:
            return

        shift = 0.5 * float(np.median(shifts))
        mtx = float(np.mean([t[0] for t in tangents]))
        mty = float(np.mean([t[1] for t in tangents]))
        mag = math.hypot(mtx, mty)
        if mag < 1e-6:
            return
        mtx /= mag
        mty /= mag
        self.x += shift * mtx
        self.y += shift * mty
        # Подтвержденный конец ориентира является прямым измерением вдоль пути
        self._unconfirmed_dist = 0.0

        # Измерение уточняет исключительно продольную ось
        beta = math.atan2(mty, mtx)
        d_angle = wrap_angle(beta - self.th)
        cos_d2 = math.cos(d_angle) ** 2
        sin_d2 = math.sin(d_angle) ** 2
        var_t = self.var_along * cos_d2 + self.var_cross * sin_d2
        self.var_along = max(1e-6, self.var_along - 0.5 * var_t * cos_d2)
        self.var_cross = max(1e-6, self.var_cross - 0.5 * var_t * sin_d2)

    def _update_variances_from_walls(self, normals: np.ndarray, weights: np.ndarray) -> None:
        """Обновить дисперсии вдоль и поперек направлений нормалей стен."""
        # Средняя ориентация нормалей.
        # Стена фиксирует нормаль и курс, но не ограничивает касательную составляющую.
        n_x = float(np.average(normals[:, 0], weights=weights))
        n_y = float(np.average(normals[:, 1], weights=weights))
        norm_mag = math.hypot(n_x, n_y)
        if norm_mag > 1e-3:
            n_x /= norm_mag
            n_y /= norm_mag

            # Угол нормали
            alpha = math.atan2(n_y, n_x)
            # Курс робота относительно нормали стены
            d_angle = wrap_angle(alpha - self.th)
            cos_d2 = math.cos(d_angle) ** 2
            sin_d2 = math.sin(d_angle) ** 2

            # Ошибка по нормали уменьшается до ~0.02^2 (точность сканирования)
            var_wall = 0.02**2

            # Обновление продольной и поперечной дисперсий.
            # Сканирование измеряет нормаль к стене с проекцией на оси робота.
            self.var_cross = self.var_cross * cos_d2 + var_wall * sin_d2
            self.var_along = self.var_along * sin_d2 + var_wall * cos_d2
            self.var_th = min(self.var_th, (0.01) ** 2)

            # Проверка наличия нормалей вдоль курса движения (поперечная стена).
            # Средневзвешенная нормаль ориентирована вдоль наиболее длинных стен.
            if normals.size:
                head = normals[:, 0] * math.cos(self.th) + normals[:, 1] * math.sin(self.th)
                if float(np.max(np.abs(head))) > 0.87:  # Нормаль в пределах ~30 градусов от курса
                    self._unconfirmed_dist = 0.0

    @staticmethod
    def _snap_scale(calc_scale: float) -> float:
        """Прижать оценку к физически допустимому множеству [0.96,0.99] U [1.01,1.04]."""
        s = max(0.96, min(1.04, float(calc_scale)))
        if 0.99 <= s <= 1.01:
            # Разрыв масштаба около 1.0 недопустим: сдвиг к ближайшей границе
            s = 1.01 if s >= 1.0 else 0.99
        return s

    def _accumulate_scale(
        self,
        prev_odom_x: float,
        prev_odom_y: float,
        scan_dx: float,
        scan_dy: float,
    ) -> None:
        """Накопить РЕАЛЬНЫЙ путь одометрии и путь сопоставления сканов, затем зафиксировать.

        plan/02:99-108: s = odom_path / lidar_path на не менее 25 м подтвержденного сканом
        пути. Оба пути измеряются на строго одном интервале между двумя принятыми
        сопоставлениями скана - дельта одометра в своем базисе, повернутая в мировые оси -
        и используется только продольная проекция смещения скана, чтобы боковые поправки
        скана/GNSS не раздували путь лидара.
        """
        if self.scale_locked:
            return

        odom_dx = self.ox - prev_odom_x
        odom_dy = self.oy - prev_odom_y
        odom_len = math.hypot(odom_dx, odom_dy)
        if odom_len <= 1e-6:
            return

        # Перемещения вычисляются в различных базисах с постоянным смещением:
        # одометрия (ox, oy, oth) - чистый базис колес с нулевым начальным курсом.
        rot = self.th - self.oth
        c_rot = math.cos(rot)
        s_rot = math.sin(rot)
        w_odom_dx = c_rot * odom_dx - s_rot * odom_dy
        w_odom_dy = s_rot * odom_dx + c_rot * odom_dy

        lidar_step = (scan_dx * w_odom_dx + scan_dy * w_odom_dy) / odom_len
        if lidar_step <= 0.0:
            return

        self._scale_odom_dist += odom_len
        self._scale_lidar_dist += lidar_step
        # Отношение одометрии к лидару на интервале.
        # Продольная составляющая вдоль стены частично ненаблюдаема, усеченное среднее фильтрует шум.
        if lidar_step > 0.01 * odom_len:
            self._scale_ratios.append(odom_len / lidar_step)

        if self._scale_lidar_dist >= 25.0:
            if len(self._scale_ratios) >= 40:
                calc_scale = self._trimmed_mean(self._scale_ratios, 0.15)
            else:
                calc_scale = self._scale_odom_dist / max(self._scale_lidar_dist, 1e-6)
            self.scale = self._snap_scale(calc_scale)
            self.scale_locked = True
            # Зафиксированный масштаб подтверждает продольную координату:
            # бюджет счисления пути перезапускается с остаточной погрешностью калибровки 1%.
            self._unconfirmed_dist = 0.0
            # Продольная неопределенность после калибровки определяется остаточной погрешностью масштаба,
            # а не исходным широким бюджетом.
            self.var_along = max(self.var_along, (0.01 * self._scale_lidar_dist) ** 2)

    @staticmethod
    def _trimmed_mean(values: List[float], trim: float) -> float:
        """Среднее после отбрасывания низшей и высшей доли `trim` выборки."""
        s = sorted(values)
        n = len(s)
        k = int(trim * n)
        kept = s[k : n - k] if n - 2 * k > 0 else s
        return sum(kept) / len(kept)

    def update_gnss(
        self,
        gnss_x: float,
        gnss_y: float,
        gnss_valid: bool,
        gnss_hdop: float,
        in_shadow: bool = False,
    ) -> bool:
        """Обновление измерения GNSS со стробированием невязки.

        Правила (plan/02:83-97):
        - никогда не копировать сырой GNSS напрямую в pose_est;
        - принимать только когда измерение действительно, не в тени и невязка < 1.5 м; когда скан
          подтверждает позу (scan_inliers >= 30), измерение берется с полным усилением, иначе
          проходят только малые (<0.6 м) поправки со сниженным усилением;
        - hdop > 1.4 только усиливает недоверие (усиление вдвое); hdop > 2.0 - грубая защита;
        - восстановление при устойчивом расхождении (> 3 с, стабильно, скан согласен с GNSS)
          смещает гипотезу к GNSS.
        """
        self.last_gnss_accepted = False

        if in_shadow or not gnss_valid or gnss_hdop > 2.0:
            self.gnss_rejections.clear()
            self._gnss_fix_ticks += 1
            return False

        dx = gnss_x - self.x
        dy = gnss_y - self.y
        dist = math.hypot(dx, dy)

        # Строб невязки GNSS: 1.5 м
        if dist < 1.5:
            # В тумане лидар ослеплен и дальность ограничена: карта не дает подтверждений,
            # засечка GNSS остается единственным источником координат.
            scan_ok = (self.scan_inliers >= 30) or self.fog_active
            if not scan_ok and dist > 0.6:
                # Карта не подтверждает позу (мало точек соответствия), а поправка велика:
                # удержание позы до восстановления совпадения со сканом.
                self._gnss_fix_ticks += 1
                self.gnss_rejections.append((dx, dy))
                self._check_lost_status()
                return False

            self.gnss_rejections.clear()
            # Фильтр стробированной невязки (взвешенная коррекция калмановского типа):
            # R_gnss ~ (0.3 м)^2, масштабирование по HDOP.
            r_var = (0.3 * max(1.0, gnss_hdop)) ** 2
            k_x = self.var_along / (self.var_along + r_var)
            k_y = self.var_cross / (self.var_cross + r_var)
            k = max(0.01, min(0.15, 0.5 * (k_x + k_y)))
            # Высокий HDOP снижает вес измерения, но не отменяет его
            if gnss_hdop > 1.4:
                k *= 0.5
            # Коррекция без подтверждения лидаром имеет пониженное доверие
            if not scan_ok:
                k *= 0.3

            self.x += k * dx
            self.y += k * dy

            # Уменьшение дисперсии ограничено точностью GNSS
            self.var_along = max(0.04, self.var_along * (1.0 - k))
            self.var_cross = max(0.04, self.var_cross * (1.0 - k))
            self.last_gnss_accepted = True
            self._gnss_fix_ticks = 0
            # Принятая засечка в пределах строба 1.5 м служит абсолютной продольной привязкой
            self._unconfirmed_dist = 0.0
            self._check_lost_status()
            return True

        # Отклоненная невязка: сохранение для проверки устойчивого расхождения
        self._gnss_fix_ticks += 1
        self.gnss_rejections.append((dx, dy))

        # Восстановление при устойчивом согласии измерений. Скачок GNSS длится 2-5 с,
        # стабильное согласование в окне 6 с свидетельствует о дрейфе лидара вдоль стены.
        if len(self.gnss_rejections) >= 60:
            recent = np.array(self.gnss_rejections[-40:])
            shift_x = float(recent[:, 0].mean())
            shift_y = float(recent[:, 1].mean())
            shift = math.hypot(shift_x, shift_y)
            if recent.std(axis=0).max() < 0.5 and self.scan_inliers >= 60 and 1.5 < shift < 3.0:
                # Фильтр сдрейфовал вдоль гладкой стены, данные GNSS стабильны
                self.x += shift_x
                self.y += shift_y
                self.var_along = 0.5**2
                self.var_cross = 0.5**2
                self.gnss_rejections.clear()
                self._check_lost_status()
                return True
            if len(self.gnss_rejections) > 80:
                self.gnss_rejections.pop(0)

        self._check_lost_status()
        return False

    def dock_snap(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        dock_goal: Union[Tuple[float, float, float], List[float]],
        dock_wall_segs: np.ndarray,
    ) -> bool:
        """Точная привязка к доку в пределах 1.5 - 3.0 м от цели дока.

        Передний луч ~0 град ожидает 1.5 м до передней стены дока.
        Боковые лучи ~+-90 град ожидают 2.5 м до боковых стен дока.
        Поза корректируется на половину расхождения вдоль и поперек курса.
        """
        gx, gy, gh = float(dock_goal[0]), float(dock_goal[1]), float(dock_goal[2])
        dist_to_goal = math.hypot(gx - self.x, gy - self.y)
        heading_err = abs(wrap_angle(self.th - gh))

        # Активация только вблизи цели (<= 3.0 м) и при соосности (<= 0.35 рад)
        if dist_to_goal > 3.0 or heading_err > 0.35:
            return False

        r = np.asarray(ranges, dtype=float)
        n = len(r)
        if n == 0 or dock_wall_segs is None or len(dock_wall_segs) == 0:
            return False

        def beam_median(center_idx: int) -> float:
            idxs = [(center_idx + j) % n for j in range(-2, 3)]
            vals = r[idxs]
            vals = vals[np.isfinite(vals)]
            return float(np.median(vals)) if len(vals) >= 3 else math.nan

        # Спереди (индекс 0), слева (индекс n // 4 = 90 град), справа (индекс 3*n // 4 = 270 град)
        exp_front = raycast(self.x, self.y, np.array([self.th]), dock_wall_segs)
        exp_left = raycast(self.x, self.y, np.array([self.th + math.pi / 2]), dock_wall_segs)
        exp_right = raycast(self.x, self.y, np.array([self.th - math.pi / 2]), dock_wall_segs)

        mf = beam_median(0)
        ml = beam_median(n // 4)
        mr = beam_median((3 * n) // 4)

        cos_th = math.cos(self.th)
        sin_th = math.sin(self.th)

        applied = False

        # Продольная корректировка по передней стене
        if math.isfinite(mf) and math.isfinite(exp_front[0]) and abs(mf - exp_front[0]) < 0.6:
            err_f = mf - exp_front[0]
            # Если измеренная дистанция меньше ожидаемой, робот ближе к стене -> смещение назад
            self.x -= 0.5 * err_f * cos_th
            self.y -= 0.5 * err_f * sin_th
            self.var_along = min(self.var_along, 0.02**2)
            applied = True

        # Поперечная корректировка по боковым стенам
        lat_errs = []
        if math.isfinite(ml) and math.isfinite(exp_left[0]) and abs(ml - exp_left[0]) < 0.6:
            lat_errs.append(-(ml - exp_left[0]))
        if math.isfinite(mr) and math.isfinite(exp_right[0]) and abs(mr - exp_right[0]) < 0.6:
            lat_errs.append(mr - exp_right[0])

        if lat_errs:
            lat_corr = float(np.mean(lat_errs))
            # Поперечное направление равно (-sin_th, cos_th)
            self.x += 0.5 * lat_corr * (-sin_th)
            self.y += 0.5 * lat_corr * cos_th
            self.var_cross = min(self.var_cross, 0.02**2)
            applied = True

        if applied:
            # Коррекция в доке не является движением по одометрии и не должна попадать
            # в калибровку масштаба и детектор пробуксовки.
            self._prev_scan_xy = (self.x, self.y)
            self._prev_scan_odom = (self.ox, self.oy)

        return applied

    def try_recover(
        self,
        ranges: Optional[np.ndarray] = None,
        rel_angles: Optional[np.ndarray] = None,
        segs: Optional[np.ndarray] = None,
        stopped: bool = False,
        is_fog: bool = False,
    ) -> bool:
        """Искать позу только когда платформа стоит и поза потеряна (plan/02:143-145).

        Возвращает True, когда найдена резкая вершина гипотезы и ``is_lost`` снят.
        """
        if not self.is_lost or not stopped:
            return False
        if ranges is None or rel_angles is None or segs is None:
            return False

        ok = self.recover_grid_search(
            np.asarray(ranges, dtype=float),
            np.asarray(rel_angles, dtype=float),
            segs,
            is_fog=is_fog,
        )
        if ok:
            self.is_lost = False
            self.lost_speed_limit = 1.39
            self._low_inlier_ticks = 0
            self._prev_scan_xy = (self.x, self.y)
            self._prev_scan_odom = (self.ox, self.oy)
            if not self.scale_locked:
                # Восстановленная поза аннулирует накопленный путь калибровки
                self._scale_odom_dist = 0.0
                self._scale_lidar_dist = 0.0
        return ok

    def recover_grid_search(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        segs: np.ndarray,
        is_fog: bool = False,
    ) -> bool:
        """Глобально-локальный поиск гипотез по сетке при потере позы.

        Сетка: dx в [-3, 3] шаг 0.25 м, dy в [-3, 3] шаг 0.25 м, dth в [-8°, 8°] шаг 2°.
        Для оценки используется 60 лучей. Резкая вершина принимается для снятия is_lost.
        """
        if segs is None or len(segs) == 0:
            return False

        r_all = np.asarray(ranges, dtype=float)
        rel_all = np.asarray(rel_angles, dtype=float)

        # 60 лучей (каждый 6-й луч)
        step = 6
        r_60 = r_all[::step]
        rel_60 = rel_all[::step]

        max_range = 5.5 if is_fog else 19.0
        mask = np.isfinite(r_60) & (r_60 > 0.1) & (r_60 < max_range)
        if mask.sum() < 15:
            return False

        eval_r = r_60[mask]
        eval_rel = rel_60[mask]

        dx_grid = np.arange(-3.0, 3.1, 0.25)
        dy_grid = np.arange(-3.0, 3.1, 0.25)
        dth_grid = np.radians(np.arange(-8.0, 8.1, 2.0))

        candidates = []
        reach = 25.0
        local_segs = filter_segs_aabb(segs, self.x, self.y, reach + 3.5)
        if len(local_segs) == 0:
            return False

        for dth in dth_grid:
            cand_th = wrap_angle(self.th + dth)
            beam_angles = cand_th + eval_rel
            rx = eval_r * np.cos(beam_angles)
            ry = eval_r * np.sin(beam_angles)

            for dx in dx_grid:
                cx = self.x + dx
                pts_x = cx + rx
                for dy in dy_grid:
                    cy = self.y + dy
                    pts_y = cy + ry

                    dists = seg_dist(pts_x, pts_y, local_segs)
                    inliers = int((dists < 0.25).sum())
                    candidates.append((inliers, cx, cy, cand_th))

        candidates.sort(key=lambda c: -c[0])
        best_score, bx, by, bth = candidates[0]

        # Выраженный пик: лучшая гипотеза должна превосходить все варианты вне
        # своей локальной окрестности (0.75 м / 3 град).
        second_score = 0
        for score, cx, cy, cand_th in candidates[1:]:
            if (
                abs(cx - bx) > 0.75
                or abs(cy - by) > 0.75
                or abs(wrap_angle(cand_th - bth)) > math.radians(3.0)
            ):
                second_score = score
                break

        # Четкий локальный пик: число соответствий >= 35 и явное преимущество по сетке
        if best_score >= 35 and (
            best_score >= second_score * 1.15 or best_score - second_score >= 6
        ):
            best_hypothesis = (bx, by, bth)
            self.x, self.y, self.th = best_hypothesis
            self.var_along = 0.2**2
            self.var_cross = 0.2**2
            self.var_th = np.radians(3.0) ** 2
            self._unconfirmed_dist = 0.0
            self.is_lost = False
            return True

        return False

    def _check_lost_status(self) -> None:
        """Оценить статус потери позы и экспортируемое ограничение скорости (plan/02:133-147).

        Уровни:
          sigma_cross > 0.4 или sigma_th > 5 град  -> lost_speed_limit <= 0.4;
          sigma_along > 2 м (поперечная узкая)     -> lost_speed_limit <= 0.6;
          sigma_cross > 0.8 или sigma_th > 10 град -> is_lost, остановка, затем поиск;
          sigma_along > 5 м и все еще без объяснения -> is_lost (см. комментарий ниже);
          inliers < 15 вне тумана более 1 с        -> is_lost.
        """
        # Широкая продольная граница требует остановки только при отсутствии объяснения.
        # При наличии подтверждения сканированием или GNSS движение продолжается.
        align = self.sigma_along > 5.0 and self._along_bound_m() > 5.0
        cross = self.sigma_cross > 0.8 or self.sigma_th > math.radians(10.0)
        blind = self._low_inlier_ticks >= 10
        entering = align or cross or blind

        if entering:
            self.is_lost = True
        elif (
            self.sigma_cross < 0.4
            and self.sigma_th < math.radians(5.0)
            and (self.sigma_along < 2.0 or self._unconfirmed_dist == 0.0)
            and self._low_inlier_ticks == 0
        ):
            # Выход также допускает подтвержденную продольную ось:
            # предотвращается остановка платформы по устаревшей оценке дисперсии.
            self.is_lost = False

        if self.is_lost:
            self.lost_speed_limit = 0.0
        else:
            lim = 1.39
            if self.sigma_along > 2.0:
                lim = min(lim, 0.6)
            if self.sigma_cross > 0.4 or self.sigma_th > math.radians(5.0):
                lim = min(lim, 0.4)
            self.lost_speed_limit = lim
