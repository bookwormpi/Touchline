#!/usr/bin/env python3
"""Touchline application: display, buttons, VL53L8CX and workout controller."""

import argparse
import io
import logging
import math
from pathlib import Path
import shlex
import struct
import subprocess
import threading
import time
import wave

from detection import DetectionConfig, OccupancyDetector
from interface_ai import MENU_ITEMS, create_matrix, render_frame
from workout import Phase, WorkoutSession

LOG = logging.getLogger("touchline")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prev", "next", "ok"):
        parser.add_argument(f"--{name}-pin", type=int, required=True,
                            help=f"BCM GPIO number for {name.upper()} button")
    parser.add_argument("--enter-mm", type=int, default=1000)
    parser.add_argument("--exit-mm", type=int, default=1200)
    parser.add_argument("--min-zones", type=int, default=3)
    parser.add_argument("--min-valid", type=int, default=8)
    parser.add_argument("--enter-debounce", type=float, default=0.3)
    parser.add_argument("--exit-debounce", type=float, default=0.5)
    parser.add_argument("--sensor-timeout", type=float, default=1.0)
    parser.add_argument("--hz", type=int, default=10, choices=range(1, 16))
    parser.add_argument("--audio-command", default=None,
                        help="optional player command reading WAV from stdin, e.g. 'aplay -q'")
    args = parser.parse_args()
    pins = (args.prev_pin, args.next_pin, args.ok_pin)
    if len(set(pins)) != 3 or any(pin < 0 or pin > 27 or pin in (2, 3) for pin in pins):
        parser.error("Use three distinct BCM pins in 0..27, excluding I2C pins 2 and 3")
    try:
        args.detection = DetectionConfig(
            args.enter_mm, args.exit_mm, args.min_zones, args.min_valid,
            args.enter_debounce, args.exit_debounce, args.sensor_timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.audio_command is not None:
        try:
            args.audio_command = shlex.split(args.audio_command)
        except ValueError as exc:
            parser.error(f"Invalid audio command: {exc}")
        if not args.audio_command:
            parser.error("Audio command must not be empty")
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

    i2c = busio.I2C(board.SCL, board.SDA)
    try:
        original_find_file = vl53lxcx._find_file
        vl53lxcx._find_file = find_firmware
        try:
            sensor = vl53lxcx.VL53L8CX(i2c)
        finally:
            vl53lxcx._find_file = original_find_file
        if not sensor.is_alive():
            raise OSError("VL53L8CX not responding")
        sensor.init()
        sensor.resolution = vl53lxcx.RESOLUTION_8X8
        sensor.ranging_freq = hz
        sensor.start_ranging({vl53lxcx.DATA_DISTANCE_MM, vl53lxcx.DATA_TARGET_STATUS})
    except (OSError, RuntimeError, ValueError):
        i2c.deinit()
        raise
    return sensor, i2c


def close_sensor(sensor, i2c):
    if sensor is not None:
        try:
            sensor.stop_ranging()
        except (OSError, RuntimeError) as exc:
            LOG.warning("Could not stop sensor: %s", exc)
    if i2c is not None:
        i2c.deinit()


def read_grid(sensor):
    from vl53lxcx import STATUS_VALID
    data = sensor.get_ranging_data()
    return [[(data.distance_mm[y * 8 + x],
              data.target_status[y * 8 + x] == STATUS_VALID)
             for x in range(8)] for y in range(8)]


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


class Audio:
    def __init__(self, command):
        self.command = command
        self.thread = None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            samples = (int(9000 * math.sin(2 * math.pi * 880 * i / 16000))
                       for i in range(2400))
            wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
        self.tone = buf.getvalue()

    def play(self):
        if self.command is None or (self.thread and self.thread.is_alive()):
            return
        self.thread = threading.Thread(target=self._play, daemon=True)
        self.thread.start()

    def _play(self):
        try:
            result = subprocess.run(self.command, input=self.tone, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, timeout=5, check=False)
            if result.returncode:
                LOG.error("Audio player exited %s: %s", result.returncode,
                          result.stderr.decode(errors="replace").strip())
        except (OSError, subprocess.TimeoutExpired) as exc:
            LOG.error("Audio cue failed: %s", exc)


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
    detector = OccupancyDetector(args.detection)
    audio = Audio(args.audio_command)
    matrix = create_matrix()
    buttons = {}
    sensor = None
    i2c = None
    connected_at = 0.0
    menu = None
    retry_at = 0.0
    last_draw = 0.0
    try:
        for name in ("prev", "next", "ok"):
            buttons[name] = Button(getattr(args, f"{name}_pin"), pull_up=True)
        inputs = ButtonInput(buttons)
        canvas = matrix.CreateFrameCanvas()
        while True:
            now = time.monotonic()
            for event in inputs.poll(now):
                menu = handle_button(event, session, now, menu)

            if sensor is None and now >= retry_at:
                try:
                    sensor, i2c = make_sensor(args.hz)
                    connected_at = time.monotonic()
                    LOG.info("Sensor connected")
                except (OSError, RuntimeError) as exc:
                    LOG.error("Sensor connection failed: %s", exc)
                    retry_at = time.monotonic() + 2
                now = time.monotonic()

            if sensor is not None:
                try:
                    if sensor.check_data_ready():
                        event = detector.update(read_grid(sensor), now)
                        if event:
                            session.sensor_event(event, now)
                            if session.phase in (Phase.BREAK, Phase.COMPLETE):
                                menu = None
                    if (detector.check_timeout(now)
                            and now - connected_at >= args.detection.frame_timeout):
                        LOG.error("Sensor data unavailable or invalid; reconnecting")
                        close_sensor(sensor, i2c)
                        sensor = None
                        i2c = None
                        retry_at = now + 2
                except (OSError, RuntimeError) as exc:
                    LOG.error("Sensor I/O error: %s", exc)
                    close_sensor(sensor, i2c)
                    sensor = None
                    i2c = None
                    detector.last_valid = None
                    detector.check_timeout(now)
                    retry_at = now + 2
            if session.tick(now):
                audio.play()
            if now - last_draw >= 0.1:
                canvas.SetImage(render_frame(session, detector, now, menu))
                canvas = matrix.SwapOnVSync(canvas)
                last_draw = now
            time.sleep(0.02)
    finally:
        close_sensor(sensor, i2c)
        for button in buttons.values():
            button.close()
        matrix.Clear()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        LOG.info("Stopping")


if __name__ == "__main__":
    main()
