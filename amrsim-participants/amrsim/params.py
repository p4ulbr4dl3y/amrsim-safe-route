"""Platform and sensor parameters.

CONFIG is exactly what a controller receives as `config`: platform and sensor
model constants, identical for every scenario. Nothing scenario-specific
(weather, events, seed, map patches) may be added here.
"""
import copy

DT = 0.1

CONFIG = {
    "dt": DT,
    "robot": {
        "radius": 0.9,
        "v_min": -0.5,
        "v_max": 1.39,
        "w_max": 1.0,
        "accel": 0.5,
        "decel": 1.2,
        "estop_decel": 2.5,
    },
    "lidar": {
        "beams": 360,
        "angle_min_deg": 0.0,
        "angle_increment_deg": 1.0,
        "max_range": 20.0,
        "sigma": 0.03,
        "fog_max_range": 6.0,
        "fog_dropout": 0.10,
        "snow_false_rate": 0.03,
        "snow_false_range": [0.3, 3.0],
    },
    "odom": {
        "scale_error_abs_range": [0.01, 0.04],
        "sigma_rel": 0.02,
        "sigma_lat_rel": 0.005,
        "heading_rw_deg_per_sqrt_min": 0.5,
        "snow_multiplier": 3.0,
    },
    "imu": {
        "yaw_rate_sigma": 0.01,
        "yaw_rate_bias_sigma": 0.0002,
        "heading_sigma": 0.002,
        "heading_rw_deg_per_sqrt_min": 0.3,
    },
    "gnss": {
        "bias_tau_s": 30.0,
        "bias_sigma": 0.25,
        "white_sigma": 0.3,
        "jump_interval_s": [60.0, 120.0],
        "jump_size_m": [3.0, 8.0],
        "jump_duration_s": [2.0, 5.0],
    },
    "pedestrian": {"radius": 0.3},
    "mission": {"arrival_hold_s": 1.0, "pickup_radius": 2.0},
}


def controller_config():
    """Deep copy for the controller process."""
    return copy.deepcopy(CONFIG)
