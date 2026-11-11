"""Persistent display, sound, and sensor settings."""

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from detection import DetectionConfig


@dataclass(frozen=True)
class Settings:
    brightness: int = 100
    sound: bool = True
    enter_mm: int = 1000
    exit_mm: int = 1200
    min_zones: int = 3
    min_valid: int = 8
    enter_seconds: float = 0.3
    exit_seconds: float = 0.5
    frame_timeout: float = 1.0

    def __post_init__(self):
        if type(self.brightness) is not int or not 1 <= self.brightness <= 100:
            raise ValueError("Brightness must be an integer from 1 to 100")
        if type(self.sound) is not bool:
            raise ValueError("Sound must be true or false")
        if any(type(value) is not int for value in
               (self.enter_mm, self.exit_mm, self.min_zones, self.min_valid)):
            raise ValueError("Sensor distances and zone counts must be integers")
        if not 1 <= self.enter_mm < self.exit_mm <= 4000:
            raise ValueError("Require 1 <= entry < exit <= 4000 mm")
        if any(type(value) not in (int, float) for value in
               (self.enter_seconds, self.exit_seconds, self.frame_timeout)):
            raise ValueError("Sensor time values must be numeric")
        if not all(math.isfinite(value) for value in
                   (self.enter_seconds, self.exit_seconds, self.frame_timeout)):
            raise ValueError("Sensor time values must be finite")
        if not (0.1 <= self.enter_seconds <= 5 and 0.1 <= self.exit_seconds <= 5):
            raise ValueError("Debounce must be between 0.1 and 5 seconds")
        self.detection()

    def detection(self):
        return DetectionConfig(self.enter_mm, self.exit_mm, self.min_zones,
                               self.min_valid, self.enter_seconds, self.exit_seconds,
                               self.frame_timeout)


def load_settings(path, defaults):
    path = Path(path)
    if not path.exists():
        return defaults
    try:
        with path.open(encoding="utf-8") as file:
            values = json.load(file)
        if not isinstance(values, dict):
            raise ValueError("Settings must be a JSON object")
        return replace(defaults, **values)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot load settings from {path}: {exc}") from exc


def save_settings(path, settings):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".touchline-", delete=False) as file:
            temp_name = file.name
            json.dump(asdict(settings), file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)
