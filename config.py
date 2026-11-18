"""Edit installation-specific sensor calibration and button GPIO values."""
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path


# BCM GPIO numbers for the two normally-open buttons.
NEXT_PIN = 25
OK_PIN = 18

# Rotation is clockwise; dead-zone coordinates are (row, column) after rotation,
# zero-based from the top left of the grid printed by the calibration tool.
ROTATION_DEGREES = 0  # 0, 90, 180 or 270
DEAD_ZONES = frozenset({
    # (0, 0),
})

# Calibrated at pool
ENTER_MM = 300
EXIT_MM = 3999
MIN_ZONES = 3
MAX_DISTANCE_MM = 4000
ENTER_SECONDS = 0.3
EXIT_SECONDS = 0.5
FRAME_TIMEOUT = 3.0
RANGING_HZ = 10

LOG = logging.getLogger("touchline")
LEGACY_SENSOR_KEYS = frozenset(("enter_mm", "exit_mm", "min_zones", "min_valid",
                                "enter_seconds", "exit_seconds", "frame_timeout"))


def create_detector():
    from .detection import DetectionConfig, OccupancyDetector

    if type(RANGING_HZ) is not int or not 1 <= RANGING_HZ <= 15:
        raise ValueError("RANGING_HZ must be an integer from 1 to 15 for 8x8")
    config = DetectionConfig(enter_mm=ENTER_MM, exit_mm=EXIT_MM, min_zones=MIN_ZONES,
                             max_distance_mm=MAX_DISTANCE_MM, enter_seconds=ENTER_SECONDS,
                             exit_seconds=EXIT_SECONDS, frame_timeout=FRAME_TIMEOUT)
    return OccupancyDetector(config, ROTATION_DEGREES, DEAD_ZONES)

@dataclass(frozen=True)
class Settings:
    brightness: int = 100
    sound: bool = True

    def __post_init__(self):
        if type(self.brightness) is not int or not 1 <= self.brightness <= 100:
            raise ValueError("Brightness must be an integer from 1 to 100")
        if type(self.sound) is not bool:
            raise ValueError("Sound must be true or false")

def load_settings(path, defaults):
    path = Path(path)
    if not path.exists():
        return defaults
    try:
        with path.open(encoding="utf-8") as file:
            values = json.load(file)
        if not isinstance(values, dict):
            raise ValueError("Settings must be a JSON object")
        legacy = values.keys() & LEGACY_SENSOR_KEYS
        if legacy:
            LOG.warning("Ignoring saved sensor settings %s; sensor_config.py is authoritative",
                        ", ".join(sorted(legacy)))
            values = {key: value for key, value in values.items() if key not in legacy}
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
