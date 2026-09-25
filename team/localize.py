"""Localization module: EKF state estimation, scan-matching Gauss-Newton, GNSS fusion, dock snap.

Conforms to plan/02-lokalizaciya.md and isolation requirements (only stdlib and numpy).
"""
import math
from typing import List, Optional, Tuple, Union

import numpy as np

try:
    from .geom import (
        filter_segs_aabb,
        point_to_segs_displacement,
        raycast,
        wrap_angle,
    )
except ImportError:
    from geom import (
        filter_segs_aabb,
        point_to_segs_displacement,
        raycast,
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

    def __init__(
        self,
        initial_pose: Union[List[float], Tuple[float, float, float], np.ndarray],
        building_segs: Optional[np.ndarray] = None,
        pole_centers: Optional[np.ndarray] = None,
    ):
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
        self._scale_ratios: List[float] = []
        self._prev_scan_xy = (self.x, self.y)
        self._prev_scan_odom = (0.0, 0.0)

        # Per-tick odometry step (real path) pending scan-match confirmation, and the
        # exact variance increments so a blocked-wheel tick can be undone.
        self._odom_step_tick = 0.0
        self._pending_odom_step = 0.0
        # Short window used by the wheel-stall detector (plan/02:149-157).
        self._stall_ticks = 0
        self._stall_odom = 0.0
        self._stall_xy = (self.x, self.y)
        self._pre_predict_xy = (self.x, self.y)
        self._predict_var = (0.0, 0.0, 0.0)

        # IMU heading bias (th = imu_heading - heading_bias)
        self.heading_bias = 0.0
        self.bias_initialized = False

        # Status and health flags
        self.is_lost = False
        self.blocked_wheels = False
        self.scan_inliers = 0
        # Speed cap exported to the safety governor (plan/02 "Потеря ориентации")
        self.lost_speed_limit = 1.39
        self._low_inlier_ticks = 0
        self._gnss_fix_ticks = 10 ** 9

        # GNSS gating and recovery tracking
        self.gnss_rejections: List[Tuple[float, float]] = []
        self.last_gnss_accepted = False

        # Fog detection hysteresis counter (hold 1.0s = 10 ticks)
        self._fog_hold = 0
        self.fog_active = False
        # Bounded cross/along variance penalty for expected near walls lost in fog
        self._fog_var_added = 0.0

        # Longitudinal landmarks: ends of mapped segments and pole centres (plan/02:63-81)
        self.landmarks = self._build_landmarks(building_segs, pole_centers)
        if pole_centers is not None and len(pole_centers) > 0:
            self.pole_centers: Optional[np.ndarray] = np.asarray(
                pole_centers, dtype=float).reshape(-1, 2)
        else:
            self.pole_centers = None

    @staticmethod
    def _build_landmarks(
        building_segs: Optional[np.ndarray],
        pole_centers: Optional[np.ndarray],
    ) -> np.ndarray:
        """Collect longitudinal landmarks: segment endpoints plus explicit pole centres."""
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
        """Detect fog condition from the real (often NaN/inf) simulator scan.

        plan/02:49-61. The simulator caps every return at ``lidar.fog_max_range`` (6.0 m)
        and turns everything beyond it into NaN, so the working evidence is:
          (a) a large share of non-finite beams, gated by the absence of long returns;
          (b) the map expects a wall in 9-19 m and the beam there is NaN/inf, in a batch.
        Beam ranges > 6.5 m cannot exist in fog, so they must NOT zero the hysteresis
        counter instantly (the old early return killed the 1 s hold).

        Holds the flag for 1.0 s (10 ticks) to avoid flickering.
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
            # Upper bound 19 m: the lidar max_range is 20 m, so 20-25 m can never be seen.
            expected_far = (exp >= 9.0) & (exp <= 19.0)
            # (b) the map expects a wall in the measurable band but the beam is missing.
            fog_drop = expected_far & ~finite
            instant_fog = int(fog_drop.sum()) >= 12
            # (a) mostly non-finite scan, but only where the map actually has far walls to
            # lose: an open yard without mapped walls has a large NaN share in clear weather.
            if nan_frac >= 0.12 and int(expected_far.sum()) >= 12:
                instant_fog = True
        else:
            instant_fog = nan_frac >= 0.12
        # (c) a long return is evidence against fog for this tick. A few such beams (snow
        # specks) must not clear the flag, so they only stop the hold from being re-armed.
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

        # 2. Store the real odometry path of this tick. It is added to the scale
        #    accumulator only when the scan match confirms actual motion (plan/02:99-108),
        #    so a slipping/blocked tick cannot poison the estimate.
        step_dist = math.hypot(odom_dx, odom_dy)
        self.blocked_wheels = False
        self._odom_step_tick = step_dist
        self._pending_odom_step += step_dist

        # 3. Position update scaled by odometry scale factor
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
        d_var_along = (scale_err * step_dist) ** 2 + 1e-5

        # Cross-track variance: grows with heading uncertainty and yaw drift (0.3 deg / sqrt(min))
        # 0.3 deg = 0.0052 rad -> ~0.0052 / sqrt(60) ≈ 0.00067 rad/sqrt(s) -> per second ~4.5e-7 rad^2/s
        yaw_drift_var = (0.00067 ** 2) * dt
        self.var_th += yaw_drift_var
        d_var_cross = (step_dist * math.sin(math.sqrt(self.var_th))) ** 2 + (0.005 * step_dist) ** 2 + 1e-5
        self.var_cross += d_var_cross
        self._predict_var = (d_var_along, d_var_cross, yaw_drift_var)

        # Check lost conditions
        self._check_lost_status()

    def _rollback_predict(self) -> None:
        """Undo this tick's prediction (blocked wheels, plan/02:149-157).

        The pose is restored to its pre-prediction value: an odometry tick that the scan
        match did not confirm must not be integrated into the filter.
        """
        self.x, self.y = self._pre_predict_xy
        da, dc, dth = self._predict_var
        self.var_along = max(0.0, self.var_along - da)
        self.var_cross = max(0.0, self.var_cross - dc)
        self.var_th = max(0.0, self.var_th - dth)
        self._predict_var = (0.0, 0.0, 0.0)
        self._pending_odom_step = max(0.0, self._pending_odom_step - self._odom_step_tick)

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
        self.fog_active = bool(is_fog)
        if segs is None or len(segs) == 0:
            return self._scan_unavailable(is_fog)

        # Filter segments in robot vicinity (~25m)
        reach = 25.0
        near_segs_arr = filter_segs_aabb(segs, self.x, self.y, reach, aabb=segs_aabb)
        if len(near_segs_arr) == 0:
            return self._scan_unavailable(is_fog)

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
        with np.errstate(invalid="ignore"):
            # inf range * cos == nan at exactly 0/90 deg; those beams are dropped anyway.
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
            return self._scan_unavailable(is_fog)

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
        for _ in range(4):
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

        if not is_fog:
            self._fog_var_added = 0.0

        # Low-inlier timer (plan/02:141)
        self._register_scan_health(is_fog)

        # Fog: expected near walls (<5.5 m) that vanished add variance in batches (plan/02:59)
        if is_fog:
            self._penalise_missing_near_walls(r_sub, rel_sub, near_segs_arr)

        # Acceptance criteria: inliers >= 30 and std(residual) < 0.08 m
        if inliers_count >= 30 and final_std < 0.08:
            prev_x, prev_y = self._prev_scan_xy
            prev_ox, prev_oy = self._prev_scan_odom
            self._prev_scan_xy = (cur_x, cur_y)
            self._prev_scan_odom = (self.ox, self.oy)

            # Wheel stall (plan/02:149-157): odometry moved while the mapped walls did
            # not move at all. Measured over a short window, because the pose is under
            # constant scan/GNSS tension and a single tick's scan displacement cannot be
            # told apart from that tension.
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

            # Accept state update
            self.x = cur_x
            self.y = cur_y
            self.th = cur_th

            if stall:
                # Do not integrate this odometry tick, do not touch the scale.
                self.blocked_wheels = True
                self._rollback_predict()
                self._pending_odom_step = 0.0
            else:
                # Update variances: project variance into normal / tangent axes of the observed walls
                if last_normals is not None and len(last_normals) > 0:
                    self._update_variances_from_walls(last_normals, last_weights)

                # Odometry scale accumulation (plan/02:99-108): no wheel block, and the
                # scan has to carry along-track information. A GNSS fix inside the 1.5 m
                # gate already anchors the pose, so any accepted match may be accumulated
                # with it -- that is what keeps a far facade from blocking calibration: on
                # 03 the north passage has no mapped wall nearer than ~14 m (the lidar
                # itself clamps at 5.5 m in fog), so the match never reaches 80 inliers
                # even though its end face and the facade bays are perfectly visible
                # landmarks (plan/02:63-81). Without GNSS the plan's stricter bar holds:
                # a dense match *and* the angle/landmark evidence.
                gnss_recent = self.last_gnss_accepted or self._gnss_fix_ticks <= 50
                if not self.scale_locked:
                    longitudinal = (self._scan_has_angle(last_normals)
                                    or self._scan_holds_landmark(
                                        r_all, rel_all, d_prev, d_next, finite_all,
                                        near_segs_arr))
                    if gnss_recent or (inliers_count > 80 and longitudinal):
                        self._accumulate_scale(
                            prev_ox, prev_oy, cur_x - prev_x, cur_y - prev_y)
                self._pending_odom_step = 0.0

                # Longitudinal landmarks: update the weak (tangential) axis only.
                self._apply_landmark_correction(
                    r_all, rel_all, d_prev, d_next, finite_all, near_segs_arr)

            self._check_lost_status()
            return True

        # Match rejected: keep the odometry path pending so the next accepted match
        # compares odometry and scan over exactly the same interval.
        self._check_lost_status()
        return False

    def _scan_unavailable(self, is_fog: bool) -> bool:
        """No usable scan this tick: count it towards the blind timer (plan/02:141)."""
        self.scan_inliers = 0
        self._register_scan_health(is_fog)
        self._check_lost_status()
        return False

    @staticmethod
    def _scan_has_angle(normals: Optional[np.ndarray]) -> bool:
        """True when the inlier walls span more than ~30 deg: an actual corner is seen."""
        if normals is None or len(normals) < 2:
            return False
        ang = np.arctan2(normals[:, 1], normals[:, 0])
        # Undirected normals -> work on doubled angles; the mean resultant length drops
        # below cos(30 deg) as soon as the spread exceeds 30 deg.
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
        """True when a scan corner sits on a mapped longitudinal landmark (plan/02:63-81).

        ``_scan_has_angle`` only looks at the spread of wall normals, so a robot driving
        past the end of a long facade sees "one wall" even though the silhouette of that
        facade's end is a perfectly good along-track reference. The plan names exactly
        that reference -- segment ends of buildings and pole centres -- and its
        association rule is 2 m. Here the same angular feature the landmark layer uses
        (neighbouring returns jumping by > 1.5 m) must land on a mapped wall
        (residual < 0.35 m) and be within 2 m of a mapped landmark. A snow speck fails
        both tests, so this cannot open the gate on an unobservable straight.
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
        """Count consecutive ticks with too few scan inliers (plan/02:141).

        Only counted when there is no absolute GNSS fix either: a blank street with a
        valid GNSS fix is not a loss of orientation.
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
        """In fog, expected near walls that return NaN add variance in a batch (plan/02:59)."""
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
        inc = 0.02 ** 2
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
        """Longitudinal landmarks (plan/02:63-81).

        An angular feature is a pair of neighbouring returns whose endpoints jump by
        more than 1.5 m. It is only usable when the endpoint actually lies on a mapped
        wall (residual < 0.35 m) and a mapped landmark -- an endpoint of that very
        segment, or a pole centre -- sits within 2 m of it. The along-wall residual is
        then written into the weak tangential axis only; the normal is already held by
        the facade, and a measurement there would smear it.
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
        # The feature must be a mapped point: its endpoint lies on a wall.
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

            # The feature must BE the landmark, not merely near it: a loose gate lets a
            # far-away wall end drag the pose along an axis the scan cannot observe.
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
            # Dead zone: the returned corner is quantised by the 1 deg beam grid, so a
            # small residual is noise. Correcting it every tick would integrate into a
            # large along-wall drift, and the scan cannot observe that axis to undo it.
            if abs(d_t) < 0.3:
                continue
            shifts.append(max(-0.5, min(0.5, d_t)))
            tangents.append((tx, ty))

        # A single beam-boundary feature is not trustworthy enough to move the pose.
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

        # Only the tangential axis is informed by this measurement.
        beta = math.atan2(mty, mtx)
        d_angle = wrap_angle(beta - self.th)
        cos_d2 = math.cos(d_angle) ** 2
        sin_d2 = math.sin(d_angle) ** 2
        var_t = self.var_along * cos_d2 + self.var_cross * sin_d2
        self.var_along = max(1e-6, self.var_along - 0.5 * var_t * cos_d2)
        self.var_cross = max(1e-6, self.var_cross - 0.5 * var_t * sin_d2)

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

            # Along and cross variance update.
            # The scan measures the wall NORMAL. Project it on the robot axes:
            #   n . forward = cos(d_angle),  n . lateral = sin(d_angle).
            # A wall parallel to the path (d_angle ~ 90 deg) therefore collapses the
            # CROSS variance; a wall perpendicular to the path collapses the ALONG one.
            # The tangential component is NOT constrained by this match.
            self.var_cross = self.var_cross * cos_d2 + var_wall * sin_d2
            self.var_along = self.var_along * sin_d2 + var_wall * cos_d2
            self.var_th = min(self.var_th, (0.01) ** 2)

    @staticmethod
    def _snap_scale(calc_scale: float) -> float:
        """Clamp the estimate to the physically allowed set [0.96,0.99] U [1.01,1.04]."""
        s = max(0.96, min(1.04, float(calc_scale)))
        if 0.99 <= s <= 1.01:
            # The 1.0 gap is not a valid odometry scale: push to the nearer boundary.
            s = 1.01 if s >= 1.0 else 0.99
        return s

    def _accumulate_scale(
        self,
        prev_odom_x: float,
        prev_odom_y: float,
        scan_dx: float,
        scan_dy: float,
    ) -> None:
        """Accumulate the REAL odometry path and the scan-matched path, then freeze.

        plan/02:99-108: s = odom_path / lidar_path over at least 25 m of scan-confirmed
        travel. Both paths are measured over exactly the same interval between two
        accepted scan matches -- the odometry odometer delta in its own frame, rotated
        into world axes -- and only the along-motion projection of the scan displacement
        is used so lateral scan/GNSS corrections do not inflate the lidar path.
        """
        if self.scale_locked:
            return

        odom_dx = self.ox - prev_odom_x
        odom_dy = self.oy - prev_odom_y
        odom_len = math.hypot(odom_dx, odom_dy)
        if odom_len <= 1e-6:
            return

        # Both displacements live in different frames and the difference is a constant:
        # odometry (ox, oy, oth) is the pure wheel frame whose heading starts at 0, while
        # the scan displacement is taken in world axes and the pose heading starts at
        # initial_pose[2]. On 01/02/04 the platform starts at theta = 0 so the two frames
        # coincide, but 03 starts at -90 deg and the raw dot product then projects a
        # sideways odometry delta onto a downhill scan delta -- it collapses to ~0 (or
        # flips sign), _scale_lidar_dist never reaches 25 m and the scale stays at 1.0.
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
        # Per-interval ratio odom/lidar. The along-wall component is only partially
        # observable, so single ratios are noisy by design; a trimmed mean over the whole
        # window is unbiased while individual scan glitches cannot move it.
        if lidar_step > 0.01 * odom_len:
            self._scale_ratios.append(odom_len / lidar_step)

        if self._scale_lidar_dist >= 25.0:
            if len(self._scale_ratios) >= 40:
                calc_scale = self._trimmed_mean(self._scale_ratios, 0.15)
            else:
                calc_scale = self._scale_odom_dist / max(self._scale_lidar_dist, 1e-6)
            self.scale = self._snap_scale(calc_scale)
            self.scale_locked = True
            # Along-track uncertainty after calibration is set by the residual scale
            # error (plan/02:97, plan/02:108), not by the wide pre-calibration budget.
            self.var_along = max(self.var_along, (0.01 * self._scale_lidar_dist) ** 2)

    @staticmethod
    def _trimmed_mean(values: List[float], trim: float) -> float:
        """Mean after dropping the lowest and highest `trim` fraction of the samples."""
        s = sorted(values)
        n = len(s)
        k = int(trim * n)
        kept = s[k:n - k] if n - 2 * k > 0 else s
        return sum(kept) / len(kept)

    def update_gnss(
        self,
        gnss_x: float,
        gnss_y: float,
        gnss_valid: bool,
        gnss_hdop: float,
        in_shadow: bool = False,
    ) -> bool:
        """GNSS measurement update with innovation gating.

        Rules (plan/02:83-97):
        - Never directly copy raw GNSS into pose_est.
        - Accept only when valid, not in_shadow and innovation < 1.5 m; when the scan
          corroborates the pose (scan_inliers >= 30) the measurement is taken at full
          gain, otherwise only small (<0.6 m) corrections pass, at reduced gain.
        - hdop > 1.4 only increases distrust (halved gain); hdop > 2.0 is a coarse guard.
        - Recovery from persistent disagreement (> 3 s, stable, scan agrees with GNSS)
          shifts the hypothesis to GNSS.
        """
        self.last_gnss_accepted = False

        if in_shadow or not gnss_valid or gnss_hdop > 2.0:
            self.gnss_rejections.clear()
            self._gnss_fix_ticks += 1
            return False

        dx = gnss_x - self.x
        dy = gnss_y - self.y
        dist = math.hypot(dx, dy)

        # Innovation gate: 1.5 m
        if dist < 1.5:
            # In fog the scan is range-clamped and blind by construction: the map cannot
            # corroborate anything, so the GNSS fix is the only reference and is used.
            scan_ok = (self.scan_inliers >= 30) or self.fog_active
            if not scan_ok and dist > 0.6:
                # The map cannot corroborate the pose (too few inliers) and the request
                # is not a small correction: hold it until the scan agrees again.
                self._gnss_fix_ticks += 1
                self.gnss_rejections.append((dx, dy))
                self._check_lost_status()
                return False

            self.gnss_rejections.clear()
            # Gated innovation filter update (Kalman-like blended correction)
            # R_gnss ~ (0.3m)^2, HDOP scaling
            r_var = (0.3 * max(1.0, gnss_hdop)) ** 2
            k_x = self.var_along / (self.var_along + r_var)
            k_y = self.var_cross / (self.var_cross + r_var)
            k = max(0.01, min(0.15, 0.5 * (k_x + k_y)))
            # A poor hdop only weakens the measurement, it does not veto it.
            if gnss_hdop > 1.4:
                k *= 0.5
            # A scan-blind correction is trusted less.
            if not scan_ok:
                k *= 0.3

            self.x += k * dx
            self.y += k * dy

            # Variance shrink bounded by GNSS accuracy
            self.var_along = max(0.04, self.var_along * (1.0 - k))
            self.var_cross = max(0.04, self.var_cross * (1.0 - k))
            self.last_gnss_accepted = True
            self._gnss_fix_ticks = 0
            self._check_lost_status()
            return True

        # Rejected innovation: record for persistent disagreement check
        self._gnss_fix_ticks += 1
        self.gnss_rejections.append((dx, dy))

        # Recovery from a persistent, stable disagreement. A GNSS jump lasts 2-5 s, so a
        # 6 s window with a tight spread cannot be a jump; the scan must still hold the
        # old pose (many inliers) for the filter to be the one that drifted.
        if len(self.gnss_rejections) >= 60:
            recent = np.array(self.gnss_rejections[-40:])
            shift_x = float(recent[:, 0].mean())
            shift_y = float(recent[:, 1].mean())
            shift = math.hypot(shift_x, shift_y)
            if (recent.std(axis=0).max() < 0.5 and self.scan_inliers >= 60
                    and 1.5 < shift < 3.0):
                # Filter drifted along an unobservable wall, GNSS is consistent.
                self.x += shift_x
                self.y += shift_y
                self.var_along = 0.5 ** 2
                self.var_cross = 0.5 ** 2
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

        if applied:
            # A dock correction is not scan-matched travel: do not let it pollute the
            # scan-displacement used for scale calibration and wheel-stall detection.
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
        """Search for the pose only while stopped and lost (plan/02:143-145).

        Returns True when a sharp hypothesis peak was found and ``is_lost`` cleared.
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
                # The recovered pose invalidates the accumulated calibration path.
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

        candidates = []
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
                    inliers = int((disp.dists < 0.25).sum())
                    candidates.append((inliers, cx, cy, cand_th))

        candidates.sort(key=lambda c: -c[0])
        best_score, bx, by, bth = candidates[0]

        # Sharp peak: the best hypothesis must beat every hypothesis that is NOT in its
        # own neighbourhood (0.75 m / 3 deg). Neighbouring grid cells of a correct pose
        # score almost identically by construction, so they must not count as rivals.
        second_score = 0
        for score, cx, cy, cand_th in candidates[1:]:
            if (abs(cx - bx) > 0.75 or abs(cy - by) > 0.75
                    or abs(wrap_angle(cand_th - bth)) > math.radians(3.0)):
                second_score = score
                break

        # Sharp distinct peak: inliers >= 35 and clearly better than the rest of the grid
        if best_score >= 35 and (best_score >= second_score * 1.15 or best_score - second_score >= 6):
            best_hypothesis = (bx, by, bth)
            self.x, self.y, self.th = best_hypothesis
            self.var_along = 0.2 ** 2
            self.var_cross = 0.2 ** 2
            self.var_th = np.radians(3.0) ** 2
            self.is_lost = False
            return True

        return False

    def _check_lost_status(self) -> None:
        """Evaluate lost status and the exported speed limit (plan/02:133-147).

        Tiers:
          sigma_cross > 0.4 or sigma_th > 5 deg  -> lost_speed_limit <= 0.4
          sigma_along > 2 m (cross narrow)       -> lost_speed_limit <= 0.6
          sigma_cross > 0.8 or sigma_th > 10 deg -> is_lost, stop, then search
          sigma_along > 5 m                      -> is_lost
          inliers < 15 outside fog for > 1 s     -> is_lost
        """
        align = self.sigma_along > 5.0
        cross = self.sigma_cross > 0.8 or self.sigma_th > math.radians(10.0)
        blind = self._low_inlier_ticks >= 10
        entering = align or cross or blind

        if entering:
            self.is_lost = True
        elif (self.sigma_cross < 0.4 and self.sigma_th < math.radians(5.0)
              and self.sigma_along < 2.0 and self._low_inlier_ticks == 0):
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
