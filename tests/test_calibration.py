import contextlib
import io
import types
import unittest
from unittest.mock import Mock, patch

from calibrate_sensor import capture, main as calibrate_main, print_grid, print_summary, recommend
from detection import DetectionConfig, OccupancyDetector, orient_grid
from main import parse_args, read_grid, run
from sensor_config import create_detector


def frame(value):
    return [[(value, True) for _ in range(8)] for _ in range(8)]


class RotationAndMaskTests(unittest.TestCase):
    def test_button_pins_from_configuration(self):
        with patch("sys.argv", ["main.py"]):
            args = parse_args()
        self.assertEqual((args.prev_pin, args.next_pin, args.ok_pin), (18, 19, 25))
        with patch("sys.argv", ["main.py"]), patch("sensor_config.NEXT_PIN", 18), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_clockwise_rotation_coordinates(self):
        source = [[(y * 8 + x, True) for x in range(8)] for y in range(8)]
        for angle, expected in ((0, 0), (90, 56), (180, 63), (270, 7)):
            with self.subTest(angle=angle):
                self.assertEqual(orient_grid(source, angle)[0][0][0], expected)
        with self.assertRaises(ValueError):
            orient_grid(source, 45)

    def test_dead_zone_after_rotation_excluded_from_detection(self):
        sensor = frame(1500)
        sensor[7][0] = (500, True)
        config = DetectionConfig(min_zones=1, min_valid=2, enter_seconds=0.1, exit_seconds=0.1)
        detector = OccupancyDetector(config, rotation=90, dead_zones={(0, 0)})
        detector.update(sensor, 0)
        detector.update(sensor, 0.2)
        self.assertFalse(detector.occupied)
        sensor[7][1] = (500, True)
        detector.update(sensor, 0.3)
        self.assertEqual(detector.update(sensor, 0.5), "arrived")

    def test_invalid_configuration_rejected(self):
        config = DetectionConfig()
        for dead in ({(8, 0)}, {("1", 0)}, {(0,)}):
            with self.subTest(dead=dead), self.assertRaises(ValueError):
                OccupancyDetector(config, dead_zones=dead)
        with self.assertRaisesRegex(ValueError, "fewer active zones"):
            OccupancyDetector(config, dead_zones={(y, x) for y in range(8) for x in range(8)})
        with self.assertRaises(ValueError):
            DetectionConfig(frame_timeout=float("nan"))
        with patch("sensor_config.RANGING_HZ", 16), self.assertRaises(ValueError):
            create_detector()

    def test_calibration_grid_shows_same_orientation_and_mask(self):
        detector = OccupancyDetector(DetectionConfig(), rotation=90, dead_zones={(0, 0)})
        with contextlib.redirect_stdout(io.StringIO()) as output:
            print_grid(frame(1500), detector)
        self.assertIn("X", output.getvalue().splitlines()[1])


class GuidedCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.detector = OccupancyDetector(DetectionConfig(min_zones=3, min_valid=8))

    def test_recommendations_separate_every_captured_frame(self):
        empty = [frame(1800) for _ in range(5)]
        occupied = [frame(800) for _ in range(5)]
        enter, exit_mm, erange, orange = recommend(empty, occupied, self.detector)
        self.assertGreaterEqual(enter, 800)
        self.assertLess(enter, exit_mm)
        self.assertLessEqual(exit_mm, 1800)
        self.assertEqual((erange, orange), ((1800, 1800), (800, 800)))
        for grid in empty:
            self.assertLess(sum(mm < exit_mm for row in grid for mm, valid in row if valid), 3)
        for grid in occupied:
            self.assertGreaterEqual(sum(mm <= enter for row in grid for mm, valid in row if valid), 3)

    def test_overlapping_insufficient_or_invalid_samples_never_recommend(self):
        empty = [frame(1000) for _ in range(5)]
        for occupied in ([frame(1000) for _ in range(5)], [frame(500)] * 4):
            with self.assertRaises(ValueError):
                recommend(empty, occupied, self.detector)
        invalid = frame(500)
        for row in invalid:
            row[:] = [(0, False)] * 8
        with self.assertRaisesRegex(ValueError, "fewer than"):
            recommend(empty, [invalid] * 5, self.detector)

    def test_capture_timeout_fails_instead_of_suggesting(self):
        sensor = Mock()
        sensor.check_data_ready.return_value = False
        with patch("calibrate_sensor.time.monotonic", side_effect=[0, 0, 2]), \
                patch("calibrate_sensor.time.sleep"):
            with self.assertRaises(TimeoutError):
                capture(sensor, self.detector, 10)

    def test_summary_exposes_per_zone_valid_counts(self):
        grids = [frame(1000), frame(2000)]
        grids[1][0][0] = (0, False)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            print_summary(grids, self.detector)
        self.assertIn("min=63 max=64 required=8", output.getvalue())
        self.assertIn("1000/1", output.getvalue())
        self.assertIn("1500/2", output.getvalue())

    def test_guided_workflow_uses_capture_and_closes_sensor(self):
        sensor, i2c = Mock(), Mock()
        with patch("sys.argv", ["calibrate_sensor.py", "--seconds", "2"]), \
                patch("builtins.input", side_effect=["", ""]), \
                patch("calibrate_sensor.make_sensor", return_value=(sensor, i2c)), \
                patch("calibrate_sensor.capture", side_effect=[[frame(1800)] * 5,
                                                               [frame(800)] * 5]) as captures, \
                patch("calibrate_sensor.close_sensor") as close, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(calibrate_main(), 0)
        self.assertIn("ENTER_MM = 1133", output.getvalue())
        self.assertIn("EXIT_MM = 1466", output.getvalue())
        self.assertEqual(captures.call_count, 2)
        close.assert_called_once_with(sensor, i2c)

    def test_guided_workflow_closes_sensor_on_capture_error(self):
        sensor, i2c = Mock(), Mock()
        with patch("sys.argv", ["calibrate_sensor.py"]), \
                patch("builtins.input", return_value=""), \
                patch("calibrate_sensor.make_sensor", return_value=(sensor, i2c)), \
                patch("calibrate_sensor.capture", side_effect=OSError(5, "I/O error")), \
                patch("calibrate_sensor.close_sensor") as close, \
                self.assertLogs("touchline", level="ERROR") as logs:
            self.assertEqual(calibrate_main(), 1)
        self.assertIn("Calibration failed", logs.output[0])
        self.assertIn("I/O error", logs.output[0])
        close.assert_called_once_with(sensor, i2c)

    def test_read_grid_debug_logs_statuses(self):
        driver = Mock(STATUS_VALID=5)
        sensor = Mock()
        sensor.get_ranging_data.return_value.distance_mm = [1000] * 64
        sensor.get_ranging_data.return_value.target_status = [5] * 63 + [9]
        with patch.dict("sys.modules", {"vl53lxcx": driver}), \
                self.assertLogs("touchline", level="DEBUG") as logs:
            read_grid(sensor)
        self.assertIn("status_counts={5: 63, 9: 1}", logs.output[0])

    def test_application_reports_invalid_frames_separately_from_io_error(self):
        broken, recovered = Mock(), Mock()
        broken.check_data_ready.return_value = True
        recovered.check_data_ready.return_value = False
        i2c1, i2c2 = Mock(), Mock()
        clock = [100.0]
        def sleep(_duration):
            clock[0] += 0.6
            if clock[0] > 104:
                raise KeyboardInterrupt
        args = types.SimpleNamespace(
            settings_file="/nonexistent/touchline/settings.json",
            sounds_dir="/nonexistent/touchline/sounds",
            prev_pin=18, next_pin=19, ok_pin=25)
        gpio = types.SimpleNamespace(Button=Mock(return_value=Mock(is_pressed=False)))
        invalid = [[(0, False)] * 8 for _ in range(8)]
        with patch.dict("sys.modules", {"gpiozero": gpio}), \
                patch("main.create_matrix", return_value=Mock()), \
                patch("main.Audio"), \
                patch("main.make_sensor", side_effect=[(broken, i2c1), (recovered, i2c2)]), \
                patch("main.read_grid", return_value=invalid), \
                patch("main.time.monotonic", side_effect=lambda: clock[0]), \
                patch("main.time.sleep", side_effect=sleep), \
                self.assertLogs("touchline", level="ERROR") as logs:
            with self.assertRaises(KeyboardInterrupt):
                run(args)
        self.assertIn("ready_frames=3 usable_frames=0", logs.output[0])
        self.assertIn("last_usable_age=never", logs.output[0])
        i2c1.deinit.assert_called_once()
        i2c2.deinit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
