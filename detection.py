"""Debounced occupancy detection for an 8x8 VL53L8CX grid."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionConfig:
    enter_mm: int = 1000
    exit_mm: int = 1200
    min_zones: int = 3
    min_valid: int = 8
    enter_seconds: float = 0.3
    exit_seconds: float = 0.5
    frame_timeout: float = 1.0

    def __post_init__(self):
        if not 0 < self.enter_mm < self.exit_mm:
            raise ValueError("Detection distances must satisfy 0 < enter < exit")
        if not 1 <= self.min_zones <= self.min_valid <= 64:
            raise ValueError("Require 1 <= min_zones <= min_valid <= 64")
        if min(self.enter_seconds, self.exit_seconds, self.frame_timeout) <= 0:
            raise ValueError("Debounce and timeout values must be positive")


class OccupancyDetector:
    def __init__(self, config):
        self.config = config
        self.occupied = None
        self.candidate = None
        self.candidate_since = None
        self.last_valid = None
        self.fault = True

    def invalidate(self):
        self.last_valid = None
        self.fault = True
        self.occupied = None
        self._reset_candidate()

    def _reset_candidate(self):
        self.candidate = self.candidate_since = None

    def check_timeout(self, now):
        if self.last_valid is None or now - self.last_valid > self.config.frame_timeout:
            self.fault = True
            self.occupied = None
            self._reset_candidate()
        return self.fault

    def update(self, grid, now):
        self.check_timeout(now)
        readings = [mm for row in grid for mm, valid in row if valid and mm > 0]
        if len(readings) < self.config.min_valid:
            self._reset_candidate()
            return None
        self.last_valid = now
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
