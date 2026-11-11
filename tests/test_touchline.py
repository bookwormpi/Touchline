import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from detection import DetectionConfig, OccupancyDetector
from interface_ai import create_matrix, render_frame
from main import ButtonInput, handle_button, make_sensor, read_grid, run
from workout import Phase, SwimSet, Workout, WorkoutSession


def session_for(*sets):
    return WorkoutSession((Workout("TEST", sets),))


class WorkoutTests(unittest.TestCase):
    def test_validate_workout_definitions(self):
        for args in (("FR", 30, 2, 60), ("FR", 25, 3, 60),
                     ("FR", 50, 0, 60), ("FR", 50, 1, 0),
                     ("FR", 50, 1, 60, 0), ("FR", 50, 1, 60, 30, -1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                SwimSet(*args)
        with self.assertRaises(ValueError):
            Workout("EMPTY", ())
        with self.assertRaises(ValueError):
            WorkoutSession(())

    def test_fifty_progression_and_sendoffs_follow_actual_departure(self):
        session = session_for(SwimSet("FR", 50, 2, 60), SwimSet("BK", 50, 1, 70))
        session.confirm(100)
        self.assertEqual(session.phase, Phase.READY)
        self.assertTrue(session.tick(100))
        self.assertFalse(session.tick(100))
        session.sensor_event("arrived", 101)
        self.assertEqual(session.phase, Phase.READY)
        session.sensor_event("left", 110)
        self.assertEqual(session.next_sendoff(120), (170, "WALL"))
        self.assertTrue(session.tick(170))
        self.assertFalse(session.tick(171))
        session.sensor_event("arrived", 180)
        self.assertEqual(session.history, [(50, "FR", 70, False)])
        self.assertEqual(session.next_sendoff(180), (170, "WALL"))
        self.assertFalse(session.tick(180))
        session.sensor_event("left", 190)
        self.assertIsNone(session.next_sendoff(200))
        session.sensor_event("arrived", 220)
        self.assertEqual(session.phase, Phase.BREAK)
        self.assertEqual(session.completed, 2)
        session.confirm(230)
        self.assertEqual((session.phase, session.set_index, session.completed),
                         (Phase.READY, 1, 0))
        self.assertEqual(session.next_sendoff(230), (230, "WALL"))
        session.sensor_event("left", 240)
        session.sensor_event("arrived", 270)
        self.assertEqual(session.phase, Phase.COMPLETE)
        session.confirm(280)
        self.assertEqual(session.phase, Phase.SELECT)
        self.assertEqual(session.history, [])

    def test_twenty_five_estimates_far_cues_and_last_rep(self):
        session = session_for(SwimSet("FR", 25, 4, 50))
        session.confirm(0)
        session.sensor_event("left", 10)
        self.assertEqual(session.next_sendoff(59), (60, "FAR"))
        self.assertFalse(session.tick(59))
        self.assertTrue(session.tick(60))
        self.assertFalse(session.tick(61))
        self.assertEqual(session.next_sendoff(60), (110, "WALL"))
        session.sensor_event("arrived", 95)
        self.assertEqual(session.history, [(25, "FR", 35, True)] * 2)
        self.assertEqual(session.completed, 2)
        self.assertTrue(session.tick(110))
        self.assertFalse(session.tick(111))
        session.sensor_event("left", 120)
        self.assertEqual(session.next_sendoff(169), (170, "FAR"))
        self.assertIsNone(session.next_sendoff(170))
        session.sensor_event("arrived", 160)
        self.assertEqual(session.history[:2], [(25, "FR", None, True)] * 2)
        self.assertEqual(session.phase, Phase.COMPLETE)

    def test_late_rest_and_extra_rest_rearm_cues(self):
        session = session_for(SwimSet("FR", 50, 2, 60, extra_rest=20, late_rest=15))
        session.confirm(0)
        session.sensor_event("left", 10)
        self.assertTrue(session.tick(70))
        session.sensor_event("arrived", 80)
        self.assertEqual(session.next_sendoff(80), (95, "WALL"))
        self.assertFalse(session.tick(94))
        self.assertTrue(session.tick(95))
        self.assertTrue(session.extra_rest(100))
        self.assertEqual(session.next_sendoff(100), (120, "WALL"))
        self.assertTrue(session.tick(120))
        session.sensor_event("left", 121)
        self.assertFalse(session.extra_rest(130))

    def test_manual_completion_standby_and_selection(self):
        session = WorkoutSession((Workout("A", (SwimSet("FR", 50, 1, 60),)),
                                  Workout("B", (SwimSet("BK", 50, 1, 60),))))
        self.assertFalse(session.complete_set())
        session.select_delta(-1)
        self.assertEqual(session.workout.name, "B")
        session.confirm(0)
        session.sensor_event("left", 2)
        self.assertTrue(session.complete_set())
        self.assertEqual(session.phase, Phase.COMPLETE)
        self.assertEqual(session.history, [])
        session.standby()
        self.assertEqual(session.phase, Phase.STANDBY)
        session.confirm(3)
        self.assertEqual(session.phase, Phase.SELECT)
        self.assertEqual(session.workout.name, "B")


class SensorTests(unittest.TestCase):
    def test_debounce_hysteresis_invalid_frames_and_recovery(self):
        config = DetectionConfig(min_zones=3, min_valid=8,
                                 enter_seconds=0.3, exit_seconds=0.5, frame_timeout=1)
        detector = OccupancyDetector(config)
        near = [[(500, True)] * 8 for _ in range(8)]
        far = [[(1500, True)] * 8 for _ in range(8)]
        invalid = [[(0, False)] * 8 for _ in range(8)]
        self.assertIsNone(detector.update(near, 0))
        self.assertIsNone(detector.update(near, 0.4))
        self.assertTrue(detector.occupied)
        self.assertIsNone(detector.update(far, 0.5))
        self.assertIsNone(detector.update(invalid, 0.8))
        self.assertIsNone(detector.update(far, 0.9))
        self.assertEqual(detector.update(far, 1.5), "left")
        self.assertIsNone(detector.update(near, 1.6))
        self.assertEqual(detector.update(near, 2.0), "arrived")
        self.assertTrue(detector.check_timeout(3.1))
        self.assertIsNone(detector.occupied)
        self.assertIsNone(detector.update(far, 3.2))
        self.assertIsNone(detector.update(far, 3.8))
        self.assertFalse(detector.occupied)
        self.assertFalse(detector.fault)

    def test_sensor_events_drive_workout(self):
        detector = OccupancyDetector(DetectionConfig(enter_seconds=0.1, exit_seconds=0.1))
        session = session_for(SwimSet("FR", 50, 1, 60))
        session.confirm(0)
        near = [[(500, True)] * 8 for _ in range(8)]
        far = [[(1500, True)] * 8 for _ in range(8)]
        for now, grid in ((0, near), (0.2, near), (0.3, far), (0.5, far),
                          (0.6, near), (0.8, near)):
            event = detector.update(grid, now)
            if event:
                session.sensor_event(event, now)
        self.assertEqual(session.phase, Phase.COMPLETE)
        self.assertAlmostEqual(session.history[0][2], 0.3)

    def test_sensor_driver_initialization_and_grid(self):
        sensor = Mock()
        sensor.is_alive.return_value = True
        sensor.get_ranging_data.return_value = types.SimpleNamespace(
            distance_mm=list(range(64)), target_status=[5, 0] * 32)
        i2c = Mock()
        driver = types.ModuleType("vl53lxcx")
        driver.DATA_DISTANCE_MM = "distance"
        driver.DATA_TARGET_STATUS = "status"
        driver.RESOLUTION_8X8 = 64
        driver.STATUS_VALID = 5
        driver.VL53L8CX = Mock(return_value=sensor)
        driver._find_file = Mock()
        board = types.SimpleNamespace(SCL="scl", SDA="sda")
        busio = types.SimpleNamespace(I2C=Mock(return_value=i2c))
        with patch.dict(sys.modules, {"board": board, "busio": busio, "vl53lxcx": driver}):
            self.assertEqual(make_sensor(10), (sensor, i2c))
            self.assertEqual(sensor.resolution, 64)
            self.assertEqual(sensor.ranging_freq, 10)
            sensor.start_ranging.assert_called_once_with({"distance", "status"})
            grid = read_grid(sensor)
        self.assertEqual(grid[0][:2], [(0, True), (1, False)])
        self.assertEqual(grid[7][-1], (63, False))

    def test_sensor_initialization_failure_releases_i2c(self):
        sensor = Mock()
        sensor.is_alive.return_value = False
        i2c = Mock()
        driver = types.SimpleNamespace(DATA_DISTANCE_MM="distance", DATA_TARGET_STATUS="status",
                                       RESOLUTION_8X8=64, VL53L8CX=Mock(return_value=sensor),
                                       _find_file=Mock())
        with patch.dict(sys.modules, {"board": types.SimpleNamespace(SCL=1, SDA=2),
                                      "busio": types.SimpleNamespace(I2C=Mock(return_value=i2c)),
                                      "vl53lxcx": driver}):
            with self.assertRaises(OSError):
                make_sensor(10)
        i2c.deinit.assert_called_once_with()

    def test_sensor_firmware_lookup_in_dotted_python_path(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / ".venv/lib/python3.13/site-packages/vl53lxcx"
            package.mkdir(parents=True)
            firmware = package / "vl53l8cx_fw.bin"
            firmware.write_bytes(b"x" * 88540)
            driver = types.ModuleType("vl53lxcx")
            driver.__file__ = str(package / "__init__.py")
            driver._find_file = Mock(side_effect=ValueError("broken upstream lookup"))
            original = driver._find_file
            driver.DATA_DISTANCE_MM = "distance"
            driver.DATA_TARGET_STATUS = "status"
            driver.RESOLUTION_8X8 = 64
            sensor = Mock()
            sensor.is_alive.return_value = True

            def construct(i2c):
                broken_path = str(package).rsplit(".", 1)[0] + "/vl53l8cx_fw.bin"
                self.assertEqual(driver._find_file(broken_path, 88540), str(firmware.resolve()))
                return sensor

            driver.VL53L8CX = construct
            i2c = Mock()
            modules = {"board": types.SimpleNamespace(SCL=1, SDA=2),
                       "busio": types.SimpleNamespace(I2C=Mock(return_value=i2c)),
                       "vl53lxcx": driver}
            with patch.dict(sys.modules, modules):
                self.assertEqual(make_sensor(10), (sensor, i2c))
                self.assertIs(driver._find_file, original)
                firmware.unlink()
                with self.assertRaisesRegex(FileNotFoundError, "Sensor firmware not found"):
                    make_sensor(10)
                self.assertIs(driver._find_file, original)
                i2c.deinit.assert_called_once_with()
                firmware.write_bytes(b"bad")
                with self.assertRaisesRegex(ValueError, "incorrect size"):
                    make_sensor(10)
                self.assertIs(driver._find_file, original)
                self.assertEqual(i2c.deinit.call_count, 2)


class InterfaceTests(unittest.TestCase):
    def test_render_each_workout_phase(self):
        session = session_for(SwimSet("FR", 50, 1, 60))
        detector = OccupancyDetector(DetectionConfig())
        self.assertEqual(render_frame(session, detector, 0).size, (128, 64))
        session.confirm(1)
        for menu in (None, 0, 6, 7):
            self.assertEqual(render_frame(session, detector, 1, menu).size, (128, 64))
        session.sensor_event("left", 2)
        self.assertEqual(render_frame(session, detector, 3).size, (128, 64))
        session.sensor_event("arrived", 4)
        self.assertEqual(render_frame(session, detector, 4).size, (128, 64))
        session.standby()
        self.assertEqual(render_frame(session, detector, 5).size, (128, 64))

    def test_matrix_configuration(self):
        driver = types.ModuleType("rgbmatrix")
        driver.RGBMatrixOptions = type("Options", (), {})
        driver.RGBMatrix = Mock()
        with patch.dict(sys.modules, {"rgbmatrix": driver}):
            create_matrix()
        options = driver.RGBMatrix.call_args.kwargs["options"]
        self.assertEqual((options.rows, options.cols, options.hardware_mapping),
                         (64, 128, "adafruit-hat"))

    def test_buttons_and_menu_confirmation(self):
        ok = types.SimpleNamespace(is_pressed=False)
        inputs = ButtonInput({"ok": ok}, debounce=0.05, hold=1.5)
        ok.is_pressed = True
        self.assertEqual(inputs.poll(1), [])
        self.assertEqual(inputs.poll(1.1), [])
        self.assertEqual(inputs.poll(2.7), ["hold"])
        ok.is_pressed = False
        inputs.poll(2.8)
        self.assertEqual(inputs.poll(2.9), [])
        session = session_for(SwimSet("FR", 50, 1, 60))
        session.confirm(0)
        menu = handle_button("next", session, 1, None)
        menu = handle_button("next", session, 1, menu)
        menu = handle_button("next", session, 1, menu)
        self.assertEqual(menu, 2)
        menu = handle_button("ok", session, 1, menu)
        self.assertEqual(session.phase, Phase.READY)
        self.assertIsNone(handle_button("ok", session, 1, menu))
        self.assertEqual(session.phase, Phase.COMPLETE)

    def test_main_loop_draws_and_releases_hardware(self):
        matrix = Mock()
        sensor = Mock()
        sensor.check_data_ready.return_value = False
        i2c = Mock()
        buttons = [Mock(is_pressed=False) for _ in range(3)]
        gpio = types.SimpleNamespace(Button=Mock(side_effect=buttons))
        args = types.SimpleNamespace(
            detection=DetectionConfig(), audio_command=None,
            prev_pin=17, next_pin=18, ok_pin=27, hz=10)
        with patch.dict(sys.modules, {"gpiozero": gpio}), \
                patch("main.create_matrix", return_value=matrix), \
                patch("main.make_sensor", return_value=(sensor, i2c)), \
                patch("main.time.monotonic", return_value=100), \
                patch("main.time.sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run(args)
        matrix.CreateFrameCanvas.return_value.SetImage.assert_called_once()
        matrix.SwapOnVSync.assert_called_once()
        matrix.Clear.assert_called_once()
        sensor.stop_ranging.assert_called_once()
        i2c.deinit.assert_called_once()
        for button in buttons:
            button.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()