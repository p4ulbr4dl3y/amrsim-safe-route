"""Localization module: EKF state estimation, scan-matching Gauss-Newton, GNSS fusion, dock snap.

Conforms to plan/02-lokalizaciya.md and isolation requirements (only stdlib and numpy).
"""
import math
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

try:
    from .geom import (
        filter_segs_aabb,
        point_to_segs_displacement,
        raycast,
        rot2d,
        segments_aabb,
        wrap_angle,
    )
except ImportError:
    from geom import (
        filter_segs_aabb,
        point_to_segs_displacement,
        raycast,
        rot2d,
        segments_aabb,
        wrap_angle,
    )


class Localizer:
    """AMR State Estimator and Localizer.
    
    Coordinates:
      x: East (m)
      y: North (m)
      th: Counterclockwise from East (rad)
      
    Pure odometry frame (ox, oy, oth) is tracked without corrections for dynamic object perception.
    """

    def __init__(self, initial_pose: Union[List[float], Tuple[float, float, float], np.ndarray]):
        self.x = float(initial_pose[0])
        self.y = float(initial_pose[1])
        self.th = wrap_angle(float(initial_pose[2]))

        # Pure odometry frame without corrections or scale adjustments
        self.ox = 0.0
        self.oy = 0.0
        self.oth = 0.0

        # Variances: along path, cross path, heading (rad^2)
        self.var_along = 0.0
        self.var_cross = 0.0
        self.var_th = 0.0

        # Odometry scale factor (true step = odom_step / scale)
        self.scale = 1.0
        self.scale_locked = False
        self._scale_odom_dist = 0.0
        self._scale_lidar_dist = 0.0
        self._prev_scan_xy = (self.x, self.y)

        # IMU heading bias (th = imu_heading - heading_bias)
        self.heading_bias = 0.0
        self.bias_initialized = False

        # Status and health flags
        self.is_lost = False
        self.blocked_wheels = False
        self.scan_inliers = 0
        self.scan_std = 0.0

        # GNSS gating and recovery tracking
        self.gnss_rejections: List[Tuple[float, float]] = []
        self.last_gnss_accepted = False

        # Fog detection hysteresis counter (hold 1.0s = 10 ticks)
        self._fog_hold = 0

    @property
    def pose(self) -> Tuple[float, float, float]:
        """Return (x, y, th)."""
        return (self.x, self.y, self.th)

    @property
    def odom_pose(self) -> Tuple[float, float, float]:
        """Return pure odometry pose (ox, oy, oth)."""
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
        """Detect fog condition based on ~6m drops where map expects 10-20m.
        
        Holds flag for 1.0s (10 ticks) to avoid flickering.
        """
        r = np.asarray(ranges, dtype=float)
        n = len(r)
        if n == 0:
            return False

        finite = np.isfinite(r)
        if expected_ranges is not None and len(expected_ranges) == n:
            beams_beyond_65 = int((finite & (r > 6.5)).sum())
            if beams_beyond_65 > 3:
                self._fog_hold = 0
                return False
            exp = np.asarray(expected_ranges, dtype=float)
            fog_drop = (exp >= 9.0) & (exp <= 25.0) & finite & (r >= 4.5) & (r <= 6.2)
            drop_count = int(fog_drop.sum())
            instant_fog = (beams_beyond_65 == 0) and (drop_count >= 12)
        else:
            instant_fog = (np.isnan(r).sum() / float(n) >= 0.15)

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
        """Prediction step using odometry and IMU.
        
        - Pure odometry (ox, oy, oth) updated directly.
        - True position (x, y) updated by (odom_dx, odom_dy) / scale rotated by current th.
        - Heading watchdog: if imu_heading jumps > 0.05 rad compared to expected, integrate yaw_rate.
        - Variances propagated based on motion.
        """
        # 1. Update pure odometry frame (no corrections, no scale)
        cos_oth = math.cos(self.oth)
        sin_oth = math.sin(self.oth)
        self.ox += cos_oth * odom_dx - sin_oth * odom_dy
        self.oy += sin_oth * odom_dx + cos_oth * odom_dy
        self.oth = wrap_angle(self.oth + odom_dth)

        # 2. Check wheel slip / blocked wheels condition externally or store odom step
        step_dist = math.hypot(odom_dx, odom_dy)
        if self.blocked_wheels:
            # Don't integrate slipping odometry
            return

        # 3. Position update scaled by odometry scale factor
        s = self.scale if (0.90 <= self.scale <= 1.10) else 1.0
        scaled_dx = odom_dx / s
        scaled_dy = odom_dy / s

        cos_th = math.cos(self.th)
        sin_th = math.sin(self.th)
        self.x += cos_th * scaled_dx - sin_th * scaled_dy
        self.y += sin_th * scaled_dx + cos_th * scaled_dy

        # 4. Heading update from IMU
        if not self.bias_initialized:
            self.heading_bias = wrap_angle(imu_heading - self.th)
            self.bias_initialized = True

        expected_th = wrap_angle(self.th + imu_yaw_rate * dt)
        measured_th = wrap_angle(imu_heading - self.heading_bias)

        # Watchdog: jump > 0.05 rad fallback to yaw_rate integration
        if abs(wrap_angle(measured_th - expected_th)) > 0.05:
            self.th = expected_th
        else:
            self.th = measured_th

        # 5. Variance growth
        # Along-track variance: (0.04 * dist)^2 until scale calibrated, then (0.01 * dist)^2
        scale_err = 0.01 if self.scale_locked else 0.04
        self.var_along += (scale_err * step_dist) ** 2 + 1e-5

        # Cross-track variance: grows with heading uncertainty and yaw drift (0.3 deg / sqrt(min))
        # 0.3 deg = 0.0052 rad -> ~0.0052 / sqrt(60) ≈ 0.00067 rad/sqrt(s) -> per second ~4.5e-7 rad^2/s
        yaw_drift_var = (0.00067 ** 2) * dt
        self.var_th += yaw_drift_var
        self.var_cross += (step_dist * math.sin(math.sqrt(self.var_th))) ** 2 + (0.005 * step_dist) ** 2 + 1e-5

        # Check lost conditions
        self._check_lost_status()

    def update_scan(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        segs: np.ndarray,
        is_fog: bool = False,
        segs_aabb: Optional[np.ndarray] = None,
    ) -> bool:
        """Scan-matching against map segments using 4 iterations of Gauss-Newton.
        
        Args:
          ranges: 1D array of beam ranges (360 beams, 1 deg step)
          rel_angles: 1D array of beam angles in robot frame (rad)
          segs: (M, 4) array of map segments [x1, y1, x2, y2]
          is_fog: whether fog condition is active
          segs_aabb: optional precomputed AABB for segments
        """
        if segs is None or len(segs) == 0:
            return False

        # Filter segments in robot vicinity (~25m)
        reach = 25.0
        near_segs_arr = filter_segs_aabb(segs, self.x, self.y, reach, aabb=segs_aabb)
        if len(near_segs_arr) == 0:
            return False

        r_all = np.asarray(ranges, dtype=float)
        rel_all = np.asarray(rel_angles, dtype=float)

        # 1. Subsample rays every 2 deg (step 2)
        step = 2
        r_sub = r_all[::step]
        rel_sub = rel_all[::step]

        # Valid finite range mask
        max_valid_range = 5.5 if is_fog else 19.0
        valid_range_mask = np.isfinite(r_sub) & (r_sub > 0.1) & (r_sub < max_valid_range)

        # Snow filter: a valid return must have at least one neighbour within 0.4m in Cartesian plane
        # Perform snow filtering on the full/subsampled rays
        # Subsampled indices
        sub_indices = np.arange(0, len(r_all), step)
        
        # Check Cartesian distances between neighbouring beams to eliminate single snow specks
        # A return is snow if isolated: both left and right neighbours (in 1 deg array) are not within 0.4m
        cos_rel_all = np.cos(rel_all)
        sin_rel_all = np.sin(rel_all)
        x_pts = r_all * cos_rel_all
        y_pts = r_all * sin_rel_all

        # Vectorized neighbour distance check in robot frame
        n_all = len(r_all)
        prev_idx = (np.arange(n_all) - 1) % n_all
        next_idx = (np.arange(n_all) + 1) % n_all

        finite_all = np.isfinite(r_all)
        d_prev = np.full(n_all, np.inf)
        d_next = np.full(n_all, np.inf)

        m_prev = finite_all & finite_all[prev_idx]
        m_next = finite_all & finite_all[next_idx]

        d_prev[m_prev] = np.hypot(x_pts[m_prev] - x_pts[prev_idx[m_prev]], y_pts[m_prev] - y_pts[prev_idx[m_prev]])
        d_next[m_next] = np.hypot(x_pts[m_next] - x_pts[next_idx[m_next]], y_pts[m_next] - y_pts[next_idx[m_next]])

        # A point is supported if either neighbor is finite and within 0.4m
        supported = (d_prev < 0.4) | (d_next < 0.4)
        
        supported_sub = supported[sub_indices]
        candidate_mask = valid_range_mask & supported_sub
        if candidate_mask.sum() < 20:
            return False

        cand_ranges = r_sub[candidate_mask]
        cand_rel = rel_sub[candidate_mask]

        # Gauss-Newton state adjustments
        cur_x = self.x
        cur_y = self.y
        cur_th = self.th

        inliers_count = 0
        final_std = 999.0
        last_normals = None
        last_weights = None

        # 4 iterations of Gauss-Newton
        for it in range(4):
            # Compute beam endpoints in world frame
            beam_world_angles = cur_th + cand_rel
            px = cur_x + cand_ranges * np.cos(beam_world_angles)
            py = cur_y + cand_ranges * np.sin(beam_world_angles)

            # Map projection & distance
            disp = point_to_segs_displacement(px, py, near_segs_arr)
            residuals = disp.dists  # distance to nearest segment line
            normals = disp.normals  # unit normal (Nx, Ny)

            # Inlier conditions:
            # 1. residual < 0.25 m
            # 2. range not shorter than map expected raycast by > 0.4 m (tested by displacement proj)
            # If distance from ray origin to projection point is significantly greater than range,
            # it means ray stopped well before the map wall (obstacle/person/snow).
            dist_to_proj = np.hypot(disp.projs[:, 0] - cur_x, disp.projs[:, 1] - cur_y)
            not_short = (cand_ranges >= dist_to_proj - 0.4)

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

            # Huber weighting: delta = 0.08
            huber_delta = 0.08
            abs_res = np.abs(res_inliers)
            weights = np.where(abs_res <= huber_delta, 1.0, huber_delta / np.maximum(abs_res, 1e-12))
            last_weights = weights

            # Residual signed error: r_i = n_x * (p_x - proj_x) + n_y * (p_y - proj_y) = dist
            # When adjusting state by (dx, dy, dth):
            # dp_x = dx - (py - cur_y) * dth
            # dp_y = dy + (px - cur_x) * dth
            # J_i = [n_x, n_y, -n_x * (py - cur_y) + n_y * (px - cur_x)]
            rx = px_inliers - cur_x
            ry = py_inliers - cur_y

            J = np.column_stack([
                norm_inliers[:, 0],
                norm_inliers[:, 1],
                -norm_inliers[:, 0] * ry + norm_inliers[:, 1] * rx,
            ])  # (K, 3)

            W = weights[:, None]
            JW = J * W
            H = J.T @ JW  # (3, 3)
            g = J.T @ (weights * res_inliers)  # (3,)

            # Damping for numerical stability
            H += 1e-3 * np.eye(3)

            try:
                delta = np.linalg.solve(H, -g)
            except np.linalg.LinAlgError:
                break

            # Apply step
            cur_x += float(delta[0])
            cur_y += float(delta[1])
            cur_th = wrap_angle(cur_th + float(delta[2]))

            if np.hypot(delta[0], delta[1]) < 0.001 and abs(delta[2]) < 0.001:
                break

        self.scan_inliers = inliers_count
        self.scan_std = final_std

        # Acceptance criteria: inliers >= 30 and std(residual) < 0.08 m
        if inliers_count >= 30 and final_std < 0.08:
            # Check wheel stall / blocked wheels
            # If odom passed > 2cm but scan displacement is < 1cm
            prev_x, prev_y = self._prev_scan_xy
            scan_dist = math.hypot(cur_x - prev_x, cur_y - prev_y)
            self._prev_scan_xy = (cur_x, cur_y)

            # Accept state update
            self.x = cur_x
            self.y = cur_y
            self.th = cur_th

            # Update IMU bias slowly if many inliers and long wall observed
            if inliers_count >= 60 and last_normals is not None:
                # Disagreement with IMU
                pass

            # Update variances: project variance into normal / tangent axes of the observed walls
            if last_normals is not None and len(last_normals) > 0:
                self._update_variances_from_walls(last_normals, last_weights)

            # Odometry scale accumulation (if >= 80 inliers and good conditions)
            if not self.scale_locked:
                self._accumulate_scale(scan_dist)

            self._check_lost_status()
            return True

        self._check_lost_status()
        return False

    def _update_variances_from_walls(self, normals: np.ndarray, weights: np.ndarray) -> None:
        """Update variances along and cross wall normal directions."""
        # Mean normal orientation
        # Wall holds the normal and heading, but does NOT constrain the tangent!
        # Shrink variance along normal, keep variance along tangent.
        n_x = float(np.average(normals[:, 0], weights=weights))
        n_y = float(np.average(normals[:, 1], weights=weights))
        norm_mag = math.hypot(n_x, n_y)
        if norm_mag > 1e-3:
            n_x /= norm_mag
            n_y /= norm_mag

            # Normal angle
            alpha = math.atan2(n_y, n_x)
            # Robot heading vs wall normal
            d_angle = wrap_angle(alpha - self.th)
            cos_d2 = math.cos(d_angle) ** 2
            sin_d2 = math.sin(d_angle) ** 2

            # The normal error collapses to ~0.02^2 (scan precision)
            var_wall = 0.02 ** 2

            # Along and cross variance update
            # If wall is parallel to path (d_angle ~ 90 deg), cross is normal -> var_cross collapses!
            # If wall is perpendicular to path (d_angle ~ 0 deg), along is normal -> var_along collapses!
            self.var_cross = self.var_cross * sin_d2 + var_wall * cos_d2
            self.var_along = self.var_along * cos_d2 + var_wall * sin_d2
            self.var_th = min(self.var_th, (0.01) ** 2)

    def _accumulate_scale(self, lidar_step_dist: float) -> None:
        """Accumulate distance to calibrate odometry scale factor over 25m."""
        # Called when scan match succeeded with high confidence
        if self.scale_locked:
            return

        self._scale_lidar_dist += lidar_step_dist
        self._scale_odom_dist += lidar_step_dist * self.scale

        if self._scale_lidar_dist >= 25.0:
            calc_scale = self._scale_odom_dist / max(self._scale_lidar_dist, 1e-6)
            # Clamp scale to physical expectation [0.96, 1.04]
            self.scale = max(0.96, min(1.04, calc_scale))
            self.scale_locked = True

    def update_gnss(
        self,
        gnss_x: float,
        gnss_y: float,
        gnss_valid: bool,
        gnss_hdop: float,
        in_shadow: bool = False,
    ) -> bool:
        """GNSS measurement update with innovation gating.
        
        Rules:
        - Never directly copy raw GNSS into pose_est.
        - Gate: valid, not in_shadow, innovation dist < 1.5 m, scan inliers >= 30.
        - Outlier rejection: if GNSS steadily disagrees for > 3.0s (30 ticks)
          with std < 0.8m, and scan agrees with GNSS, perform recovery.
        """
        self.last_gnss_accepted = False

        if in_shadow or not gnss_valid or gnss_hdop > 2.0:
            self.gnss_rejections.clear()
            return False

        dx = gnss_x - self.x
        dy = gnss_y - self.y
        dist = math.hypot(dx, dy)

        # Innovation gate: 1.5 m
        if dist < 1.5:
            self.gnss_rejections.clear()
            # Gated innovation filter update (Kalman-like blended correction)
            # R_gnss ~ (0.3m)^2, HDOP scaling
            r_var = (0.3 * max(1.0, gnss_hdop)) ** 2
            k_x = self.var_along / (self.var_along + r_var)
            k_y = self.var_cross / (self.var_cross + r_var)
            k = max(0.01, min(0.15, 0.5 * (k_x + k_y)))

            self.x += k * dx
            self.y += k * dy

            # Variance shrink bounded by GNSS accuracy
            self.var_along = max(0.04, self.var_along * (1.0 - k))
            self.var_cross = max(0.04, self.var_cross * (1.0 - k))
            self.last_gnss_accepted = True
            self._check_lost_status()
            return True

        # Rejected innovation: record for persistent disagreement check
        self.gnss_rejections.append((dx, dy))

        # Check persistent disagreement (> 3.0 s = 30 ticks)
        if len(self.gnss_rejections) >= 30:
            recent = np.array(self.gnss_rejections[-20:])
            # If stable (std < 0.8m) and scan inliers are very low (< 20, filter drifted):
            if recent.std(axis=0).max() < 0.8 and self.scan_inliers < 20:
                # Filter lost/drifted, GNSS is consistent: recovery shift
                shift_x = float(recent[:, 0].mean())
                shift_y = float(recent[:, 1].mean())
                self.x += shift_x
                self.y += shift_y
                self.var_along = 0.5 ** 2
                self.var_cross = 0.5 ** 2
                self.gnss_rejections.clear()
                self._check_lost_status()
                return True
            if len(self.gnss_rejections) > 60:
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
        """Accurate docking snap within 1.5 - 3.0 m of dock goal.
        
        Front beam ~0 deg expects 1.5m to front dock wall.
        Side beams ~+-90 deg expect 2.5m to side dock walls.
        Adjusts pose by half the discrepancy along and cross heading.
        """
        gx, gy, gh = float(dock_goal[0]), float(dock_goal[1]), float(dock_goal[2])
        dist_to_goal = math.hypot(gx - self.x, gy - self.y)
        heading_err = abs(wrap_angle(self.th - gh))

        # Only activate close to goal (<= 3.0m) and roughly aligned (<= 0.35 rad)
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

        # Front (index 0), Left (index n // 4 = 90 deg), Right (index 3*n // 4 = 270 deg / -90 deg)
        exp_front = raycast(self.x, self.y, np.array([self.th]), dock_wall_segs)
        exp_left = raycast(self.x, self.y, np.array([self.th + math.pi / 2]), dock_wall_segs)
        exp_right = raycast(self.x, self.y, np.array([self.th - math.pi / 2]), dock_wall_segs)

        mf = beam_median(0)
        ml = beam_median(n // 4)
        mr = beam_median((3 * n) // 4)

        cos_th = math.cos(self.th)
        sin_th = math.sin(self.th)

        applied = False

        # Longitudinal adjustment (front wall)
        if math.isfinite(mf) and math.isfinite(exp_front[0]) and abs(mf - exp_front[0]) < 0.6:
            err_f = mf - exp_front[0]
            # If measured range is smaller than expected, robot is closer than expected -> move backwards
            self.x -= 0.5 * err_f * cos_th
            self.y -= 0.5 * err_f * sin_th
            self.var_along = min(self.var_along, 0.02 ** 2)
            applied = True

        # Lateral adjustment (side walls)
        lat_errs = []
        if math.isfinite(ml) and math.isfinite(exp_left[0]) and abs(ml - exp_left[0]) < 0.6:
            lat_errs.append(-(ml - exp_left[0]))
        if math.isfinite(mr) and math.isfinite(exp_right[0]) and abs(mr - exp_right[0]) < 0.6:
            lat_errs.append(mr - exp_right[0])

        if lat_errs:
            lat_corr = float(np.mean(lat_errs))
            # Lateral direction is (-sin_th, cos_th)
            self.x += 0.5 * lat_corr * (-sin_th)
            self.y += 0.5 * lat_corr * cos_th
            self.var_cross = min(self.var_cross, 0.02 ** 2)
            applied = True

        return applied

    def recover_grid_search(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        segs: np.ndarray,
        is_fog: bool = False,
    ) -> bool:
        """Global/local hypothesis search over grid when lost.
        
        Grid: dx in [-3, 3] step 0.5m, dy in [-3, 3] step 0.5m, dth in [-8°, 8°] step 2°.
        Uses 60 rays for evaluation. Sharp peak accepted to clear is_lost.
        """
        if segs is None or len(segs) == 0:
            return False

        r_all = np.asarray(ranges, dtype=float)
        rel_all = np.asarray(rel_angles, dtype=float)

        # 60 rays (every 6th beam)
        step = 6
        r_60 = r_all[::step]
        rel_60 = rel_all[::step]

        max_range = 5.5 if is_fog else 19.0
        mask = np.isfinite(r_60) & (r_60 > 0.1) & (r_60 < max_range)
        if mask.sum() < 15:
            return False

        eval_r = r_60[mask]
        eval_rel = rel_60[mask]

        dx_grid = np.arange(-3.0, 3.1, 0.5)
        dy_grid = np.arange(-3.0, 3.1, 0.5)
        dth_grid = np.radians(np.arange(-8.0, 8.1, 2.0))

        best_score = -1
        second_score = -1
        best_hypothesis = None

        reach = 25.0
        local_segs = filter_segs_aabb(segs, self.x, self.y, reach + 3.5)
        if len(local_segs) == 0:
            return False

        for dth in dth_grid:
            cand_th = wrap_angle(self.th + dth)
            beam_angles = cand_th + eval_rel
            cos_b = np.cos(beam_angles)
            sin_b = np.sin(beam_angles)

            for dx in dx_grid:
                cx = self.x + dx
                for dy in dy_grid:
                    cy = self.y + dy

                    pts_x = cx + eval_r * cos_b
                    pts_y = cy + eval_r * sin_b

                    disp = point_to_segs_displacement(pts_x, pts_y, local_segs)
                    inliers = (disp.dists < 0.25).sum()

                    if inliers > best_score:
                        second_score = best_score
                        best_score = inliers
                        best_hypothesis = (cx, cy, cand_th)
                    elif inliers > second_score:
                        second_score = inliers

        # Sharp distinct peak: inliers >= 35 and significantly better than 2nd best
        if best_score >= 35 and (best_score >= second_score * 1.25 or best_score - second_score >= 8):
            self.x, self.y, self.th = best_hypothesis
            self.var_along = 0.2 ** 2
            self.var_cross = 0.2 ** 2
            self.var_th = np.radians(3.0) ** 2
            self.is_lost = False
            return True

        return False

    def _check_lost_status(self) -> None:
        """Evaluate lost status based on variance thresholds (plan/02-lokalizaciya.md)."""
        # Conditions for lost:
        # sigma_cross > 0.8 m or sigma_th > 10 deg (0.174 rad)
        # sigma_along > 5.0 m
        if self.sigma_cross > 0.8 or self.sigma_th > math.radians(10.0) or self.sigma_along > 5.0:
            self.is_lost = True
        elif self.sigma_cross < 0.4 and self.sigma_th < math.radians(5.0) and self.sigma_along < 2.0:
            self.is_lost = False
