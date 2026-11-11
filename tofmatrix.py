#!/usr/bin/env python3
"""Print VL53L8CX distance readings for poolside calibration."""

import argparse
import time

from calibrate_sensor import print_grid
from main import close_sensor, make_sensor, read_grid
import sensor_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor-only", action="store_true",
                        help="print sensor readings without using the LED matrix")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="maximum seconds to wait for a sensor frame")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    detector = sensor_config.create_detector()
    sensor, i2c = make_sensor(sensor_config.RANGING_HZ)
    last_frame = time.monotonic()
    try:
        while True:
            if sensor.check_data_ready():
                grid = read_grid(sensor)
                print_grid(grid, detector)
                print(flush=True)
                last_frame = time.monotonic()
            elif time.monotonic() - last_frame > args.timeout:
                raise TimeoutError("No sensor frame received before timeout")
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        close_sensor(sensor, i2c)


if __name__ == "__main__":
    main()