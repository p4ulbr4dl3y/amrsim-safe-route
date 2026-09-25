"""Safety governor and speed limiter module.

Strictly conforms to plan/03-vospriyatie-i-bezopasnost.md, plan/01-schet-i-ploshchadka.md,
and scoring thresholds (standard library math/typing and numpy only).
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from .geom import inside_polygon
    from .perceive import Track
except ImportError:
    from geom import inside_polygon
    from perceive import Track


# Platform and safety constants
R_PLATFORM = 0.9  # Platform radius (m)
R_PEDESTRIAN = 0.3  # Pedestrian radius (m)
DECEL_NORMAL = 1.2  # Normal service deceleration (m/s^2)
DT = 0.1  # Simulation step (s)
V_MAX_DEFAULT = 1.39  # Maximum vehicle speed (m/s)

SLOW_PERSON_GAP = 3.3  # Current clearance below which a human caps v at <= 0.22 m/s
SLOW_PERSON_V = 0.22  # Speed cap next to a person/unknown (plan/03:55)
# The scoring penalty starts at clearance < 3.0 m and |v| > 0.28 m/s, but a command of 0.22
# does not become the true speed instantly: the platform decelerates at 1.2 m/s^2, so from
# 0.95 m/s it needs ~0.6 s (6 ticks) to fall under 0.28. While it is still braking the gap
# keeps closing, and a person walking towards the platform closes it faster still. Engaged at
# the bare 3.3 m threshold the speed is therefore still ~0.35 m/s when the true gap crosses
# 3.0 m: a one-tick `person_near_fast` episode (-0.2, measured on 01/03/04). The margin below
# is added to the engagement gap for a person-like cluster so the speed is already <= 0.28 by
# the time the gap reaches 3.0 m. It is a fraction of the ground covered while the service
# brake releases the ramp (0.28 s per 1 m/s of current speed: ~0.27 m at 0.95 m/s, ~0.39 m at
# cruise), calibrated as the smallest value that removes every observed episode. It is capped
# so that a distant person can never throttle the platform; within the current 1.39 m/s limit
# the cap is a guard only (it binds above ~1.43 m/s), so the calibrated behaviour below is
# exactly K * v_now.
SLOW_PERSON_MARGIN_K = 0.28  # s: extra gap per m/s of current speed (braking-ramp cover)
SLOW_PERSON_MARGIN_MAX = 0.40  # m: hard cap on the anticipatory margin
SLOW_PERSON_MIN_PTS = 4  # a person-like cluster: a lone snow return is never this wide
# The 2 s clearance prediction answers "would this body enter the circle" (plan/03:47). Using
# the already-limited v_odom understates the risk: once the slow cap has collapsed the speed to
# 0.22 m/s the prediction looks safe, the stop never fires, and the platform may crawl for a
# long time inside a stream of pedestrians instead of waiting for it to clear. Predict with the
# speed the path follower actually asked for (never less than the current speed).
STOP_PREDICT_WITH_CANDIDATE = True
STOP_PREDICT_MIN_SPEED = 0.5  # m/s: only while the platform is really rolling fast
STOP_GAP = 0.8  # Current or predicted clearance below which v = 0
# A static object whose honest gap (no 0.3 m pedestrian radius subtracted) falls
# below this is close enough that a misclassification would matter: safety applies
# the human limits to it anyway (task I.5).
STATIC_OBJECT_NEAR_GAP = 1.5
ESTOP_GAP = 1.2  # Confirmed cluster distance enabling emergency braking


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
      horizon_s: prediction horizon (default 2.0)
      dt_step: time step for prediction (default 0.2)

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
    - Status 'lost' when pose is lost AND the platform has already stopped (plan/02:145).
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

    Limits speed according to plan/03 (hardest limit wins):
    1. Predicted clearance to pedestrian/unknown over 2 s < 0.8 m -> v = 0. While the platform
       is still rolling fast (>= STOP_PREDICT_MIN_SPEED) the prediction uses the speed the path
       follower asked for, not the v_odom our own slow cap may have just collapsed, so the crawl
       limit cannot suppress a stop that is genuinely needed (see STOP_PREDICT_WITH_CANDIDATE).
    2. Current clearance to pedestrian/unknown < 0.8 m -> v = 0, held until the predicted
       clearance exceeds 3.3 m (no "wait and go" timeout for dynamic/unknown tracks).
    3. Current clearance to a person-like pedestrian/unknown < 3.3 m, plus an anticipatory
       margin that grows with the current speed (SLOW_PERSON_MARGIN_K*|v_odom|, capped), caps
       v at <= 0.22 (scoring penalty starts at 3.0 m / 0.28 m/s, so this leaves margin for the
       1.2 m/s^2 brake ramp and for the person walking towards the platform).
    4. Three adjacent lidar returns in corridor |y| < 1.0 m inside braking distance -> v = 0.
    5. Unmapped wall (is_wall/map_extra) and static object in the corridor -> treated as an
       obstacle in the clearance and in the corridor test, never ignored.
    6. Fog + unexplained cluster ahead < 5.0 m -> v <= 0.35; fog and clear -> v <= 0.90.
    7. Pose loss (is_lost) -> v = 0; status becomes 'lost' only after the platform has stopped.
    8. estop (2.5 m/s^2) only when a confirmed cluster is closer than 1.2 m, the gap closes and
       the normal 1.2 m/s^2 brake cannot stop in time. Never above 1.5 m (false estop = -1).
    """

    NOTE_ORDER = (
        "blocked_wheels",
        "stop_person",
        "stop_object",
        "stop_corridor",
        "slow_person",
        "lost",
        "map",
        "fog",
        "zone",
        "dock",
    )

    def __init__(self, v_top: float = V_MAX_DEFAULT, dt: float = DT):
        self.v_top = float(v_top)
        self.dt = float(dt)

        # Person-stop latch: after stopping for a person/unknown track, hold v = 0 until the
        # predicted clearance to every human track exceeds 3.3 m. A "waited 8 s then went"
        # timeout for dynamic/unknown tracks is explicitly forbidden (plan/03:73).
        self._person_hold: bool = False
        self._person_note: str = ""
        self._last_human_pred: float = math.inf
        self._lost_human_ticks: int = 0
        # Previous minimum estimated clearance, used to confirm a closing gap for estop.
        self._prev_min_cl: Optional[float] = None

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

    def _compose_note(self, notes: Dict[str, str]) -> str:
        """Join active reasons into one stable <= 200 char string, no flicker."""
        parts = [notes[k] for k in self.NOTE_ORDER if k in notes]
        if not parts:
            return ""
        return " ".join(parts)[:200]

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
        sigma_cross: float = 0.0,
    ) -> Tuple[float, float, str, str]:
        """Evaluate safety limits and determine safe command (v, w), status, and note.

        Args:
          v_cand: candidate forward velocity from path follower (m/s)
          w_cand: candidate angular velocity from path follower (rad/s)
          v_odom: current forward velocity from odometry (m/s)
          w_odom: current angular velocity from odometry (rad/s)
          pose: world pose (x, y, th)
          odom_pose: pure odometry pose (ox, oy, oth)
          tracks: active tracks from perception (including unmapped walls, is_wall=True)
          ranges: lidar beam ranges (360,)
          rel_angles: relative beam angles in robot frame (360,)
          zones: speed limit zones [(polygon, v_max), ...]
          is_fog: whether fog condition is active
          is_arrived: whether dock target reached
          is_lost: whether localizer lost (v forced to 0)
          blocked_wheels: whether wheel slip/wall contact detected
          perception_note: existing note from perception (e.g. map_missing/map_extra)
          remaining_dist: remaining distance to dock, metres
          sigma_cross: lateral pose sigma, reported in the `lost s_lat=` note

        Returns:
          (v_safe, w_safe, status, note)
        """
        x, y, th = pose
        _, _, oth = odom_pose
        v_now = abs(v_odom)

        v_lim = self.v_top
        stop_reason: Optional[str] = None
        notes: Dict[str, str] = {}
        is_estop: bool = False

        # Perception note (map_missing / map_extra) stays visible for the whole cause.
        if perception_note:
            notes["map"] = perception_note

        # 1. Blocked wheels / wall contact condition (plan/03:122-131)
        if blocked_wheels:
            stop_reason = "blocked_wheels"
            notes["blocked_wheels"] = "blocked_wheels"
            v_lim = 0.0

        # 2. Zone speed limits: current position and lookahead 3.0 m ahead
        cos_th = math.cos(th)
        sin_th = math.sin(th)
        zone_curr = self.get_zone_limit(x, y, zones)
        zone_ahead = self.get_zone_limit(x + 3.0 * cos_th, y + 3.0 * sin_th, zones)
        zone_effective = min(zone_curr, zone_ahead)
        v_lim = min(v_lim, zone_effective)
        if zone_effective < self.v_top:
            notes["zone"] = f"zone v={zone_effective:.2f}"

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
                notes["fog"] = "fog_cluster"
            else:
                # Fog and clear ahead: up to 0.9 m/s to satisfy short-leg deadline
                v_lim = min(v_lim, 0.90)
                notes["fog"] = "fog_clear"

        # 4. Track clearances and predictive TTC. Unmapped walls (is_wall=True, map_extra)
        #    MUST count as obstacles here, not be skipped.
        d_stop_corridor = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + 0.6

        min_overall_clearance = math.inf
        human_pred_min = math.inf
        person_stop = False
        person_slow = False
        person_slow_cl = math.inf
        front_hit = False  # a cluster is directly ahead inside the corridor
        # True-contact flag: the shortest *centre-to-point* distance over every cluster.
        # The braking path is about translation, but the hull is a 0.9 m disc, so an
        # in-place turn is safe while the nearest point stays outside the disc. This is
        # what decides whether w may be kept while the corridor holds v = 0.
        min_point_dist = math.inf

        for tr in tracks:
            pts = tr.pts
            if pts is None or len(pts) == 0:
                continue

            d_pts = float(np.hypot(pts[:, 0], pts[:, 1]).min())
            if d_pts < min_point_dist:
                min_point_dist = d_pts

            is_human = tr.is_pedestrian or tr.is_unknown
            cl = calculate_clearance(pts, is_pedestrian=is_human)
            if cl < min_overall_clearance:
                min_overall_clearance = cl

            ahead = (pts[:, 0] > 0.0) & (np.abs(pts[:, 1]) < R_PLATFORM + 0.35)
            if (ahead & (pts[:, 0] < d_stop_corridor)).any():
                front_hit = True

            if is_human:
                ped_ahead = (pts[:, 0] > 0.0) & (pts[:, 0] < 4.5) & (np.abs(pts[:, 1]) < 1.8)
                person_like = len(pts) >= SLOW_PERSON_MIN_PTS
                slow_gap = SLOW_PERSON_GAP
                if person_like:
                    slow_gap += min(SLOW_PERSON_MARGIN_K * v_now, SLOW_PERSON_MARGIN_MAX)
                # While the platform is still rolling fast the prediction uses the speed the
                # path follower asked for, not the already-limited v_odom. Predicting with a
                # speed that our own slow cap has just collapsed would hide a genuinely closing
                # person: the stop would never fire and the platform would crawl for a long
                # time inside a stream of pedestrians instead of waiting for it to clear
                # (measured on 03 seed 21). Once the platform is already slow (<= 0.5 m/s) the
                # plan's own thresholds apply unchanged, so a 2.5 m gap stays a 0.22 m/s cap.

                # A. Current or predicted (2 s horizon) clearance < 0.8 m -> stop
                v_pred = v_now
                if STOP_PREDICT_WITH_CANDIDATE and v_now >= STOP_PREDICT_MIN_SPEED:
                    v_pred = max(v_now, abs(v_cand))
                pred_cl, _ = predict_ttc_clearance(
                    tr, v_platform=v_pred, oth=oth, horizon_s=2.0, dt_step=0.2
                )
                if pred_cl < human_pred_min:
                    human_pred_min = pred_cl

                if cl < STOP_GAP or pred_cl < STOP_GAP:
                    stop_reason = "stop_person"
                    notes["stop_person"] = f"stop_person d={max(0.0, min(cl, pred_cl)):.1f}"
                    v_lim = 0.0
                    person_stop = True
                # B. Person ahead in corridor within 4.5 m, or clearance below the engagement
                #    gap. The engagement gap is the plan's 3.3 m plus an anticipatory margin on
                #    a person-like cluster: the platform cannot drop to 0.22 m/s instantly, and
                #    without the margin the true 3.0 m / 0.28 m/s scoring line is crossed while
                #    the brake is still releasing speed (one-tick `person_near_fast`). A lone or
                #    paired snow return (few points) is not person-like and gets no margin, so
                #    snow never throttles the platform (plan/03:18, plan/03:55).
                elif ped_ahead.any() or cl < slow_gap:
                    person_slow = True
                    if cl < person_slow_cl:
                        person_slow_cl = cl
            else:
                # Confirmed static object (is_static_object) or unmapped wall (is_wall): the
                # human limits above never apply here. Two stop conditions only (plan/03:56,
                # plan/04:32-45):
                #   a) the cluster really sits in the swept corridor inside the braking reach;
                #   b) the honest gap (this branch already omits the 0.3 m pedestrian radius)
                #      of a point in the swept frontal band is below STOP_GAP, so even from
                #      rest the normal brake could no longer stop in time.
                # Otherwise the object does not limit v: the route plans a side offset around
                # it (plan/04:3, plan/04:29-30).
                # Near-miss guard (task I.5): a *static object* whose honest gap is below
                # STATIC_OBJECT_NEAR_GAP still gets the human limits (<= 0.22, and 0 below
                # STOP_GAP). If the classifier confused a person with a pallet, the gap is
                # what protects, not the label (plan/03:3, plan/03:47). The dock pallet on
                # 04 keeps a ~1.9 m honest gap and is unaffected; walls are not covered.
                cl_honest = calculate_clearance(pts, is_pedestrian=False)
                if tr.is_static_object and cl_honest < STATIC_OBJECT_NEAR_GAP:
                    pred_cl, _ = predict_ttc_clearance(
                        tr, v_platform=v_now, oth=oth, horizon_s=2.0, dt_step=0.2
                    )
                    if cl_honest < STOP_GAP or pred_cl < STOP_GAP:
                        stop_reason = stop_reason or "stop_object"
                        notes["stop_object"] = "stop_object"
                        v_lim = 0.0
                    elif cl_honest < SLOW_PERSON_GAP:
                        v_lim = min(v_lim, SLOW_PERSON_V)

                if remaining_dist > 0.35:
                    in_corridor = ahead & (pts[:, 0] < d_stop_corridor)
                    front_gap = math.inf
                    if ahead.any():
                        front_gap = calculate_clearance(pts[ahead], is_pedestrian=False)
                    if in_corridor.any() or front_gap < STOP_GAP:
                        stop_reason = stop_reason or "stop_object"
                        notes["stop_object"] = "stop_object"
                        v_lim = 0.0

        if person_slow and not person_stop:
            v_lim = min(v_lim, SLOW_PERSON_V)
            notes["slow_person"] = f"slow_person d={max(0.0, person_slow_cl):.1f}"

        # 5. Person-stop latch (replaces the forbidden timeout). While held, v stays 0 until
        #    the predicted clearance to every human track is greater than 3.3 m. A brief guard
        #    keeps the brake applied through fog dropout (plan/03:20), never resumes motion.
        saw_human = math.isfinite(human_pred_min)
        if saw_human:
            self._last_human_pred = human_pred_min
            self._lost_human_ticks = 0

        if person_stop and not self._person_hold:
            self._person_hold = True
            self._person_note = notes.get("stop_person", "stop_person")

        if self._person_hold:
            if not saw_human:
                self._lost_human_ticks += 1
                if self._lost_human_ticks <= 10:
                    human_pred_min = self._last_human_pred
            if human_pred_min > SLOW_PERSON_GAP:
                self._person_hold = False
                self._person_note = ""
            else:
                stop_reason = stop_reason or "stop_person"
                v_lim = 0.0
                notes["stop_person"] = self._person_note or notes.get("stop_person", "stop_person")

        # 6. Lidar raw swept footprint corridor check (|y| < 1.0 m inside braking reach)
        if remaining_dist > 0.35:
            r = np.asarray(ranges, dtype=float)
            rel = np.asarray(rel_angles, dtype=float)
            if len(r) > 0 and len(rel) == len(r):
                reach = R_PLATFORM + (v_now * v_now) / (2.0 * DECEL_NORMAL) + v_now * self.dt + 0.25
                with np.errstate(invalid="ignore"):
                    px = r * np.cos(rel)
                    py = r * np.sin(rel)
                    corridor_hit = (
                        np.isfinite(r) & (px > 0.0) & (px < reach) & (np.abs(py) < R_PLATFORM + 0.1)
                    )
                    # Three adjacent beams: real obstacle, not snowflake
                    three_hit = corridor_hit & np.roll(corridor_hit, 1) & np.roll(corridor_hit, -1)
                    if three_hit.any():
                        stop_reason = stop_reason or "too_close"
                        v_lim = 0.0
                        notes["stop_corridor"] = "stop_corridor"

        # 7. estop: emergency 2.5 m/s^2 brake only when a confirmed cluster is closer than
        #    1.2 m, the gap is closing and the normal 1.2 m/s^2 brake cannot stop in time.
        #    False estop at gap >= 1.5 m costs -1, so stay strictly inside 1.2 m.
        closing = True
        if self._prev_min_cl is not None and math.isfinite(self._prev_min_cl):
            closing = min_overall_clearance < self._prev_min_cl - 0.005
        stopping_normal = (v_now * v_now) / (2.0 * DECEL_NORMAL) + v_now * self.dt
        if (
            math.isfinite(min_overall_clearance)
            and min_overall_clearance < ESTOP_GAP
            and min_overall_clearance < stopping_normal
            and front_hit
            and v_now > 0.05
            and closing
        ):
            is_estop = True
            v_lim = 0.0
            if stop_reason is None:
                stop_reason = "estop"
        self._prev_min_cl = min_overall_clearance if math.isfinite(min_overall_clearance) else None

        # 8. Arbitrate forward velocity v
        if is_lost:
            # Pose unknown: stop and integrate only confirmed scan-to-scan motion (plan/02:145).
            v_safe = 0.0
            notes["lost"] = f"lost s_lat={sigma_cross:.1f}"
        elif stop_reason is not None and remaining_dist > 0.35:
            v_safe = 0.0
        else:
            v_safe = max(0.0, min(v_cand, v_lim))

        # 9. Arbitrate angular velocity w. Rotating on the spot beside a body is allowed
        #    (plan/03:71, plan/03:76): the hull is a 0.9 m disc, so an in-place turn cannot
        #    bring it closer to a cluster it is not already touching. A wall or an object
        #    in the swept corridor therefore keeps v = 0 but must NOT freeze w: the route
        #    has already planned the A* bypass around it, and zeroing w pins the platform
        #    in front of the body forever -- the route command to steer away is discarded
        #    and the mission times out (own s2_container_block seed 7: frozen at
        #    (190.8, 93.0) from t=154 to 252 while route asked v=1.39 w=-0.49). Only a
        #    real hull contact (a cluster point inside the disc), an emergency stop or a
        #    wheel jam rules rotation out.
        hull_contact = math.isfinite(min_point_dist) and min_point_dist < R_PLATFORM + 0.05
        if is_estop or blocked_wheels or hull_contact:
            w_safe = 0.0
        else:
            w_safe = w_cand

        # 10. Arrival hold: hold the dock command at zero speed
        if is_arrived:
            v_safe = 0.0
            w_safe = 0.0
            if not notes:
                notes["dock"] = "dock"

        # 11. Status determination
        is_slowed = v_safe <= 0.35 and v_safe > 0.0
        is_stopped_flag = (stop_reason is not None) or (v_safe == 0.0 and w_safe == 0.0)

        # Simulator status: strictly 'moving' whenever |v_odom| >= 0.05
        status = determine_status(
            v_odom=v_odom,
            w_odom=w_odom,
            is_arrived=is_arrived,
            is_lost=is_lost,
            is_stopped=is_stopped_flag,
            is_slowed=is_slowed,
            is_estop=is_estop,
            allow_slowed=False,  # strictly 'moving' when moving to prevent status_mismatch
        )

        return v_safe, w_safe, status, self._compose_note(notes)
