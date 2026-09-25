# Approach

- Localization: Scan-matching with Gauss-Newton, GNSS gating, scale calibration, IMU heading.
- Route following: Pure pursuit along reference path with adaptive lookahead.
- Safety: Lidar obstacle tracking in pure odometry frame, speed limits from map zones.
- Omissions: No global mapping, no dynamic replanning outside path corridor.
