"""Debounced occupancy detection for an 8x8 VL53L8CX grid."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class DetectionConfig:
    enter_mm: int = 1000
    exit_mm: int = 1200
    min_zones: int = 3
    max_distance_mm: int = 4000
    enter_seconds: float = 0.3
    exit_seconds: float = 0.5
    frame_timeout: float = 1.0

    def __post_init__(self):
        if any(type(value) is not int for value in
               (self.enter_mm, self.exit_mm, self.min_zones, self.max_distance_mm)):
            raise ValueError("Distances and zone counts must be integers")
        if not 0 < self.enter_mm < self.exit_mm < self.max_distance_mm:
            raise ValueError("Detection distances must satisfy 0 < enter < exit < max distance")
        if not 1 <= self.min_zones <= 64:
            raise ValueError("Require 1 <= min_zones <= 64")
        if not all(type(value) in (int, float) and math.isfinite(value) and value > 0 for value in
                   (self.enter_seconds, self.exit_seconds, self.frame_timeout)):
            raise ValueError("Debounce and timeout values must be positive")


def orient_grid(grid, rotation):
    if len(grid) != 8 or any(len(row) != 8 for row in grid):
        raise ValueError("Expected an 8x8 sensor grid")
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180 or 270 degrees")
    result = [list(row) for row in grid]
    for _ in range(rotation // 90):
        result = [list(row) for row in zip(*result[::-1])]
    return result


def active_readings(grid, dead_zones):
    return [mm for y, row in enumerate(grid) for x, (mm, valid) in enumerate(row)
            if (y, x) not in dead_zones and valid and mm > 0]


def occupancy_distance(mm, valid, max_distance_mm):
    return mm if valid and mm > 0 else max_distance_mm


def occupancy_readings(grid, dead_zones, max_distance_mm):
    return [occupancy_distance(mm, valid, max_distance_mm)
            for y, row in enumerate(grid) for x, (mm, valid) in enumerate(row)
            if (y, x) not in dead_zones]


class OccupancyDetector:
    def __init__(self, config, rotation=0, dead_zones=frozenset()):
        self.config = config
        if type(rotation) is not int or rotation not in (0, 90, 180, 270):
            raise ValueError("Rotation must be 0, 90, 180 or 270 degrees")
        for zone in dead_zones:
            if (not isinstance(zone, tuple) or len(zone) != 2 or
                    any(type(value) is not int or not 0 <= value < 8 for value in zone)):
                raise ValueError(f"Invalid dead zone {zone!r}; use (row, column) from 0 to 7")
        self.dead_zones = frozenset(dead_zones)
        if 64 - len(self.dead_zones) < config.min_zones:
            raise ValueError("Dead zones leave fewer active zones than MIN_ZONES")
        self.rotation = rotation
        self.occupied = None
        self.candidate = None
        self.candidate_since = None
        self.last_frame = None
        self.fault = True

    def invalidate(self):
        self.last_frame = None
        self.fault = True
        self.occupied = None
        self._reset_candidate()

    def _reset_candidate(self):
        self.candidate = self.candidate_since = None

    def check_timeout(self, now):
        if self.last_frame is None or now - self.last_frame > self.config.frame_timeout:
            self.fault = True
            self.occupied = None
            self._reset_candidate()
        return self.fault

    def update(self, grid, now):
        self.check_timeout(now)
        oriented = orient_grid(grid, self.rotation)
        readings = occupancy_readings(oriented, self.dead_zones, self.config.max_distance_mm)
        self.last_frame = now
        self.fault = False
        near = sum(mm <= self.config.enter_mm for mm in readings)
        not_clear = sum(mm < self.config.exit_mm for mm in readings)
        if near >= self.config.min_zones:
            desired = True
        elif not_clear < self.config.min_zones:
            desired = False
        else:
            self._reset_candidate()
            return None
        if desired == self.occupied:
            self._reset_candidate()
            return None
        if desired != self.candidate:
            self.candidate = desired
            self.candidate_since = now
            return None
        delay = self.config.enter_seconds if desired else self.config.exit_seconds
        if now - self.candidate_since < delay:
            return None
        previous = self.occupied
        self.occupied = desired
        self._reset_candidate()
        if previous is None:
            return None
        return "arrived" if desired else "left"
