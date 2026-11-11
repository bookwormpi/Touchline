#!/usr/bin/env python3
"""Print VL53L8CX distance readings for poolside calibration."""

import argparse
import time

from main import close_sensor, make_sensor, read_grid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor-only", action="store_true",
                        help="print sensor readings without using the LED matrix")
    parser.add_argument("--hz", type=int, default=10, choices=range(1, 16))
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="maximum seconds to wait for a sensor frame")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    sensor, i2c = make_sensor(args.hz)
    last_frame = time.monotonic()
    try:
        while True:
            if sensor.check_data_ready():
                grid = read_grid(sensor)
                for row in grid:
                    print(" ".join(f"{distance:4}" if valid and distance > 0 else "   -"
                                   for distance, valid in row))
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