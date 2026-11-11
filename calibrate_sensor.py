#!/usr/bin/env python3
"""Guided, hardware-only VL53L8CX calibration; does not modify configuration."""

import argparse
import logging
import math
import statistics
import struct
import time

from detection import active_readings, orient_grid
from main import close_sensor, make_sensor, read_grid
import sensor_config

LOG = logging.getLogger("touchline")


def recommend(empty_frames, occupied_frames, detector):
    """Find conservative thresholds separating every captured usable frame."""
    config = detector.config
    results = []
    for label, frames in (("empty", empty_frames), ("occupied", occupied_frames)):
        if len(frames) < 5:
            raise ValueError(f"{label} capture needs at least 5 frames")
        kth_distances = []
        for grid in frames:
            readings = sorted(active_readings(orient_grid(grid, detector.rotation),
                                              detector.dead_zones))
            if len(readings) < config.min_valid:
                raise ValueError(f"{label} capture has a frame with fewer than "
                                 f"{config.min_valid} valid active zones")
            kth_distances.append(readings[config.min_zones - 1])
        results.append(kth_distances)
    empty, occupied = results
    low, high = max(occupied), min(empty)
    if high - low < 3:
        raise ValueError(
            f"No reliable separation: occupied max={low} mm, empty min={high} mm. "
            "Adjust mounting, dead zones, or MIN_ZONES and repeat; no thresholds recommended."
        )
    enter = low + (high - low) // 3
    exit_mm = low + 2 * (high - low) // 3
    return enter, exit_mm, (min(empty), max(empty)), (min(occupied), max(occupied))


def print_grid(grid, detector):
    oriented = orient_grid(grid, detector.rotation)
    print("      " + " ".join(f"{x:>4}" for x in range(8)))
    for y, row in enumerate(oriented):
        cells = []
        for x, (distance, valid) in enumerate(row):
            cells.append("   X" if (y, x) in detector.dead_zones else
                         f"{distance:4}" if valid and distance > 0 else "   -")
        print(f"{y:>2}  " + " ".join(cells))
    print("X=dead zone, -=invalid, all other values are millimeters")


def print_summary(frames, detector):
    oriented = [orient_grid(grid, detector.rotation) for grid in frames]
    counts = [len(active_readings(grid, detector.dead_zones)) for grid in oriented]
    print(f"Active valid zones per frame: min={min(counts)} max={max(counts)} "
          f"required={detector.config.min_valid}")
    print("Per-zone median mm/valid frames (X=dead, -=no valid samples):")
    print("       " + " ".join(f"{x:>9}" for x in range(8)))
    for y in range(8):
        cells = []
        for x in range(8):
            values = [grid[y][x][0] for grid in oriented
                      if grid[y][x][1] and grid[y][x][0] > 0]
            if (y, x) in detector.dead_zones:
                cell = "X"
            elif values:
                cell = f"{statistics.median(values):g}/{len(values)}"
            else:
                cell = "-"
            cells.append(f"{cell:>9}")
        print(f"{y:>2}   " + " ".join(cells))


def capture(sensor, detector, duration):
    frames = []
    start = time.monotonic()
    last_frame = start
    while time.monotonic() - start < duration:
        now = time.monotonic()
        if sensor.check_data_ready():
            grid = read_grid(sensor)
            if not frames:
                print_grid(grid, detector)
            frames.append(grid)
            count = len(active_readings(orient_grid(grid, detector.rotation), detector.dead_zones))
            LOG.debug("Calibration frame=%d active_valid=%d", len(frames), count)
            last_frame = now
        elif now - last_frame > detector.config.frame_timeout:
            raise TimeoutError(f"No sensor frame for {now - last_frame:.1f} seconds")
        time.sleep(0.02)
    print(f"Captured {len(frames)} frames in {time.monotonic() - start:.1f} seconds.")
    if frames:
        print_summary(frames, detector)
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10,
                        help="capture duration per condition (default: 10)")
    parser.add_argument("--log-level", choices=("INFO", "DEBUG"), default="INFO")
    parser.add_argument("--log-file", help="append detailed logs to this file")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be positive and finite")
    handlers = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    try:
        detector = sensor_config.create_detector()
        LOG.info("Calibration config: %s rotation=%d dead_zones=%s hz=%d",
                 detector.config, detector.rotation, sorted(detector.dead_zones),
                 sensor_config.RANGING_HZ)
        input("Clear the sensor's approach area, then press Enter to capture EMPTY: ")
        sensor, i2c = make_sensor(sensor_config.RANGING_HZ)
        try:
            empty = capture(sensor, detector, args.seconds)
            input("Place the swimmer at the wall, then press Enter to capture OCCUPIED: ")
            occupied = capture(sensor, detector, args.seconds)
        finally:
            close_sensor(sensor, i2c)
        enter, exit_mm, empty_range, occupied_range = recommend(empty, occupied, detector)
        print(f"MIN_ZONES-th nearest distance: empty={empty_range}, occupied={occupied_range} mm")
        print(f"Candidate values for sensor_config.py:\nENTER_MM = {enter}\nEXIT_MM = {exit_mm}")
        print("Review and copy manually; re-run and validate in real pool conditions.")
    except (OSError, RuntimeError, ValueError, IndexError, struct.error, EOFError):
        LOG.exception("Calibration failed; no configuration was changed")
        return 1
    except KeyboardInterrupt:
        print("\nCalibration cancelled; no configuration was changed.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
