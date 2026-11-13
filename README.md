# Touchline swim trainer

Touchline connects a VL53L8CX 8x8 time-of-flight sensor, a 128x64 HUB75 RGB
matrix with an Adafruit RGB Matrix Bonnet, and two buttons to a Raspberry Pi.
The sensor is mounted above the starting-block end and looks down into the
swimmer's approach area. Workouts are defined in code, not stored remotely.

**Prototype, not a certified timing or safety device.** The example thresholds,
workouts and mounting geometry must be calibrated and tested at the actual
pool. Water reflections, splashes, wet optics, lighting, other swimmers and
missing sensor returns can cause missed or false detections. Do not rely on
this system for safety, competition results, or unattended operation. Use
appropriately rated, isolated, weatherproof equipment and installation around
water; follow local electrical and pool-safety rules.

## What it does

- Debounces arrival and departure separately, with separate entry and exit
  distances and a minimum number of valid and occupied zones. The swimmer must
  be detected at the wall and then leave before a rep starts. Arrival completes
  a 50, or a pair of 25s in a 25-unit pool. A new departure starts the next
  round trip automatically.
- Shows the next send-off countdown even while swimming; after a wall send-off
  is missed, the countdown is negative by default. For 25s, `NEXT FAR` is the
  assumed far-end departure; after that scheduled time the display switches to
  `NEXT WALL`. The far-end departure cannot be verified. On the final round
  trip, `LAST REP` and `--:--` indicate that no further send-off is scheduled.
  A set may instead specify a rest period for a late arrival. The next
  send-off is based on the **actual** detected departure, not the previous
  planned time. When sound is enabled, `timestart.mp3` plays at each scheduled
  send-off, including the assumed far-end departure. `lapchime.mp3` plays once
  when a detected wall arrival completes a 50 or a pair of 25s. Initial wall
  presence and re-establishing sensor state do not count as completed laps.
- Pauses between sets until OK is pressed. A menu permits extra rest, manually
  completing a set, or ending a workout; completion and exit require
  confirmation. A manual completion does not invent any missing splits.
- The workout view shows the timer at upper left, the current set and progress
  at lower left, and up to four recent results in the right column, newest
  first. The upper-right corner of the timer pane shows the Pi's local
  24-hour time (`HH:MM`); `T` below the countdown shows elapsed time since
  starting the workout, including breaks and time after completion until exit.
  The wall clock depends on the Pi's system time and timezone; workout timing
  uses a monotonic clock. `SENSOR ERR` indicates a sensor fault and `NO SWIM`
  means the swimmer is not detected at the wall. `EST` means an inferred 25, not a measured
  split; `--:-- EST` means the inference was impossible. Sensor errors are
  displayed and logged. After a sensor outage the detector re-establishes its
  state before generating transitions, so a missed event is not reconstructed.
  The clock continues during outages; use the menu if a set must be completed
  manually.

### Estimating 25s

The sensor cannot see the far end. For a pair of 25s with send-off interval
`I` and measured departure-to-return time `T`, Touchline assumes the swimmer
departs the far end exactly `I` seconds after leaving this end and swims both
lengths in the same time. It estimates **each** 25 as `T - I`; implied far-end
rest is `I - (T - I)`. For example, 25s on 50 seconds with an 85-second round
trip produce two estimated 35-second 25s and 15 seconds of far-end rest. When
`T - I` is outside 0 through `I`, the estimates are unavailable. Detection
debounce and sensor placement also affect measured times.

Only even numbers of 25s are supported: an odd final 25 finishes out of view.
The display cannot time or signal the swimmer at the far end. A 50 is measured
only as the entire round trip, including any time spent at the far end. The
included workouts assume a 25-unit pool; distances are generic units and do not
perform yard/meter conversion.

## Controls

Wire two normally-open momentary switches between their selected GPIO inputs
and ground. Inputs use pull-ups and are active low. Never connect a button
input to 5 V. Choose **two distinct free BCM GPIO numbers** after checking the
exact bonnet, its configuration, Pi, and other peripherals. GPIO 2 and 3 are
reserved for I2C and are rejected; the application cannot detect all other
bonnet conflicts for you.

The `adafruit-hat` mapping assigns BCM 24 to the matrix's E row-address line.
Do not use GPIO 24 for a button when that line is needed or connected; 64-row
panels commonly need it. BCM 18 is used for output enable instead if you use
the `adafruit-hat-pwm` mapping. Check the actual bonnet wiring and panel before
choosing pins.

| Button | Action |
| --- | --- |
| Tap NEXT | Move forward or increase a setting; open the workout menu during a workout |
| Hold NEXT for 0.7 seconds | Move backward or decrease a setting; open the workout menu during a workout |
| Tap OK | Confirm selection, edit a setting, start a workout, or advance after a set |
| Hold OK for 1.5 seconds | Enter standby, abandoning the current workout |
| Tap OK in standby | Wake to the home screen |

Taps take effect after release. Holds trigger once and do not also produce a tap.

The start screen offers `WORKOUT` and `SETTINGS`. Choose a workout with the
NEXT and OK, or choose `BACK` to return home. In settings, use NEXT to
choose an item and OK to edit it; tap or hold NEXT to change the value and OK finishes
editing. Select `BACK` to return home. Brightness and sound are saved immediately.
Save errors appear on screen and in the log. Settings are stored in
`/var/lib/touchline/settings.json` by default; use `--settings-file` to choose
another writable path. Sensor settings are now defined only in `sensor_config.py`;
previously saved sensor settings are ignored with a warning, while brightness
and sound are retained. The former sensor command-line overrides were removed.

`EXTRA REST` moves the due time to the later of now or the existing send-off,
then adds the current set's configured extra-rest duration. It works while
waiting for departure, not while swimming. To mark a set complete, open the
menu, select `COMPLETE SET`, then confirm with OK. Tap or hold NEXT to cancel
the confirmation. `END WORKOUT` works similarly.

Standby is **software standby only**: the Pi, sensor and software remain
powered. A GPIO button cannot power on a Pi with power removed. Use an
appropriate external power controller for physical power-on and safe shutdown.
Hold OK deliberately: standby resets the current workout and its history.

## Installation and running

1. Enable I2C on the Pi. On Raspberry Pi OS with Python 3.11 or newer, run
   the matrix installer as your normal user (it requests sudo for packages):

   ```sh
   bash install-matrix.sh
   ```

   It installs build prerequisites with `apt` and installs the Python bindings
   from a pinned revision of [rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix)
   in `.venv`. It needs internet access and does not modify any existing
   `rpi-rgb-led-matrix` checkout.
   The application uses the `adafruit-hat` mapping, 64 rows, 128 columns,
   slowdown 5 and brightness 100; adjust `create_matrix()` in `interface_ai.py`
   to match your hardware.
2. Install the application and sensor dependencies into the same environment:

   ```sh
   .venv/bin/python -m pip install -r requirements.txt
   ```

   This installs the pinned [CircuitPython VL53LxCX driver](https://pypi.org/project/circuitpython-vl53lxcx/)
   and Adafruit Blinka. The application works around a firmware lookup bug in
   driver version 0.0.5, and initializes the sensor without toggling its optional
   LPN reset pin, which is not configured by this project. Depending
   on the Pi and gpiozero version, a supported gpiozero pin backend must also
   be installed/configured.
3. Connect and verify the two buttons and the I2C sensor. The BCM button
   pins are defined in `sensor_config.py`: NEXT 19 and OK 18. Check
   them against your actual hardware and edit that file if needed. Run:

   ```sh
   sudo .venv/bin/python main.py
   ```

   Use the explicit `.venv/bin/python` path even when the environment is
   activated: `sudo python` may select the system interpreter instead.
   The matrix driver often requires elevated privileges. Run from this
   directory with the Python environment containing all the dependencies.
   The application keeps privileges for I2C access. Check the terminal or
   service logs for sensor and audio errors. Debounced button presses and
   holds are logged at INFO level. Stop with Ctrl+C.

Install VLC's native library with `sudo apt install libvlc5 vlc-plugin-base`.
The default cue files are `audio/timestart.mp3` and `audio/lapchime.mp3`;
`--sounds-dir` selects another directory containing files with those names.
Sound is enabled by default and can be disabled in settings.
Audio errors and missing files are logged; they do not stop the timer. Configure
and test the Pi's audio output for the account running the application, including
when using sudo.

### Sensor connection troubleshooting

`Sensor initialized` means only that startup succeeded; readings must still be
received and validated. Incomplete frames and I/O errors are logged, the sensor
state is cleared, and reconnection is attempted. Every correctly formed frame,
including an all-invalid one, is used for occupancy detection. The configured
`FRAME_TIMEOUT` defaults to 5 seconds: after that long without a frame, the
workout app marks the sensor faulty and reconnects. This determines how long the
last occupancy state can remain in use when frames stop arriving. The workout
app and live diagnostic retry an I/O failure during a data-ready check twice,
with 50 ms between attempts, before reconnecting. Other sensor errors trigger
reconnection without these retries. The live diagnostic also reconnects after a
frame timeout or failed initialization. Repeated `Errno 5` errors can
have physical causes that software cannot determine: with power off, check
sensor power, ground, SDA/SCL wiring and connectors, compatible logic levels,
and appropriate I2C pull-ups for the sensor breakout. Enable I2C and verify the
device is visible before running the calibration diagnostic. Check the Pi's I2C
configuration and sensor documentation; avoid changing the bus speed blindly.
Do not treat reconnection as proof that the hardware is stable.

For detailed diagnostics, run the app with timestamped debug logging:

```sh
sudo .venv/bin/python main.py --log-level DEBUG --log-file /tmp/touchline-sensor.log
```

Logs include initialization stages, failure tracebacks and errno, data-ready and
usable-frame counts, active valid zones, raw target status counts, timeouts,
and reconnect attempts. Each frame with no valid active zones is logged
at WARNING with its full rotated 8x8 distances, validity, original target
status codes and dead-zone coordinates. Malformed frames include the available
raw arrays (capped at 256 values) and their lengths. A read failure before a
frame is returned has no frame contents to log. Calibration and the live
diagnostic log bad frames too. Logging every bad frame can grow quickly even
at INFO; DEBUG also logs every good frame. Stop
the program with Ctrl+C and share the log after checking it for private data.
`ready_frames=0` indicates no frame became ready; frames with no valid active
zones do not by themselves prove an I2C disconnect. A malformed frame or I/O exception is logged with
its operation. These observations cannot establish the root cause without
testing the Pi, wiring, sensor and power.

## Poolside calibration

Stop the workout app first: only one program should control the sensor. Edit
`sensor_config.py` on the Pi to configure `ROTATION_DEGREES` (clockwise 0, 90,
180, or 270), `DEAD_ZONES`, thresholds, debounce, timeout and ranging frequency.
Dead zones are `(row, column)` coordinates from 0 to 7, measured **after**
rotation with `(0, 0)` at the top left. They are excluded from both the
occupied count and valid count, and at least `MIN_ZONES` zones must remain.
Defaults are examples, not calibrated values.

Run the live grid to inspect orientation, valid readings and dead zones:

```sh
sudo .venv/bin/python tofmatrix.py --sensor-only
```

`X` marks a dead zone. A value marked `*`, such as `4000*`, is the assumed
distance for an invalid or non-positive reading, not a sensor measurement.
Identify permanent obstructions and other lanes, edit the dead zones, and restart the diagnostic.
Next, run the guided empty-area and swimmer-at-wall captures:

```sh
sudo .venv/bin/python calibrate_sensor.py --seconds 10 \
  --log-level DEBUG --log-file /tmp/touchline-calibration.log
```

The tool displays the first grid of each capture, frame counts, valid-zone
coverage and the median distance/valid-sample count for every zone. It compares
the `MIN_ZONES`-th closest valid active distance in every frame. It only prints
candidate entry/exit thresholds if at least five frames per condition each have
at least `MIN_ZONES` actual valid readings and the two captures are completely separated. Overlap,
timeouts and incomplete frames fail explicitly without changing the code.
Copy the printed values into `sensor_config.py`, review the other values,
and restart the app. A successful recommendation applies only to the sampled
conditions; it is not automatic calibration or proof of reliable detection.

For occupancy detection, invalid or non-positive active-zone measurements are
assumed to be `MAX_DISTANCE_MM` (default 4000 mm), which must exceed `EXIT_MM`.
This is an assumption, not a measured distance: an invalid zone may actually
contain a nearby swimmer, so this policy can incorrectly mark the area clear.
The occupied test counts zones at or below entry distance; a clear test requires
fewer than `MIN_ZONES` zones below exit distance. Even an all-invalid frame is
treated as clear and can trigger a departure after the normal debounce; it does
not trigger a reconnect. Missing frames still produce a sensor error and
reconnection attempts. The grid marks assumed distances with `*`; calibration
summaries and recommendations use actual valid readings only.

Test a stationary swimmer, brief splashes, complete departures and repeated
approaches, with no swimmer and with real pool conditions. Confirm the
displayed progress against observed events and adjust placement, thresholds and
debounce. A quiet water surface must produce enough valid *far* readings to
identify departure. Position and configure dead zones to avoid other lanes and
fixed nearby structures. There is no guaranteed operation through an enclosure.

## Custom workouts and tests

Edit `WORKOUTS` in `workout.py`. Each workout contains sets with a stroke label,
25 or 50 distance, repetition count, send-off seconds per repetition and
optional `extra_rest` seconds. Set `late_rest` to a positive number of seconds
to schedule that much rest when arrival is already past the next send-off;
the default of zero keeps the missed countdown negative. A 25 set must have an
even repetition count. Every set is followed by a confirmation before the next
one.

Run the hardware-independent tests with:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests simulate sensor data and buttons; they do not validate physical detection,
audio, GPIO pin availability, or pool safety.
