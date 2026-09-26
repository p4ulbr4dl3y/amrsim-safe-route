"""Класс Localizer: координатор подсистем локализации AMR.

Интегрирует:
- EKF фильтрацию и чистое счисление пути (ekf.py);
- сопоставление лидарных сканов со стенами и ориентирами (scan_matcher.py);
- комплексирование GNSS измерений (gnss.py);
- детектор тумана и пробуксовки колес;
- калибровку масштаба одометрии (25 м интервал, snap scale);
- точную привязку к доку (dock_snap);
- многоуровневый детектор потери позы (lost status).

Соответствует требованиям Т3 и Т5 (только stdlib и numpy, относительные импорты).
"""

import math
from typing import List, Optional, Tuple, Union

import numpy as np

try:
    from ..geom import raycast, wrap_angle
except (ImportError, ValueError):
    from geom import raycast, wrap_angle
from .ekf import EKFFilter
from .gnss import GNSSFilter
from .scan_matcher import ScanMatcher


class Localizer:
    """Оценщик состояния и локализатор AMR."""

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

        # Коэффициент масштаба одометрии
        self.scale = 1.0
        self.scale_locked = False
        self._scale_odom_dist = 0.0
        self._scale_lidar_dist = 0.0
        self._scale_ratios: List[float] = []
        self._prev_scan_xy = (self.x, self.y)
        self._prev_scan_odom = (0.0, 0.0)
        self._unconfirmed_dist = 0.0

        # Шаг одометрии за такт до подтверждения
        self._odom_step_tick = 0.0
        self._pending_odom_step = 0.0
        self._stall_ticks = 0
        self._stall_odom = 0.0
        self._stall_xy = (self.x, self.y)
        self._pre_predict_xy = (self.x, self.y)
        self._predict_var = (0.0, 0.0, 0.0)

        # Смещение курса IMU
        self.heading_bias = 0.0
        self.bias_initialized = False

        # Флаги статуса и состояния
        self.is_lost = False
        self.blocked_wheels = False
        self.scan_inliers = 0
        self.lost_speed_limit = 1.39
        self._low_inlier_ticks = 0

        # Детектор тумана
        self._fog_hold = 0
        self.fog_active = False
        self._fog_var_added = 0.0

        # Ориентиры
        self.landmarks = self._build_landmarks(building_segs, pole_centers)
        if pole_centers is not None and len(pole_centers) > 0:
            self.pole_centers: Optional[np.ndarray] = np.asarray(pole_centers, dtype=float).reshape(
                -1, 2
            )
        else:
            self.pole_centers = None

        # Внутренние подсистемы
        self._scan_matcher = ScanMatcher()
        self._gnss = GNSSFilter()
        self._ekf = EKFFilter()

    @property
    def gnss_rejections(self) -> List[Tuple[float, float]]:
        return self._gnss.rejections

    @gnss_rejections.setter
    def gnss_rejections(self, val: List[Tuple[float, float]]) -> None:
        self._gnss.rejections = list(val)

    @property
    def last_gnss_accepted(self) -> bool:
        return self._gnss.last_accepted

    @last_gnss_accepted.setter
    def last_gnss_accepted(self, val: bool) -> None:
        self._gnss.last_accepted = bool(val)

    @property
    def _gnss_fix_ticks(self) -> int:
        return self._gnss.fix_ticks

    @_gnss_fix_ticks.setter
    def _gnss_fix_ticks(self, val: int) -> None:
        self._gnss.fix_ticks = int(val)

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
        return (self.x, self.y, self.th)

    @property
    def odom_pose(self) -> Tuple[float, float, float]:
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
        """Обнаружить туман по реальному скану симулятора."""
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
            expected_far = (exp >= 9.0) & (exp <= 19.0)
            fog_drop = expected_far & ~finite
            instant_fog = int(fog_drop.sum()) >= 12
            if nan_frac >= 0.12 and int(expected_far.sum()) >= 12:
                instant_fog = True
        else:
            instant_fog = nan_frac >= 0.12

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
        """Шаг прогноза по одометрии и IMU."""
        self.blocked_wheels = False
        self._pre_predict_xy = (self.x, self.y)

        (
            self.x,
            self.y,
            self.th,
            self.ox,
            self.oy,
            self.oth,
            self.var_along,
            self.var_cross,
            self.var_th,
            self._unconfirmed_dist,
            self.heading_bias,
            self.bias_initialized,
            self._predict_var,
            step_dist,
        ) = self._ekf.predict(
            self.x,
            self.y,
            self.th,
            self.ox,
            self.oy,
            self.oth,
            self.var_along,
            self.var_cross,
            self.var_th,
            self.scale,
            self._unconfirmed_dist,
            self.scale_locked,
            odom_dx,
            odom_dy,
            odom_dth,
            imu_heading,
            imu_yaw_rate,
            dt,
            self.heading_bias,
            self.bias_initialized,
        )

        self._odom_step_tick = step_dist
        self._pending_odom_step += step_dist
        self._check_lost_status()

    def _along_bound_m(self) -> float:
        return self._ekf.along_bound_m(self._unconfirmed_dist, self.scale_locked)

    def _rollback_predict(self) -> None:
        (
            self.x,
            self.y,
            self.var_along,
            self.var_cross,
            self.var_th,
            self._pending_odom_step,
            self._unconfirmed_dist,
        ) = self._ekf.rollback_predict(
            self._pre_predict_xy,
            self._predict_var,
            self._odom_step_tick,
            self.var_along,
            self.var_cross,
            self.var_th,
            self._pending_odom_step,
            self._unconfirmed_dist,
        )
        self._predict_var = (0.0, 0.0, 0.0)

    def update_scan(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        segs: np.ndarray,
        is_fog: bool = False,
        segs_aabb: Optional[np.ndarray] = None,
    ) -> bool:
        """Сопоставление сканов с отрезками карты."""
        self.fog_active = bool(is_fog)

        res = self._scan_matcher.match(
            self.x,
            self.y,
            self.th,
            ranges,
            rel_angles,
            segs,
            is_fog=is_fog,
            segs_aabb=segs_aabb,
        )

        if len(res.near_segs) == 0:
            return self._scan_unavailable(is_fog)

        self.scan_inliers = res.inliers

        if not is_fog:
            self._fog_var_added = 0.0

        self._register_scan_health(is_fog)

        if is_fog:
            self.var_along, self.var_cross, self._fog_var_added = (
                self._scan_matcher.penalise_missing_near_walls(
                    self.x,
                    self.y,
                    self.th,
                    self.var_along,
                    self.var_cross,
                    self._fog_var_added,
                    res.r_sub,
                    res.rel_sub,
                    res.near_segs,
                )
            )

        if res.success:
            cur_x, cur_y, cur_th = res.x, res.y, res.th
            prev_x, prev_y = self._prev_scan_xy
            prev_ox, prev_oy = self._prev_scan_odom
            self._prev_scan_xy = (cur_x, cur_y)
            self._prev_scan_odom = (self.ox, self.oy)

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

            self.x = cur_x
            self.y = cur_y
            self.th = cur_th

            if stall:
                self.blocked_wheels = True
                self._rollback_predict()
                self._pending_odom_step = 0.0
            else:
                if res.normals is not None and len(res.normals) > 0 and res.weights is not None:
                    self._update_variances_from_walls(res.normals, res.weights)

                gnss_recent = self.last_gnss_accepted or self._gnss_fix_ticks <= 50
                if not self.scale_locked:
                    r_all = np.asarray(ranges, dtype=float)
                    rel_all = np.asarray(rel_angles, dtype=float)
                    longitudinal = self._scan_has_angle(res.normals) or self._scan_holds_landmark(
                        r_all, rel_all, res.d_prev, res.d_next, res.finite_all, res.near_segs
                    )
                    if gnss_recent or (res.inliers > 80 and longitudinal):
                        self._accumulate_scale(prev_ox, prev_oy, cur_x - prev_x, cur_y - prev_y)
                self._pending_odom_step = 0.0

                r_all = np.asarray(ranges, dtype=float)
                rel_all = np.asarray(rel_angles, dtype=float)
                self._apply_landmark_correction(
                    r_all, rel_all, res.d_prev, res.d_next, res.finite_all, res.near_segs
                )

            self._check_lost_status()
            return True

        self._check_lost_status()
        return False

    def _scan_unavailable(self, is_fog: bool) -> bool:
        self.scan_inliers = 0
        self._register_scan_health(is_fog)
        self._check_lost_status()
        return False

    @staticmethod
    def _scan_has_angle(normals: Optional[np.ndarray]) -> bool:
        return ScanMatcher.has_angle(normals)

    def _scan_holds_landmark(
        self,
        r_all: np.ndarray,
        rel_all: np.ndarray,
        d_prev: np.ndarray,
        d_next: np.ndarray,
        finite_all: np.ndarray,
        segs: np.ndarray,
    ) -> bool:
        return self._scan_matcher.holds_landmark(
            self.x,
            self.y,
            self.th,
            self.landmarks,
            r_all,
            rel_all,
            d_prev,
            d_next,
            finite_all,
            segs,
        )

    def _register_scan_health(self, is_fog: bool) -> None:
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
        self.var_along, self.var_cross, self._fog_var_added = (
            self._scan_matcher.penalise_missing_near_walls(
                self.x,
                self.y,
                self.th,
                self.var_along,
                self.var_cross,
                self._fog_var_added,
                r_sub,
                rel_sub,
                segs,
            )
        )

    def _apply_landmark_correction(
        self,
        r_all: np.ndarray,
        rel_all: np.ndarray,
        d_prev: np.ndarray,
        d_next: np.ndarray,
        finite_all: np.ndarray,
        segs: np.ndarray,
    ) -> None:
        new_x, new_y, new_va, new_vc, applied = self._scan_matcher.apply_landmark_correction(
            self.x,
            self.y,
            self.th,
            self.var_along,
            self.var_cross,
            r_all,
            rel_all,
            d_prev,
            d_next,
            finite_all,
            segs,
            self.pole_centers,
        )
        if applied:
            self.x = new_x
            self.y = new_y
            self.var_along = new_va
            self.var_cross = new_vc
            self._unconfirmed_dist = 0.0

    def _update_variances_from_walls(self, normals: np.ndarray, weights: np.ndarray) -> None:
        new_va, new_vc, new_vth, reset_unconfirmed = self._ekf.update_variances_from_walls(
            self.th, self.var_along, self.var_cross, self.var_th, normals, weights
        )
        self.var_along = new_va
        self.var_cross = new_vc
        self.var_th = new_vth
        if reset_unconfirmed:
            self._unconfirmed_dist = 0.0

    @staticmethod
    def _snap_scale(calc_scale: float) -> float:
        s = max(0.96, min(1.04, float(calc_scale)))
        if 0.99 <= s <= 1.01:
            s = 1.01 if s >= 1.0 else 0.99
        return s

    def _accumulate_scale(
        self,
        prev_odom_x: float,
        prev_odom_y: float,
        scan_dx: float,
        scan_dy: float,
    ) -> None:
        if self.scale_locked:
            return

        odom_dx = self.ox - prev_odom_x
        odom_dy = self.oy - prev_odom_y
        odom_len = math.hypot(odom_dx, odom_dy)
        if odom_len <= 1e-6:
            return

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
        if lidar_step > 0.01 * odom_len:
            self._scale_ratios.append(odom_len / lidar_step)

        if self._scale_lidar_dist >= 25.0:
            if len(self._scale_ratios) >= 40:
                calc_scale = self._trimmed_mean(self._scale_ratios, 0.15)
            else:
                calc_scale = self._scale_odom_dist / max(self._scale_lidar_dist, 1e-6)
            self.scale = self._snap_scale(calc_scale)
            self.scale_locked = True
            self._unconfirmed_dist = 0.0
            self.var_along = max(self.var_along, (0.01 * self._scale_lidar_dist) ** 2)

    @staticmethod
    def _trimmed_mean(values: List[float], trim: float) -> float:
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
        accepted, new_x, new_y, new_va, new_vc, reset_unconf = self._gnss.update(
            self.x,
            self.y,
            self.var_along,
            self.var_cross,
            gnss_x,
            gnss_y,
            gnss_valid,
            gnss_hdop,
            in_shadow=in_shadow,
            scan_inliers=self.scan_inliers,
            fog_active=self.fog_active,
        )
        self.x = new_x
        self.y = new_y
        self.var_along = new_va
        self.var_cross = new_vc
        if reset_unconf:
            self._unconfirmed_dist = 0.0
        self._check_lost_status()
        return accepted

    def dock_snap(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        dock_goal: Union[Tuple[float, float, float], List[float]],
        dock_wall_segs: np.ndarray,
    ) -> bool:
        """Точная привязка к доку в пределах 1.5 - 3.0 м от цели дока."""
        gx, gy, gh = float(dock_goal[0]), float(dock_goal[1]), float(dock_goal[2])
        dist_to_goal = math.hypot(gx - self.x, gy - self.y)
        heading_err = abs(wrap_angle(self.th - gh))

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

        exp_front = raycast(self.x, self.y, np.array([self.th]), dock_wall_segs)
        exp_left = raycast(self.x, self.y, np.array([self.th + math.pi / 2]), dock_wall_segs)
        exp_right = raycast(self.x, self.y, np.array([self.th - math.pi / 2]), dock_wall_segs)

        mf = beam_median(0)
        ml = beam_median(n // 4)
        mr = beam_median((3 * n) // 4)

        cos_th = math.cos(self.th)
        sin_th = math.sin(self.th)

        applied = False

        if math.isfinite(mf) and math.isfinite(exp_front[0]) and abs(mf - exp_front[0]) < 0.6:
            err_f = mf - exp_front[0]
            self.x -= 0.5 * err_f * cos_th
            self.y -= 0.5 * err_f * sin_th
            self.var_along = min(self.var_along, 0.02**2)
            applied = True

        lat_errs = []
        if math.isfinite(ml) and math.isfinite(exp_left[0]) and abs(ml - exp_left[0]) < 0.6:
            lat_errs.append(-(ml - exp_left[0]))
        if math.isfinite(mr) and math.isfinite(exp_right[0]) and abs(mr - exp_right[0]) < 0.6:
            lat_errs.append(mr - exp_right[0])

        if lat_errs:
            lat_corr = float(np.mean(lat_errs))
            self.x += 0.5 * lat_corr * (-sin_th)
            self.y += 0.5 * lat_corr * cos_th
            self.var_cross = min(self.var_cross, 0.02**2)
            applied = True

        if applied:
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
        """Искать позу только когда платформа стоит и поза потеряна."""
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
        """Глобально-локальный поиск гипотез по сетке при потере позы."""
        res = self._scan_matcher.recover_grid_search(
            self.x,
            self.y,
            self.th,
            ranges,
            rel_angles,
            segs,
            is_fog=is_fog,
        )
        if res is not None:
            self.x, self.y, self.th = res
            self.var_along = 0.2**2
            self.var_cross = 0.2**2
            self.var_th = np.radians(3.0) ** 2
            self._unconfirmed_dist = 0.0
            self.is_lost = False
            return True
        return False

    def _check_lost_status(self) -> None:
        """Оценить статус потери позы и экспортируемое ограничение скорости."""
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
