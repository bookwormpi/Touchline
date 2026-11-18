#!/usr/bin/env python3
"""Print VL53L8CX distance readings for poolside calibration."""

import argparse
import logging
import struct
import time

from ..main import check_sensor_ready, close_sensor, log_bad_frame, make_sensor, read_grid
from Touchline import config

LOG = logging.getLogger("touchline")

def print_grid(grid, detector):
    oriented = orient_grid(grid, detector.rotation)
    width = max(5, len(str(detector.config.max_distance_mm)) + 1)
    print("    " + " ".join(f"{x:>{width}}" for x in range(8)))
    for y, row in enumerate(oriented):
        cells = []
        for x, (distance, valid) in enumerate(row):
            if (y, x) in detector.dead_zones:
                cell = "X"
            else:
                value = occupancy_distance(distance, valid, detector.config.max_distance_mm)
                cell = f"{value}{'*' if not valid or distance <= 0 else ''}"
            cells.append(f"{cell:>{width}}")
        print(f"{y:>2}  " + " ".join(cells))
    print("X=dead zone, *=assumed distance for invalid or non-positive reading; values in mm")
    print("All-invalid frames are assumed clear for occupancy; calibration uses valid readings only.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor-only", action="store_true",
                        help="print sensor readings without using the LED matrix")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="maximum seconds to wait for a sensor frame")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    detector = sensor_config.create_detector()
    sensor = i2c = None
    try:
        while True:
            try:
                if sensor is None:
                    sensor, i2c = make_sensor(sensor_config.RANGING_HZ)
                    last_frame = time.monotonic()
                    LOG.info("Sensor initialized; waiting for frames")
                if check_sensor_ready(sensor):
                    grid = read_grid(sensor)
                    log_bad_frame(grid, detector, "live diagnostic")
                    print_grid(grid, detector)
                    print(flush=True)
                    last_frame = time.monotonic()
                elif time.monotonic() - last_frame > args.timeout:
                    raise TimeoutError("No sensor frame received before timeout")
            except (OSError, RuntimeError, ValueError, IndexError, struct.error):
                LOG.exception("Sensor diagnostic failure; reconnecting in 2 seconds")
                if sensor is not None or i2c is not None:
                    close_sensor(sensor, i2c)
                sensor = i2c = None
                time.sleep(2)
                continue
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        close_sensor(sensor, i2c)


if __name__ == "__main__":
    main()