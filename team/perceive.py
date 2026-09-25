"""Perception module: unexplained lidar clustering, odometry tracking, classification, map discrepancies.

Strictly conforms to plan/03-vospriyatie-i-bezopasnost.md and isolation requirements
(standard library math/typing and numpy only).
"""
import math
from typing import Dict, List, Optional, Set, Tuple, Union

import numpy as np

try:
    from .geom import filter_segs_aabb, raycast, rot2d, seg_dist, wrap_angle
except ImportError:
    from geom import filter_segs_aabb, raycast, rot2d, seg_dist, wrap_angle


class Track:
    """Obstacle track maintained in pure odometry coordinates (ox, oy, oth).
    
    Tracking in pure odometry prevents artificial position jumps caused by
    GNSS corrections or scan-matching pose updates.
    """
    __slots__ = (
        "track_id",
        "ox", "oy",              # Centroid in pure odometry frame (m)
        "hist",                  # History of (ox, oy) coordinates
        "seen",                  # History of detection hits (1) and misses (0)
        "dyn",                   # True (pedestrian), False (static/wall), None (unknown)
        "class_label",           # "pedestrian", "wall_extra", "static_object", "unknown"
        "still_ticks",           # Consecutive ticks without motion while robot still
        "vx_odom", "vy_odom",    # Estimated velocity in odometry frame (m/s)
        "pts",                   # Current points in robot frame (N, 2)
        "length",                # Cluster length along principal axis (m)
        "thickness",             # Cluster thickness 80th percentile across axis (m)
        "coast_ticks",           # Ticks since last sensor detection
    )

    def __init__(self, track_id: int, ox: float, oy: float, pts: Optional[np.ndarray] = None):
        self.track_id = track_id
        self.ox = float(ox)
        self.oy = float(oy)
        self.hist: List[Tuple[float, float]] = [(self.ox, self.oy)]
        self.seen: List[int] = [1]
        self.dyn: Optional[bool] = None
        self.class_label: str = "unknown"
        self.still_ticks: int = 0
        self.vx_odom: float = 0.0
        self.vy_odom: float = 0.0
        self.pts: np.ndarray = pts if pts is not None else np.empty((0, 2), dtype=float)
        self.length: float = 0.0
        self.thickness: float = 0.0
        self.coast_ticks: int = 0

    @property
    def is_pedestrian(self) -> bool:
        return self.class_label == "pedestrian" or self.dyn is True

    @property
    def is_wall(self) -> bool:
        return self.class_label == "wall_extra"

    @property
    def is_static_object(self) -> bool:
        return self.class_label == "static_object" or (self.dyn is False and self.class_label != "wall_extra")

    @property
    def is_unknown(self) -> bool:
        return self.dyn is None and self.class_label == "unknown"


def fit_cluster_geometry(pts: np.ndarray) -> Tuple[float, float]:
    """Calculate length and 80th-percentile thickness using PCA (SVD).
    
    pts: (N, 2) array of 2D points in Cartesian plane.
    Returns:
      (length, thickness) in meters.
    """
    if len(pts) < 2:
        return 0.0, 0.0
    if len(pts) == 2:
        length = float(np.hypot(pts[1, 0] - pts[0, 0], pts[1, 1] - pts[0, 1]))
        return length, 0.0

    c = pts.mean(axis=0)
    centered = pts - c
    try:
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        along = centered @ vt[0]
        across = centered @ vt[1]
        length = float(along.max() - along.min())
        thickness = float(np.percentile(np.abs(across), 80))
        return length, thickness
    except Exception:
        length = float(np.ptp(pts[:, 0]) + np.ptp(pts[:, 1]))
        return length, 0.0


def is_wall_cluster(pts: np.ndarray) -> bool:
    """Determine if cluster geometry represents an unmapped wall or fence.
    
    Criterion: length > 1.0 m and 80th-percentile thickness < 0.1 m.
    """
    if len(pts) < 3:
        return False
    length, thickness = fit_cluster_geometry(pts)
    return length > 1.0 and thickness < 0.10


def is_wall_continuation(pts: np.ndarray, wall_point_clouds: List[np.ndarray]) -> bool:
    """Determine if a short cluster continues an unmapped wall.
    
    Criterion: cluster is closer than 0.6 m to a known wall cluster and its
    80th-percentile lateral deviation from the wall principal axis is < 0.15 m.
    """
    if len(pts) == 0 or not wall_point_clouds:
        return False

    for w_pts in wall_point_clouds:
        if len(w_pts) < 3:
            continue
        # Distance between cluster points and wall points
        dists = np.hypot(pts[:, None, 0] - w_pts[None, :, 0], pts[:, None, 1] - w_pts[None, :, 1])
        if float(dists.min()) > 0.6:
            continue

        c = w_pts.mean(axis=0)
        try:
            _, _, vt = np.linalg.svd(w_pts - c, full_matrices=False)
            proj_across = (pts - c) @ vt[1]
            if float(np.percentile(np.abs(proj_across), 80)) < 0.15:
                return True
        except Exception:
            continue

    return False


class Perception:
    """Perception pipeline for AMR navigation.
    
    - Isolates dynamic tracks into pure odometry frame (ox, oy, oth).
    - Clusters unexplained lidar returns (> 0.35 + sigma_pose shorter than map, > 0.4m from map wall).
    - Snow filtering: isolated single beams rejected.
    - Classifies tracks: pedestrian, wall_extra, static_object, unknown.
    - Preserves dynamic tracks across dropouts (up to 1.0s) with velocity prediction.
    - Detects map discrepancies: map_missing (sensed demolished walls), map_extra (new obstacles).
    """

    def __init__(self, dt: float = 0.1):
        self.dt = float(dt)
        self.tracks: List[Track] = []
        self._next_track_id: int = 1

        # Map discrepancy tracking
        self.removed_segment_ids: Set[int] = set()
        self._missing_wall_votes: Dict[int, int] = {}
        self.note: str = ""

    def reset(self) -> None:
        """Reset internal tracking state."""
        self.tracks.clear()
        self._next_track_id = 1
        self.removed_segment_ids.clear()
        self._missing_wall_votes.clear()
        self.note = ""

    def step(
        self,
        ranges: np.ndarray,
        rel_angles: np.ndarray,
        pose: Tuple[float, float, float],
        odom_pose: Tuple[float, float, float],
        map_segs: np.ndarray,
        sigma_pose: float = 0.0,
        is_fog: bool = False,
        v_odom: float = 0.0,
        scan_inliers: int = 0,
    ) -> List[Track]:
        """Process lidar scan and update obstacle tracks and map discrepancies.
        
        Args:
          ranges: 1D array of lidar ranges (360 beams, 1 deg step)
          rel_angles: 1D array of beam angles in robot frame (rad)
          pose: estimated world pose (x, y, th)
          odom_pose: pure odometry pose (ox, oy, oth)
          map_segs: (M, 4) line segments of mapped buildings
          sigma_pose: current localizer pose uncertainty (m)
          is_fog: whether fog condition is active
          v_odom: current forward velocity from odometry (m/s)
          scan_inliers: number of scan-matching inliers from localizer
          
        Returns:
          Active confirmed tracks.
        """
        x, y, th = pose
        ox, oy, oth = odom_pose
        r = np.asarray(ranges, dtype=float)
        rel = np.asarray(rel_angles, dtype=float)
        n = len(r)

        if n == 0 or map_segs is None:
            return []

        # 1. Expected ranges from map walls
        # Filter active segments (exclude removed segments)
        active_segs = map_segs
        if self.removed_segment_ids:
            mask = np.ones(len(map_segs), dtype=bool)
            for sid in self.removed_segment_ids:
                if 0 <= sid < len(map_segs):
                    mask[sid] = False
            active_segs = map_segs[mask]

        exp = raycast(x, y, th + rel, active_segs)

        # 2. Candidate unexplained beams: shorter than map by margin
        margin = 0.35 + min(1.5, max(0.0, sigma_pose))
        bad = np.isfinite(r) & (r < exp - margin)

        # Filter out beams whose end points fall within 0.4m of mapped wall
        if bad.any():
            bad_idx = np.flatnonzero(bad)
            beam_world_angles = th + rel[bad_idx]
            wx = x + r[bad_idx] * np.cos(beam_world_angles)
            wy = y + r[bad_idx] * np.sin(beam_world_angles)
            wall_margin = max(0.85, 0.4 + min(1.5, 2.0 * sigma_pose))
            near_wall = seg_dist(wx, wy, active_segs) < wall_margin
            bad[bad_idx[near_wall]] = False

        # 3. Snow filter: isolated single short returns (0.3-3.0m) discarded
        if bad.any():
            bad_idx = np.flatnonzero(bad)
            # Check Cartesian distance to immediate neighbours in angular sweep
            cos_rel = np.cos(rel)
            sin_rel = np.sin(rel)
            px_all = r * cos_rel
            py_all = r * sin_rel

            for k in bad_idx:
                prev_k = (k - 1) % n
                next_k = (k + 1) % n
                has_prev = bad[prev_k] and (math.hypot(px_all[k] - px_all[prev_k], py_all[k] - py_all[prev_k]) < 0.6)
                has_next = bad[next_k] and (math.hypot(px_all[k] - px_all[next_k], py_all[k] - py_all[next_k]) < 0.6)
                if not (has_prev or has_next):
                    # Lone ray: snow artifact
                    bad[k] = False

        # 4. Assemble clusters
        finite = np.isfinite(r)
        breaks = finite & ~bad  # Ray explained by map ends the object
        clusters: List[List[int]] = []

        if bad.any():
            start = int(np.argmax(breaks)) if breaks.any() else int(np.argmax(~finite)) if (~finite).any() else 0
            run: List[int] = []
            skipped = 0

            for j in range(1, n + 1):
                k = (start + j) % n
                if bad[k]:
                    if not run:
                        run.append(k)
                        skipped = 0
                        continue
                    # Check gap in Cartesian plane
                    gap = math.hypot(
                        r[k] * math.cos(rel[k]) - r[run[-1]] * math.cos(rel[run[-1]]),
                        r[k] * math.sin(rel[k]) - r[run[-1]] * math.sin(rel[run[-1]]),
                    )
                    if gap < 0.6:
                        run.append(k)
                        skipped = 0
                        continue

                # Up to 2 dropped / NaN beams do not break the cluster (fog resilience)
                if run and skipped < 2:
                    nxt = [(start + j + d) % n for d in (1, 2)]
                    # Check if next beam resumes cluster within 0.6m
                    can_resume = not finite[k] or any(
                        bad[q] and (math.hypot(
                            r[q] * math.cos(rel[q]) - r[run[-1]] * math.cos(rel[run[-1]]),
                            r[q] * math.sin(rel[q]) - r[run[-1]] * math.sin(rel[run[-1]])
                        ) < 0.6)
                        for q in nxt
                    )
                    if can_resume:
                        skipped += 1
                        continue

                if len(run) >= 2:
                    clusters.append(run)
                run = [k] if bad[k] else []
                skipped = 0

            if len(run) >= 2:
                clusters.append(run)

        # 5. Extract cluster points and transform centroids into pure odometry frame
        cos_oth = math.cos(oth)
        sin_oth = math.sin(oth)
        cos_rel = np.cos(rel)
        sin_rel = np.sin(rel)

        detected_clusters: List[Dict[str, Any]] = []
        confirmed_wall_pts: List[np.ndarray] = []

        for run_indices in clusters:
            idx = np.array(run_indices)
            px = r[idx] * cos_rel[idx]
            py = r[idx] * sin_rel[idx]
            pts = np.column_stack([px, py])

            mean_px = float(px.mean())
            mean_py = float(py.mean())

            # Transform centroid to pure odometry frame (ox, oy, oth)
            cluster_ox = ox + cos_oth * mean_px - sin_oth * mean_py
            cluster_oy = oy + sin_oth * mean_px + cos_oth * mean_py

            length, thickness = fit_cluster_geometry(pts)
            is_wall = (length > 1.0 and thickness < 0.10)
            if is_wall:
                confirmed_wall_pts.append(pts)

            detected_clusters.append({
                "pts": pts,
                "ox": cluster_ox,
                "oy": cluster_oy,
                "length": length,
                "thickness": thickness,
                "is_wall": is_wall,
            })

        # Second pass: check wall continuations
        for c_dict in detected_clusters:
            if not c_dict["is_wall"]:
                if is_wall_continuation(c_dict["pts"], confirmed_wall_pts):
                    c_dict["is_wall_piece"] = True
                else:
                    c_dict["is_wall_piece"] = False
            else:
                c_dict["is_wall_piece"] = False

        # 6. Associate detections with existing tracks in pure odometry frame
        assoc_thresh = 1.5 if is_fog else 1.0
        used_tracks: Set[int] = set()
        matched_cluster_indices: Set[int] = set()

        for c_idx, c_dict in enumerate(detected_clusters):
            c_ox, c_oy = c_dict["ox"], c_dict["oy"]
            best_idx = None
            best_dist = assoc_thresh

            for t_idx, tr in enumerate(self.tracks):
                if t_idx in used_tracks:
                    continue
                d = math.hypot(tr.ox - c_ox, tr.oy - c_oy)
                if d < best_dist:
                    best_idx = t_idx
                    best_dist = d

            if best_idx is not None:
                tr = self.tracks[best_idx]
                used_tracks.add(best_idx)
                matched_cluster_indices.add(c_idx)

                # Velocity update in odometry frame
                dx = c_ox - tr.ox
                dy = c_oy - tr.oy
                inst_vx = dx / self.dt
                inst_vy = dy / self.dt
                tr.vx_odom = 0.6 * tr.vx_odom + 0.4 * inst_vx
                tr.vy_odom = 0.6 * tr.vy_odom + 0.4 * inst_vy

                tr.ox = c_ox
                tr.oy = c_oy
                tr.pts = c_dict["pts"]
                tr.length = c_dict["length"]
                tr.thickness = c_dict["thickness"]
                tr.hist.append((c_ox, c_oy))
                tr.seen.append(1)
                tr.coast_ticks = 0

                # Geometry classification
                if c_dict["is_wall"] or c_dict["is_wall_piece"]:
                    tr.class_label = "wall_extra"
                    tr.dyn = False
            else:
                # New track
                tr = Track(self._next_track_id, c_ox, c_oy, c_dict["pts"])
                self._next_track_id += 1
                tr.length = c_dict["length"]
                tr.thickness = c_dict["thickness"]

                if c_dict["is_wall"] or c_dict["is_wall_piece"]:
                    tr.class_label = "wall_extra"
                    tr.dyn = False
                else:
                    # Inherit pedestrian class if adjacent to a known dynamic track
                    if any(other.is_pedestrian and math.hypot(other.ox - c_ox, other.oy - c_oy) < assoc_thresh
                           for other in self.tracks):
                        tr.dyn = True
                        tr.class_label = "pedestrian"

                self.tracks.append(tr)
                used_tracks.add(len(self.tracks) - 1)
                matched_cluster_indices.add(c_idx)

        # 7. Unmatched tracks: Coasting / prediction for dynamic tracks
        robot_still = abs(v_odom) < 0.02
        for t_idx, tr in enumerate(self.tracks):
            if t_idx not in used_tracks:
                tr.seen.append(0)
                tr.coast_ticks += 1

                # If track was pedestrian and lost within 1.0s (10 ticks), predict motion
                if tr.is_pedestrian and tr.coast_ticks <= 10:
                    tr.ox += tr.vx_odom * self.dt
                    tr.oy += tr.vy_odom * self.dt
                    tr.hist.append((tr.ox, tr.oy))

                    # Predict robot-frame points
                    rel_ox = tr.ox - ox
                    rel_oy = tr.oy - oy
                    rx = cos_oth * rel_ox + sin_oth * rel_oy
                    ry = -sin_oth * rel_ox + cos_oth * rel_oy
                    # Synthesize approximate cluster footprint around predicted position
                    tr.pts = np.array([
                        [rx - 0.15, ry],
                        [rx + 0.15, ry],
                        [rx, ry - 0.15],
                        [rx, ry + 0.15],
                    ])
                else:
                    tr.hist.append((tr.ox, tr.oy))
                    rel_ox = tr.ox - ox
                    rel_oy = tr.oy - oy
                    rx = cos_oth * rel_ox + sin_oth * rel_oy
                    ry = -sin_oth * rel_ox + cos_oth * rel_oy
                    tr.pts = np.array([[rx, ry]])

        # 8. Track classification and history evaluation
        for tr in self.tracks:
            tr.hist = tr.hist[-11:]
            tr.seen = tr.seen[-11:]

            if tr.is_wall:
                continue

            if len(tr.hist) >= 5:
                # Shift over history window (up to 1.0 s)
                dt_span = len(tr.hist) * self.dt
                shift = math.hypot(tr.hist[-1][0] - tr.hist[0][0], tr.hist[-1][1] - tr.hist[0][1])

                if shift >= 0.6:
                    tr.class_label = "pedestrian"
                    tr.dyn = True
                    tr.still_ticks = 0
                elif shift < 0.25:
                    if robot_still:
                        tr.still_ticks += 1
                    else:
                        tr.still_ticks = 0

                    # Stationary >= 1.0 s (10 ticks) while AMR is stopped -> static object
                    if tr.still_ticks >= 10:
                        tr.class_label = "static_object"
                        tr.dyn = False
                    elif tr.dyn is None and sum(tr.seen) >= 8:
                        # Frequently seen without motion
                        if tr.still_ticks >= 5:
                            tr.class_label = "static_object"
                            tr.dyn = False
            if tr.dyn is None:
                tr.class_label = "unknown"

        # 9. Pruning stale tracks
        # Keep track if seen recently, or if pedestrian coasting <= 10 ticks
        self.tracks = [
            tr for tr in self.tracks
            if (sum(tr.seen[-6:]) > 0) or (tr.is_pedestrian and tr.coast_ticks <= 10)
        ]

        # 10. Check map discrepancies: missing walls and extra walls
        self._check_map_discrepancies(r, exp, x, y, th, map_segs, scan_inliers)

        # Return confirmed tracks: seen in >= 3 of last 4 frames, or has >= 3 lidar points (immediate object), or coasting pedestrian
        return [
            tr for tr in self.tracks
            if ((sum(tr.seen[-4:]) >= 3 or len(tr.pts) >= 3) and tr.seen[-1] == 1) or (tr.is_pedestrian and tr.coast_ticks <= 10)
        ]

    def _check_map_discrepancies(
        self,
        ranges: np.ndarray,
        exp_ranges: np.ndarray,
        x: float,
        y: float,
        th: float,
        map_segs: np.ndarray,
        scan_inliers: int,
    ) -> None:
        """Detect demolished mapped walls (map_missing) or confirmed extra structures (map_extra)."""
        if len(map_segs) == 0:
            return

        # Sensed missing walls: finite rays longer than map by > 1.2m when scan match is reliable
        if scan_inliers >= 40:
            overshoot = (exp_ranges < 15.0) & np.isfinite(ranges) & (ranges < 19.5) & (ranges > exp_ranges + 1.2)
            if overshoot.any():
                over_indices = np.flatnonzero(overshoot)
                # Count rays penetrating each segment in the current tick
                tick_votes: Dict[int, int] = {}
                for idx in over_indices:
                    for s_idx, seg in enumerate(map_segs):
                        if s_idx in self.removed_segment_ids:
                            continue
                        ang = wrap_angle(th + np.radians(float(idx)))
                        r_s = raycast(x, y, np.array([ang]), seg[None, :])
                        if np.isfinite(r_s[0]) and abs(r_s[0] - exp_ranges[idx]) < 0.25:
                            tick_votes[s_idx] = tick_votes.get(s_idx, 0) + 1

                for s_idx, count in tick_votes.items():
                    # Require at least 5 simultaneous penetrating rays to register a vote
                    if count >= 5:
                        self._missing_wall_votes[s_idx] = self._missing_wall_votes.get(s_idx, 0) + 1
                        if self._missing_wall_votes[s_idx] >= 20:
                            self.removed_segment_ids.add(s_idx)
                            self.note = "map_missing"

        # Check for confirmed extra walls
        has_extra_wall = any(tr.is_wall for tr in self.tracks)
        if has_extra_wall and not self.note:
            self.note = "map_extra"

    def get_extra_obstacles(self) -> List[Tuple[float, float, float]]:
        """Return extra obstacles for route planner / collision avoidance: list of (x, y, radius)."""
        obs = []
        for tr in self.tracks:
            if tr.is_wall or tr.is_static_object:
                # Estimate radius from length
                r_eff = max(0.4, tr.length / 2.0)
                # World position of track
                obs.append((tr.ox, tr.oy, r_eff))
        return obs
