"""Sensor models with deliberately correlated noise (SPEC section 5).

Each sensor owns its numpy Generator so the draw sequence of one sensor does not
depend on another. The number of draws per tick does not depend on wall time.
"""
import math

import numpy as np

from amrsim.geometry import ray_cast, wrap_angle
from amrsim.params import CONFIG, DT


def _rw_sigma_per_tick(deg_per_sqrt_min):
    """Random walk with std `deg` after one minute -> per-tick std in radians."""
    return math.radians(deg_per_sqrt_min) / math.sqrt(60.0 / DT)


class Gnss:
    def __init__(self, rng):
        c = CONFIG["gnss"]
        self.rng = rng
        self.tau = c["bias_tau_s"]
        self.sig_b = c["bias_sigma"]
        self.sig_w = c["white_sigma"]
        self.a = math.exp(-DT / self.tau)
        self.q = self.sig_b * math.sqrt(1.0 - self.a * self.a)
        self.bias = rng.normal(0.0, self.sig_b, 2)
        self.jump_iv = c["jump_interval_s"]
        self.jump_sz = c["jump_size_m"]
        self.jump_du = c["jump_duration_s"]
        self.next_jump = float(rng.uniform(*self.jump_iv))
        self.jump_end = -1.0
        self.jump = np.zeros(2)
        self.jump_hdop = None

    def step(self, t, x, y, blocked):
        """Advance the error processes one tick and return the obs field."""
        self.bias = self.a * self.bias + self.q * self.rng.normal(0.0, 1.0, 2)
        white = self.rng.normal(0.0, self.sig_w, 2)
        if t >= self.next_jump and t >= self.jump_end:
            ang = self.rng.uniform(0.0, 2.0 * math.pi)
            mag = self.rng.uniform(*self.jump_sz)
            self.jump = np.array([mag * math.cos(ang), mag * math.sin(ang)])
            self.jump_end = t + float(self.rng.uniform(*self.jump_du))
            self.jump_hdop = float(self.rng.uniform(1.5, 3.0)) if self.rng.uniform() < 0.5 else None
            self.next_jump = self.jump_end + float(self.rng.uniform(*self.jump_iv))
        in_jump = t < self.jump_end
        hdop_noise = float(self.rng.normal(0.0, 0.05))
        if blocked:
            return {"x": None, "y": None, "valid": False, "hdop": None}
        err = self.bias + white + (self.jump if in_jump else 0.0)
        hdop = self.jump_hdop if (in_jump and self.jump_hdop is not None) else 0.9 + hdop_noise
        return {"x": round(x + float(err[0]), 3), "y": round(y + float(err[1]), 3),
                "valid": True, "hdop": round(max(0.5, hdop), 2)}


class Odometry:
    def __init__(self, rng, snow):
        c = CONFIG["odom"]
        self.rng = rng
        lo, hi = c["scale_error_abs_range"]
        self.scale = float(rng.uniform(lo, hi)) * (1.0 if rng.uniform() < 0.5 else -1.0)
        mult = c["snow_multiplier"] if snow else 1.0
        self.sig_rel = c["sigma_rel"] * mult
        self.sig_lat = c["sigma_lat_rel"] * mult
        self.sig_th = _rw_sigma_per_tick(c["heading_rw_deg_per_sqrt_min"]) * mult

    def step(self, wheel):
        dx, dy, dth = wheel
        n = self.rng.normal(0.0, 1.0, 3)
        ds = math.hypot(dx, dy)
        moving = ds > 1e-6 or abs(dth) > 1e-6
        mx = dx * (1.0 + self.scale) + n[0] * self.sig_rel * ds
        my = dy * (1.0 + self.scale) + n[1] * self.sig_lat * ds
        mth = dth + (n[2] * self.sig_th if moving else 0.0)
        return {"dx": round(mx, 5), "dy": round(my, 5), "dtheta": round(mth, 6)}


class Imu:
    def __init__(self, rng):
        c = CONFIG["imu"]
        self.rng = rng
        self.sig_rate = c["yaw_rate_sigma"]
        self.bias = float(rng.normal(0.0, c["yaw_rate_bias_sigma"]))
        self.sig_head = c["heading_sigma"]
        self.q_head = _rw_sigma_per_tick(c["heading_rw_deg_per_sqrt_min"])
        self.drift = 0.0

    def step(self, w_true, th_true):
        n = self.rng.normal(0.0, 1.0, 3)
        self.drift += n[2] * self.q_head
        rate = w_true + self.bias + n[0] * self.sig_rate
        head = wrap_angle(th_true + self.drift + n[1] * self.sig_head)
        return {"yaw_rate": round(rate, 5), "heading": round(head, 5)}


class Lidar:
    def __init__(self, rng, snow):
        c = CONFIG["lidar"]
        self.rng = rng
        self.n = c["beams"]
        self.rel = np.radians(c["angle_min_deg"] + c["angle_increment_deg"] * np.arange(self.n))
        self.max_range = c["max_range"]
        self.fog_range = c["fog_max_range"]
        self.fog_drop = c["fog_dropout"]
        self.sigma = c["sigma"]
        self.snow = snow
        self.snow_rate = c["snow_false_rate"]
        self.snow_lo, self.snow_hi = c["snow_false_range"]

    def scan(self, world, x, y, th, circles, fog):
        """Return a list of ranges (NaN = no return)."""
        reach = self.fog_range if fog else self.max_range
        segs = world.lidar_segments(x, y, reach + 0.5)
        r = ray_cast(x, y, th + self.rel, segs, circles)
        r = r + self.rng.normal(0.0, self.sigma, self.n)
        r[r > reach] = np.inf
        if fog:
            r[self.rng.uniform(size=self.n) < self.fog_drop] = np.inf
        if self.snow:
            fake = self.rng.uniform(size=self.n) < self.snow_rate
            vals = self.rng.uniform(self.snow_lo, self.snow_hi, self.n)
            r = np.where(fake, np.minimum(r, vals), r)
        r = np.maximum(r, 0.05)
        r = np.round(r, 3)
        r[~np.isfinite(r)] = np.nan
        return r.tolist()
