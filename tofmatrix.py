#!/usr/bin/env python3
"""Print VL53L8CX distance readings for poolside calibration."""

import argparse
import logging
import struct
import time

from calibrate_sensor import print_grid
from main import check_sensor_ready, close_sensor, log_bad_frame, make_sensor, read_grid
import sensor_config

LOG = logging.getLogger("touchline")


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