#!/usr/bin/env python3
"""Touchline application: display, buttons, VL53L8CX and workout controller."""

import argparse
from collections import Counter
import logging
from pathlib import Path
import struct
import time

from audio import Audio
from detection import active_readings, orient_grid
from interface_ai import MENU_ITEMS, create_matrix, render_frame
from navigation import Navigation
import sensor_config
from settings import Settings, load_settings, save_settings
from workout import Phase, WorkoutSession

LOG = logging.getLogger("touchline")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings-file", default="/var/lib/touchline/settings.json")
    parser.add_argument("--sounds-dir", default=str(Path(__file__).resolve().parent / "sounds"))
    parser.add_argument("--log-level", choices=("INFO", "DEBUG"), default="INFO")
    parser.add_argument("--log-file", help="append detailed logs to this file")
    args = parser.parse_args()
    args.prev_pin = sensor_config.PREV_PIN
    args.next_pin = sensor_config.NEXT_PIN
    args.ok_pin = sensor_config.OK_PIN
    pins = (args.prev_pin, args.next_pin, args.ok_pin)
    if (any(type(pin) is not int or pin < 0 or pin > 27 or pin in (2, 3) for pin in pins)
            or len(set(pins)) != 3):
        parser.error("sensor_config.py must define three distinct BCM pins in 0..27, "
                     "excluding I2C pins 2 and 3")
    try:
        sensor_config.create_detector()
    except ValueError as exc:
        parser.error(str(exc))
    return args


def make_sensor(hz):
    import board
    import busio
    import vl53lxcx

    def find_firmware(name, required_size):
        # Version 0.0.5 truncates paths containing dots before searching sys.path.
        path = Path(vl53lxcx.__file__).resolve().parent / Path(name).name
        try:
            size = path.stat().st_size
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Sensor firmware not found at {path}; reinstall circuitpython-vl53lxcx==0.0.5"
            ) from exc
        if size != required_size:
            raise ValueError(f"Sensor firmware has incorrect size: {path} ({size} bytes)")
        return str(path)

    LOG.info("Sensor init: opening I2C; target=0x29 resolution=8x8 frequency=%s Hz", hz)
    i2c = busio.I2C(board.SCL, board.SDA)
    try:
        original_find_file = vl53lxcx._find_file
        vl53lxcx._find_file = find_firmware
        try:
            sensor = vl53lxcx.VL53L8CX(i2c)
        finally:
            vl53lxcx._find_file = original_find_file
        LOG.info("Sensor init: probing device")
        if not sensor.is_alive():
            raise OSError("VL53L8CX not responding")
        LOG.info("Sensor init: loading firmware and configuring ranging")
        sensor.init()
        sensor.resolution = vl53lxcx.RESOLUTION_8X8
        sensor.ranging_freq = hz
        if not sensor.start_ranging({vl53lxcx.DATA_DISTANCE_MM, vl53lxcx.DATA_TARGET_STATUS}):
            raise OSError("Sensor did not start ranging with the requested data")
        LOG.info("Sensor init: ranging started; awaiting frames")
    except (OSError, RuntimeError, ValueError, IndexError, struct.error):
        try:
            i2c.deinit()
        except (OSError, RuntimeError) as exc:
            LOG.warning("Could not release I2C after initialization failure: %s", exc)
        raise
    return sensor, i2c


def close_sensor(sensor, i2c):
    if sensor is not None:
        try:
            sensor.stop_ranging()
        except (OSError, RuntimeError, ValueError) as exc:
            LOG.warning("Could not stop sensor: %s", exc)
    if i2c is not None:
        try:
            i2c.deinit()
        except (OSError, RuntimeError) as exc:
            LOG.warning("Could not release I2C: %s", exc)


class SensorGrid(list):
    """Distance/valid grid retaining the driver's original per-zone statuses."""

    def __init__(self, rows, statuses):
        super().__init__(rows)
        self.statuses = statuses


def _frame_values(values):
    if values is None:
        return None
    return list(values[:256])


def read_grid(sensor):
    from vl53lxcx import STATUS_VALID
    data = sensor.get_ranging_data()
    distances = getattr(data, "distance_mm", None)
    statuses = getattr(data, "target_status", None)
    if distances is None or statuses is None:
        LOG.warning("Bad sensor frame: missing data distances=%s target_status=%s",
                    _frame_values(distances), _frame_values(statuses))
        raise ValueError("Sensor frame missing distance or target status data")
    if len(distances) != 64 or len(statuses) != 64:
        LOG.warning("Bad sensor frame: incorrect lengths distances=%d target_status=%d "
                    "distance_mm=%s target_status_values=%s (values capped at 256)",
                    len(distances), len(statuses), _frame_values(distances), _frame_values(statuses))
        raise ValueError("Sensor frame must contain 64 distances and target statuses")
    LOG.debug("Sensor frame status_counts=%s positive_distances=%d",
              dict(sorted(Counter(statuses).items())),
              sum(value > 0 for value in distances))
    rows = [[(distances[y * 8 + x], statuses[y * 8 + x] == STATUS_VALID)
             for x in range(8)] for y in range(8)]
    return SensorGrid(rows, [list(statuses[y * 8:y * 8 + 8]) for y in range(8)])


def log_bad_frame(grid, detector, context):
    """Log frames with no valid active-zone measurements."""
    oriented = orient_grid(grid, detector.rotation)
    count = len(active_readings(oriented, detector.dead_zones))
    if count:
        return
    statuses = getattr(grid, "statuses", None)
    if statuses is not None:
        statuses = orient_grid(statuses, detector.rotation)
    LOG.warning("Sensor frame with no valid active zones (%s): active_valid=%d rotation=%d "
                "assumed_distance_mm=%d dead_zones=%s distance_mm=%s valid=%s target_status=%s",
                context, count, detector.rotation, detector.config.max_distance_mm,
                sorted(detector.dead_zones),
                [[distance for distance, _ in row] for row in oriented],
                [[valid for _, valid in row] for row in oriented], statuses)


class ButtonInput:
    """Poll and debounce buttons, reporting an OK hold only once."""

    def __init__(self, buttons, debounce=0.05, hold=1.5):
        self.buttons = buttons
        self.debounce = debounce
        self.hold = hold
        self.raw = {name: False for name in buttons}
        self.stable = dict(self.raw)
        self.changed_at = {name: 0.0 for name in buttons}
        self.pressed_at = {name: None for name in buttons}
        self.held = False

    def poll(self, now):
        events = []
        for name, button in self.buttons.items():
            pressed = button.is_pressed
            if pressed != self.raw[name]:
                self.raw[name] = pressed
                self.changed_at[name] = now
            if (pressed != self.stable[name]
                    and now - self.changed_at[name] >= self.debounce):
                self.stable[name] = pressed
                if pressed:
                    self.pressed_at[name] = now
                    if name != "ok":
                        events.append(name)
                else:
                    if name == "ok" and not self.held:
                        events.append("ok")
                    self.pressed_at[name] = None
                    if name == "ok":
                        self.held = False
            if (name == "ok" and self.stable[name] and not self.held
                    and now - self.pressed_at[name] >= self.hold):
                self.held = True
                events.append("hold")
        return events


def handle_button(event, session, now, menu):
    if event == "hold":
        if session.phase == Phase.STANDBY:
            session.confirm(now)
        else:
            session.standby()
        return None
    if session.phase == Phase.STANDBY:
        if event == "ok":
            session.confirm(now)
        return None
    if session.phase == Phase.SELECT:
        if event in ("prev", "next"):
            session.select_delta(-1 if event == "prev" else 1)
        elif event == "ok":
            session.confirm(now)
        return None
    if menu is not None:
        if menu >= len(MENU_ITEMS):
            if event in ("prev", "next"):
                return menu - len(MENU_ITEMS)
            if event == "ok":
                if menu - len(MENU_ITEMS) == 2:
                    if not session.complete_set():
                        LOG.info("No active set to complete")
                        return None
                    LOG.info("Set manually marked complete; no splits were added")
                else:
                    session.reset()
                return None
        if event in ("prev", "next"):
            return (menu + (-1 if event == "prev" else 1)) % len(MENU_ITEMS)
        if event == "ok":
            if menu == 1:
                if not session.extra_rest(now):
                    LOG.info("Extra rest is only available before departure")
                    return menu
            elif menu in (2, 3):
                return menu + len(MENU_ITEMS)
            return None
    elif event in ("prev", "next"):
        return 0
    elif event == "ok":
        session.confirm(now)
    return menu


def run(args):
    from gpiozero import Button

    session = WorkoutSession()
    settings = load_settings(args.settings_file, Settings())
    detector = sensor_config.create_detector()
    LOG.info("Sensor config: %s rotation=%s dead_zones=%s hz=%s",
             detector.config, detector.rotation, sorted(detector.dead_zones),
             sensor_config.RANGING_HZ)
    navigation = Navigation()
    matrix = create_matrix()
    matrix.brightness = settings.brightness
    audio = Audio(args.sounds_dir)
    buttons = {}
    sensor = None
    i2c = None
    connected_at = 0.0
    menu = None
    retry_at = 0.0
    last_draw = 0.0
    ready_frames = 0
    usable_frames = 0
    last_frame_at = None
    previous_report = time.monotonic()
    stage = "idle"
    try:
        for name in ("prev", "next", "ok"):
            buttons[name] = Button(getattr(args, f"{name}_pin"), pull_up=True)
        inputs = ButtonInput(buttons)
        canvas = matrix.CreateFrameCanvas()
        while True:
            now = time.monotonic()
            for event in inputs.poll(now):
                if navigation.screen != "workout" or event == "hold":
                    previous_screen = navigation.screen
                    previous_settings = settings
                    settings = navigation.button(
                        event, session, settings,
                        lambda value: save_settings(args.settings_file, value))
                    if navigation.error:
                        LOG.error("Settings not changed: %s", navigation.error)
                    if settings != previous_settings:
                        matrix.brightness = settings.brightness
                    if previous_screen == "select" and navigation.screen == "workout":
                        session.confirm(now)
                        if session.tick(now) and settings.sound:
                            audio.play("start")
                    if event == "hold":
                        menu = None
                else:
                    menu = handle_button(event, session, now, menu)
                    if session.phase == Phase.SELECT:
                        navigation.screen = "home"

            if sensor is None and now >= retry_at:
                try:
                    stage = "initialization"
                    sensor, i2c = make_sensor(sensor_config.RANGING_HZ)
                    connected_at = time.monotonic()
                    ready_frames = usable_frames = 0
                    last_frame_at = None
                    LOG.info("Sensor initialized; waiting for frames")
                except (OSError, RuntimeError, ValueError, IndexError, struct.error):
                    LOG.exception("Sensor connection failed during %s; retrying in 2 seconds", stage)
                    retry_at = time.monotonic() + 2
                now = time.monotonic()

            if sensor is not None:
                try:
                    stage = "data-ready check"
                    if sensor.check_data_ready():
                        stage = "frame read"
                        ready_frames += 1
                        grid = read_grid(sensor)
                        last_frame_at = now
                        readings = active_readings(orient_grid(grid, detector.rotation),
                                                   detector.dead_zones)
                        valid_count = len(readings)
                        usable_frames += 1
                        if not valid_count:
                            log_bad_frame(grid, detector, f"workout frame {ready_frames}")
                        LOG.debug("Sensor frame active_valid=%d/%d near=%d",
                                  valid_count, 64 - len(detector.dead_zones),
                                  sum(value <= detector.config.enter_mm for value in readings))
                        previous_occupancy = detector.occupied
                        event = detector.update(grid, now)
                        if settings.sound and (event == "arrived" or
                                               (previous_occupancy is None and detector.occupied is True)):
                            audio.play("wall")
                        if event:
                            session.sensor_event(event, now)
                            if session.phase in (Phase.BREAK, Phase.COMPLETE):
                                menu = None
                    if (detector.check_timeout(now)
                            and now - connected_at >= detector.config.frame_timeout):
                        LOG.error("Sensor timeout: ready_frames=%d usable_frames=%d "
                                  "last_frame_age=%s timeout=%.2fs; reconnecting",
                                  ready_frames, usable_frames,
                                  "never" if last_frame_at is None else f"{now - last_frame_at:.2f}s",
                                  detector.config.frame_timeout)
                        close_sensor(sensor, i2c)
                        sensor = None
                        i2c = None
                        detector.invalidate()
                        retry_at = now + 2
                except (OSError, RuntimeError, ValueError, IndexError, struct.error):
                    LOG.exception("Sensor failure during %s after %.2fs: ready_frames=%d "
                                  "usable_frames=%d; reconnecting",
                                  stage, now - connected_at, ready_frames, usable_frames)
                    close_sensor(sensor, i2c)
                    sensor = None
                    i2c = None
                    detector.invalidate()
                    retry_at = now + 2
                if now - previous_report >= 30:
                    LOG.info("Sensor status: connected=%s ready_frames=%d usable_frames=%d "
                             "fault=%s occupied=%s", sensor is not None, ready_frames,
                             usable_frames, detector.fault, detector.occupied)
                    previous_report = now
            if session.tick(now):
                if settings.sound:
                    audio.play("start")
            if now - last_draw >= 0.1:
                canvas.SetImage(render_frame(session, detector, now, menu,
                                             navigation=navigation, settings=settings))
                canvas = matrix.SwapOnVSync(canvas)
                last_draw = now
            time.sleep(0.02)
    finally:
        close_sensor(sensor, i2c)
        for button in buttons.values():
            button.close()
        audio.close()
        matrix.Clear()


def main():
    args = parse_args()
    handlers = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    try:
        run(args)
    except KeyboardInterrupt:
        LOG.info("Stopping")


if __name__ == "__main__":
    main()
