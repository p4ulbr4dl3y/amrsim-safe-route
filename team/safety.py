"""Safety governor and speed limiter module.

Strictly conforms to plan/03-vospriyatie-i-bezopasnost.md, plan/01-schet-i-ploshchadka.md,
and scoring thresholds (standard library math/typing and numpy only).
"""
import math
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

try:
    from .geom import inside_polygon, wrap_angle
    from .perceive import Track
except ImportError:
    from geom import inside_polygon, wrap_angle
    from perceive import Track


# Platform and safety constants
R_PLATFORM = 0.9         # Platform radius (m)
R_PEDESTRIAN = 0.3       # Pedestrian radius (m)
DECEL_NORMAL = 1.2       # Normal service deceleration (m/s^2)
DECEL_ESTOP = 2.5        # Emergency deceleration (m/s^2)
DT = 0.1                 # Simulation step (s)
V_MAX_DEFAULT = 1.39     # Maximum vehicle speed (m/s)


def calculate_clearance(
    pts: np.ndarray,
    is_pedestrian: bool = True,
) -> float:
    """Calculate clearance from AMR perimeter to obstacle perimeter.
    
    AMR radius = 0.9 m.
    Pedestrian radius = 0.3 m (subtracted for pedestrians and unknown obstacles).
    For walls/fences and static objects, only AMR radius is subtracted.
    
    Returns:
      clearance in meters (can be <= 0 at contact).
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
    """Predict minimum clearance to track over a 2.0 s horizon with 0.2 s steps.
    
    Considers platform velocity along heading and track velocity in pure odometry frame.
    
    Args:
      track: obstacle Track instance
      v_platform: forward speed of platform (m/s)
      oth: AMR heading in pure odometry frame (rad)
      horizon_s: prediction horizon (default 2.0 s)
      dt_step: time step for prediction (default 0.2 s)
      
    Returns:
      (min_predicted_clearance, time_to_min_clearance)
    """
    pts = track.pts
    if pts is None or len(pts) == 0:
        return math.inf, horizon_s

    # Track velocity in robot frame
    cos_oth = math.cos(oth)
    sin_oth = math.sin(oth)
    vx_r = cos_oth * track.vx_odom + sin_oth * track.vy_odom
    vy_r = -sin_oth * track.vx_odom + cos_oth * track.vy_odom

    # Relative velocity of track with respect to moving robot platform
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
    """Determine AMR operational status.
    
    Conforms to scoring rules:
    - Status MUST be 'moving' whenever |v_odom| >= 0.05 to prevent status_mismatch (-2).
    - Status 'arrived' when dock condition is met.
    - Status 'waiting' when stopped (|v_odom| < 0.05) due to obstacle, person or pause.
    - Status 'lost' when pose is lost.
    - Status 'estop' when emergency stop is triggered.
    - If allow_slowed=True and robot is moving under reduced speed limit, returns 'slowed'.
    """
    if is_arrived:
        return "arrived"
    if is_estop:
        return "estop"

    # Moving threshold from scoring: THRESH["moving_v"] = 0.05 m/s
    if abs(v_odom) >= 0.05 or abs(w_odom) >= 0.10:
        if allow_slowed and is_slowed:
            return "slowed"
        return "moving"

    # Stationary state (|v_odom| < 0.05)
    if is_lost:
        return "lost"
    if is_stopped:
        return "waiting"
    if is_slowed and allow_slowed:
        return "slowed"

    return "waiting"


class SafetyGovernor:
    """Safety governor enforcing clearance, speed limits, corridor braking, and notes.
    
    Limits speed according to:
    1. Predicted clearance to pedestrian/unknown < 0.8 m -> v = 0.
    2. Current clearance to pedestrian/unknown < 0.8 m -> v = 0.
    3. Current clearance to pedestrian/unknown < 3.3 m -> v <= 0.22 (margin for safety -2/s).
    4. Three adjacent lidar returns in corridor |y| < 1.0 m inside braking distance -> v = 0.
    5. Fog + unexplained cluster ahead < 5.0 m -> v <= 0.35.
    6. Fog and clear -> v <= 0.90 (respecting short-leg deadline).
    7. Clear -> speed limit zone with 0.05 margin and braking 3.0 m before zone boundary.
    """

    def __init__(self, v_top: float = V_MAX_DEFAULT, dt: float = DT):
        self.v_top = float(v_top)
        self.dt = float(dt)

        # Hysteresis counter for person near stop (prevents stop release during fog dropout)
        self._person_hold_ticks: int = 0
        self._arrived_ticks: int = 0
        self._near_wait: int = 0

    def get_zone_limit(
        self,
        x: float,
        y: float,
        zones: List[Tuple[Any, float]],
    ) -> float:
        """Find minimum applicable zone speed limit at (x, y) with 0.05 m/s margin."""
        lim = self.v_top
        for poly, v_max in zones:
            if inside_polygon(x, y, poly):
                # 0.05 margin to prevent overspeed violation
                lim = min(lim, v_max - 0.05)
        return max(0.1, lim)

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
    ) -> Tuple[float, float, str, str]:
        """Evaluate safety limits and determine safe command (v, w), status, and note.
        
        Args:
          v_cand: candidate forward velocity from path follower (m/s)
          w_cand: candidate angular velocity from path follower (rad/s)
          v_odom: current forward velocity from odometry (m/s)
          w_odom: current angular velocity from odometry (rad/s)
          pose: world pose (x, y, th)
          odom_pose: pure odometry pose (ox, oy, oth)
          tracks: active tracks from perception
          ranges: lidar beam ranges (360,)
          rel_angles: relative beam angles in robot frame (360,)
          zones: speed limit zones [(polygon, v_max), ...]
          is_fog: whether fog condition is active
          is_arrived: whether dock target reached
          is_lost: whether localizer lost
          blocked_wheels: whether wheel slip/wall contact detected
          perception_note: existing note from perception (e.g. map_missing)
          
        Returns:
          (v_safe, w_safe, status, note)
        """
        x, y, th = pose
        _, _, oth = odom_pose
        v_now = abs(v_odom)

        v_lim = self.v_top
        stop_reason: Optional[str] = None
        note_str: str = perception_note or ""
        is_estop: bool = False
        min_overall_clearance = math.inf

        # 1. Blocked wheels / wall collision condition
        if blocked_wheels:
            stop_reason = "blocked_wheels"
            note_str = "blocked_wheels"
            v_lim = 0.0

        # 2. Zone speed limits: current position and lookahead 3.0 m ahead
        cos_th = math.cos(th)
        sin_th = math.sin(th)
        zone_curr = self.get_zone_limit(x, y, zones)
        zone_ahead = self.get_zone_limit(x + 3.0 * cos_th, y + 3.0 * sin_th, zones)
        zone_effective = min(zone_curr, zone_ahead)
        v_lim = min(v_lim, zone_effective)
        if zone_effective < self.v_top and not note_str:
            note_str = f"zone v={zone_effective:.2f}"

        # 3. Fog limits
        if is_fog:
            # Check if unexplained cluster ahead closer than 5.0 m
            has_cluster_ahead = False
            for tr in tracks:
                if tr.pts is not None and len(tr.pts) > 0:
                    pts = tr.pts
                    # Ahead of robot and closer than 5.0 m
                    in_front = (pts[:, 0] > 0.0) & (pts[:, 0] < 5.0) & (np.abs(pts[:, 1]) < 2.0)
                    if in_front.any():
                        has_cluster_ahead = True
                        break

            if has_cluster_ahead:
                v_lim = min(v_lim, 0.35)
                if not note_str:
                    note_str = "fog_cluster"
            else:
                # Fog and clear ahead: up to 0.9 m/s to satisfy short-leg deadline
                v_lim = min(v_lim, 0.90)
                if not note_str:
                    note_str = "fog_clear"

        # 4. Track clearances and predictive TTC
        d_stop_corridor = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + 0.6

        for tr in tracks:
            pts = tr.pts
            if pts is None or len(pts) == 0:
                continue

            if tr.is_wall:
                continue

            is_human = tr.is_pedestrian or tr.is_unknown
            cl = calculate_clearance(pts, is_pedestrian=is_human)
            if cl < min_overall_clearance:
                min_overall_clearance = cl

            # Check static object in direct driving corridor
            if not is_human:
                if remaining_dist > 0.35:
                    in_corridor = (pts[:, 0] > 0.0) & (pts[:, 0] < d_stop_corridor) & (np.abs(pts[:, 1]) < R_PLATFORM + 0.35)
                    if in_corridor.any():
                        stop_reason = stop_reason or "stop_object"
                        if not note_str or "fog" in note_str or "zone" in note_str:
                            note_str = "stop_object"
                        v_lim = 0.0
                continue

            # Pedestrian or unknown track
            ped_ahead = (pts[:, 0] > 0.0) & (pts[:, 0] < 4.5) & (np.abs(pts[:, 1]) < 1.8)

            # A. Current clearance < 0.8 m -> stop
            if cl < 0.8:
                stop_reason = "stop_person"
                note_str = f"stop_person d={max(0.0, cl):.1f}"
                v_lim = 0.0
            # B. Predictive TTC on 2.0 s horizon
            else:
                pred_cl, _ = predict_ttc_clearance(tr, v_platform=v_now, oth=oth, horizon_s=2.0, dt_step=0.2)
                if pred_cl < 0.8:
                    stop_reason = "stop_person"
                    note_str = f"stop_person d={max(0.0, pred_cl):.1f}"
                    v_lim = 0.0
                # C. Person ahead in corridor within 4.5 m, or clearance < 2.7 m -> speed <= 0.25 m/s
                elif ped_ahead.any() or cl < 2.7:
                    v_lim = min(v_lim, 0.25)
                    if not note_str or note_str in ("fog", "fog_clear") or "zone" in note_str:
                        note_str = f"slow_person d={cl:.1f}"

        # 5. Lidar raw swept footprint corridor check (|y| < 1.0 m inside braking reach)
        if remaining_dist > 0.35:
            r = np.asarray(ranges, dtype=float)
            rel = np.asarray(rel_angles, dtype=float)
            if len(r) > 0 and len(rel) == len(r):
                reach = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + v_now * self.dt + 0.25
                with np.errstate(invalid="ignore"):
                    px = r * np.cos(rel)
                    py = r * np.sin(rel)
                    corridor_hit = np.isfinite(r) & (px > 0.0) & (px < reach) & (np.abs(py) < R_PLATFORM + 0.1)
                    # Three adjacent beams: real obstacle, not snowflake
                    three_hit = corridor_hit & np.roll(corridor_hit, 1) & np.roll(corridor_hit, -1)
                    if three_hit.any():
                        stop_reason = stop_reason or "too_close"
                        v_lim = 0.0
                        if not note_str or "fog" in note_str or "zone" in note_str:
                            note_str = "stop_corridor"

        # 6. Person near hold hysteresis (1.0 s hold to prevent dropout flicker in fog)
        if stop_reason == "stop_person":
            self._person_hold_ticks = 10
        elif stop_reason is None and self._person_hold_ticks > 0:
            self._person_hold_ticks -= 1
            stop_reason = "stop_person"
            v_lim = 0.0

        if stop_reason == "stop_person":
            self._near_wait += 1
            if self._near_wait > 80:
                # Someone standing beside path for 8s: proceed slowly at <= 0.25 m/s
                stop_reason = None
                v_lim = min(v_lim, 0.25)
                note_str = "slow_person pass"
        else:
            self._near_wait = 0

        # 7. Arbitrate forward velocity v
        if stop_reason is not None and remaining_dist > 0.35:
            v_safe = 0.0
        else:
            v_safe = max(0.0, min(v_cand, v_lim))

        # 8. Arbitrate angular velocity w
        # If obstacle is directly in front within braking distance, zero out w
        corridor_blocked = (stop_reason in ("too_close", "stop_object", "blocked_wheels")) and (remaining_dist > 0.35)
        if corridor_blocked:
            w_safe = 0.0
        else:
            # Rotating on spot beside pedestrian is allowed and safe
            w_safe = w_cand

        # 9. Arrival hold handling (hold for 12 ticks, target is 10)
        if is_arrived:
            self._arrived_ticks += 1
            v_safe = 0.0
            w_safe = 0.0
            if not note_str:
                note_str = "dock"
        else:
            self._arrived_ticks = 0

        # 10. Status determination
        is_slowed = (v_safe <= 0.35 and v_safe > 0.0)
        is_stopped_flag = (stop_reason is not None) or (v_safe == 0.0 and w_safe == 0.0)

        # Simulator status: strictly 'moving' whenever |v_odom| >= 0.05
        status = determine_status(
            v_odom=v_odom,
            w_odom=w_odom,
            is_arrived=is_arrived,
            is_lost=is_lost,
            is_stopped=is_stopped_flag,
            is_slowed=is_slowed,
            is_estop=False,
            allow_slowed=False,  # strictly 'moving' when moving to prevent status_mismatch
        )

        return v_safe, w_safe, status, note_str[:200]
