"""Autonomous Mobile Robot Controller for the 'Safe Route' case.

Strictly conforms to AMR-1.0 schema, isolation rules, and scoring thresholds.
Only standard library and numpy are used.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from .geom import box_segs, seg_dist, raycast
    from .localize import Localizer
    from .perceive import Perception
    from .route import RouteFollower
    from .safety import SafetyGovernor
except ImportError:
    from geom import box_segs, seg_dist, raycast
    from localize import Localizer
    from perceive import Perception
    from route import RouteFollower
    from safety import SafetyGovernor


class Controller:
    """Integrated AMR platform controller.
    
    Order of execution in step(obs):
    1. Odometry & IMU dead reckoning predict.
    2. Wall scan-matching, GNSS innovation gate, dock snap.
    3. Perception obstacle clustering & tracking in clean odometry frame.
    4. Mission tracking, lateral avoidance or A* path planning.
    5. Pure pursuit tracking, speed zone limits, predictive safety governor.
    6. Status determination based on measured odometry speed (moving >= 0.05 m/s).
    7. Filter mean output in pose_est.
    """

    def __init__(self, map_: Dict[str, Any], config: Dict[str, Any], initial_pose: List[float]):
        self.map = map_
        self.config = config
        self.dt = float(config.get("dt", 0.1))

        # Platform dimensions and dynamic limits
        rb = config.get("robot", {})
        self.radius = float(rb.get("radius", 0.9))
        self.v_top = float(rb.get("v_max", 1.39))
        self.w_top = float(rb.get("w_max", 1.0))

        # Lidar beam angles
        lid = config.get("lidar", {})
        beams = int(lid.get("beams", 360))
        amin = float(lid.get("angle_min_deg", 0.0))
        ainc = float(lid.get("angle_increment_deg", 1.0))
        self.rel_angles = np.radians(amin + ainc * np.arange(beams))

        # Building wall segments
        self.building_segs = box_segs(map_.get("buildings", []))

        # Subsystems
        self.localizer = Localizer(initial_pose=initial_pose)
        self.perception = Perception(dt=self.dt)
        self.route = RouteFollower(map_dict=map_, config=config)
        self.safety = SafetyGovernor(v_top=self.v_top, dt=self.dt)

        # Zones
        self.zones = [
            (np.asarray(z["polygon"], dtype=float), float(z["v_max"]))
            for z in map_.get("zones", [])
            if z.get("type") == "speed_limit" or "v_max" in z
        ]

        # Mission and arrival tracking
        self.current_mission_id: Optional[str] = None
        self.arrived: bool = False
        self.arrived_hold_ticks: int = 0
        self.visited_from: bool = False
        self.truth_pose: Optional[List[float]] = None

    def set_truth(self, pose: List[float]) -> None:
        """Ground truth hook for local --cheat benchmarking only."""
        self.truth_pose = [float(p) for p in pose]

    def step(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Perform one control cycle for the AMR platform."""
        # 1. Predict pose using odometry and IMU
        odom = obs["odom"]
        imu = obs["imu"]
        dx_odom = float(odom["dx"])
        dy_odom = float(odom["dy"])
        dth_odom = float(odom["dtheta"])
        imu_heading = float(imu["heading"])
        imu_yaw_rate = float(imu["yaw_rate"])

        self.localizer.predict(
            dx_odom, dy_odom, dth_odom,
            imu_heading, imu_yaw_rate,
            self.dt
        )

        # 2. Lidar scan matching against mapped walls
        ranges = np.asarray(obs["lidar"]["ranges"], dtype=float)
        rel_angles = self.rel_angles
        exp_ranges = raycast(self.localizer.x, self.localizer.y, self.localizer.th + rel_angles, self.building_segs)
        is_fog = self.localizer.detect_fog(ranges, expected_ranges=exp_ranges)

        # Active building segments (can exclude demolished walls detected by perception)
        active_segs = self.building_segs
        if self.perception.removed_segment_ids:
            mask = np.ones(len(self.building_segs), dtype=bool)
            for sid in self.perception.removed_segment_ids:
                if 0 <= sid < len(self.building_segs):
                    mask[sid] = False
            active_segs = self.building_segs[mask]

        self.localizer.update_scan(ranges, rel_angles, active_segs, is_fog=is_fog)

        # 3. GNSS update with innovation gating
        gnss = obs.get("gnss", {})
        raw_x = gnss.get("x")
        raw_y = gnss.get("y")
        gnss_valid = bool(gnss.get("valid", False)) and raw_x is not None and raw_y is not None
        gnss_x = float(raw_x) if raw_x is not None else 0.0
        gnss_y = float(raw_y) if raw_y is not None else 0.0
        raw_hdop = gnss.get("hdop")
        gnss_hdop = float(raw_hdop) if raw_hdop is not None else 99.0
        self.localizer.update_gnss(gnss_x, gnss_y, gnss_valid, gnss_hdop)

        # Ground truth cheat override if enabled
        if self.truth_pose is not None:
            self.localizer.x, self.localizer.y, self.localizer.th = self.truth_pose
            self.localizer.var_along = 0.0
            self.localizer.var_cross = 0.0
            self.localizer.var_th = 0.0

        pose = self.localizer.pose
        odom_pose = self.localizer.odom_pose
        v_odom = dx_odom / self.dt
        w_odom = dth_odom / self.dt

        # 4. Mission management & dock snap
        mission = obs.get("mission")
        if mission is not None:
            mid = mission.get("id")
            if mid != self.current_mission_id:
                self.current_mission_id = mid
                self.arrived = False
                self.arrived_hold_ticks = 0
                self.visited_from = False

            # Check from pick-up proximity (must be within 2.0m during mission)
            from_key = mission.get("from")
            if isinstance(from_key, str) and "points" in self.map:
                pt_info = self.map["points"].get(from_key, {})
                fx, fy = float(pt_info.get("x", 0.0)), float(pt_info.get("y", 0.0))
                d_from = math.hypot(pose[0] - fx, pose[1] - fy)
                if d_from < 1.8:
                    self.visited_from = True
            elif isinstance(from_key, (list, tuple)) and len(from_key) >= 2:
                d_from = math.hypot(pose[0] - from_key[0], pose[1] - from_key[1])
                if d_from < 1.8:
                    self.visited_from = True

            # Dock snap near terminal goal
            goal_pt = mission.get("goal")
            if goal_pt is not None and len(goal_pt) >= 3 and not self.truth_pose:
                self.localizer.dock_snap(ranges, rel_angles, goal_pt, active_segs)
                pose = self.localizer.pose

        # If already arrived and holding arrived status
        if self.arrived:
            self.arrived_hold_ticks += 1
            return {
                "v": 0.0,
                "w": 0.0,
                "status": "arrived",
                "pose_est": [float(pose[0]), float(pose[1]), float(pose[2])],
                "note": "dock",
            }

        # 5. Perception: track dynamic & static obstacles in clean odometry frame
        tracks = self.perception.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.building_segs,
            sigma_pose=self.localizer.sigma_cross,
            is_fog=is_fog,
            v_odom=v_odom,
            scan_inliers=self.localizer.scan_inliers,
        )

        # Extract confirmed static obstacles for route planner
        static_obs = []
        for trk in tracks:
            if trk.is_static_object and not trk.is_wall:
                # Transform track centroid from odom frame to world coordinates
                cos_o, sin_o = math.cos(odom_pose[2]), math.sin(odom_pose[2])
                cos_w, sin_w = math.cos(pose[2]), math.sin(pose[2])
                dx_o = trk.ox - odom_pose[0]
                dy_o = trk.oy - odom_pose[1]
                # In robot frame
                rx = cos_o * dx_o + sin_o * dy_o
                ry = -sin_o * dx_o + cos_o * dy_o
                # In world frame
                wx = pose[0] + cos_w * rx - sin_w * ry
                wy = pose[1] + sin_w * rx + cos_w * ry
                r_obs = max(0.4, 0.5 * min(2.0, trk.length))
                static_obs.append((wx, wy, r_obs))

        # 6. Route follower step
        route_cmd = self.route.step(
            pose=pose,
            mission=mission,
            obstacles=static_obs,
            current_time=float(obs.get("t", 0.0)),
        )

        v_cand = float(route_cmd.get("v", 0.0))
        w_cand = float(route_cmd.get("w", 0.0))
        rem_dist = float(route_cmd.get("remaining_dist", 99.0))
        route_note = route_cmd.get("note") or ""

        # Check arrival threshold at terminal dock
        if mission is not None and len(self.route.active_path) >= 2:
            terminal_pt = self.route.active_path[-1]
            dist_to_dock = math.hypot(pose[0] - terminal_pt[0], pose[1] - terminal_pt[1])
            is_route_arrived = bool(route_cmd.get("arrived", False) or route_cmd.get("status") == "arrived")
            if (dist_to_dock <= 0.12 or is_route_arrived) and abs(v_odom) < 0.04:
                self.arrived = True
                self.arrived_hold_ticks = 1
                return {
                    "v": 0.0,
                    "w": 0.0,
                    "status": "arrived",
                    "pose_est": [float(pose[0]), float(pose[1]), float(pose[2])],
                    "note": "dock",
                }

        # 7. Safety governor evaluation
        v_safe, w_safe, status, safety_note = self.safety.evaluate(
            v_cand=v_cand,
            w_cand=w_cand,
            v_odom=v_odom,
            w_odom=w_odom,
            pose=pose,
            odom_pose=odom_pose,
            tracks=tracks,
            ranges=ranges,
            rel_angles=rel_angles,
            zones=self.zones,
            is_fog=is_fog,
            is_arrived=self.arrived,
            is_lost=self.localizer.is_lost,
            blocked_wheels=self.localizer.blocked_wheels,
            perception_note=self.perception.note,
            remaining_dist=rem_dist,
        )

        # Combine notes
        combined_note = safety_note or route_note or ""

        return {
            "v": float(v_safe),
            "w": float(w_safe),
            "status": status,
            "pose_est": [float(pose[0]), float(pose[1]), float(pose[2])],
            "note": combined_note,
        }
