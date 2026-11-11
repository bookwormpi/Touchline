"""Edit installation-specific sensor calibration and button GPIO values."""

# BCM GPIO numbers for the three normally-open buttons.
PREV_PIN = 18
NEXT_PIN = 19
OK_PIN = 25

# Rotation is clockwise; dead-zone coordinates are (row, column) after rotation,
# zero-based from the top left of the grid printed by the calibration tool.
ROTATION_DEGREES = 0  # 0, 90, 180 or 270
DEAD_ZONES = frozenset({
    # (0, 0),
})

# Example values only: calibrate and validate at the actual pool.
ENTER_MM = 1000
EXIT_MM = 1200
MIN_ZONES = 3
MIN_VALID = 8
ENTER_SECONDS = 0.3
EXIT_SECONDS = 0.5
FRAME_TIMEOUT = 1.0
RANGING_HZ = 10


def create_detector():
    from detection import DetectionConfig, OccupancyDetector

    if type(RANGING_HZ) is not int or not 1 <= RANGING_HZ <= 15:
        raise ValueError("RANGING_HZ must be an integer from 1 to 15 for 8x8")
    config = DetectionConfig(ENTER_MM, EXIT_MM, MIN_ZONES, MIN_VALID,
                             ENTER_SECONDS, EXIT_SECONDS, FRAME_TIMEOUT)
    return OccupancyDetector(config, ROTATION_DEGREES, DEAD_ZONES)
