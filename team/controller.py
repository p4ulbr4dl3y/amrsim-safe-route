"""AMR Controller entry point."""
from . import geom


class Controller:
    """Controller entry point conforming to simulator check interface."""

    def __init__(self, map_, config, initial_pose):
        self.map = map_
        self.config = config
        self.pose = initial_pose

    def step(self, obs):
        return {"v": 0.0, "w": 0.0}
