# Touchline swim trainer

Touchline connects a VL53L8CX 8x8 time-of-flight sensor, a 128x64 HUB75 RGB
matrix with an Adafruit RGB Matrix Bonnet, and three buttons to a Raspberry Pi.
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
  planned time. When sound is enabled, the start MP3 plays at each scheduled
  send-off, including the assumed far-end departure. The wall MP3 plays on a
  debounced arrival and when wall presence is initially established, including
  after a sensor reconnection.
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

Wire three normally-open momentary switches between their selected GPIO inputs
and ground. Inputs use pull-ups and are active low. Never connect a button
input to 5 V. Choose **three distinct free BCM GPIO numbers** after checking the
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
| PREV / NEXT | Navigate home, settings or workouts; open the workout menu during a workout |
| OK | Confirm selection, edit a setting, start a workout, or advance after a set |
| Hold OK for 1.5 seconds | Enter standby, abandoning the current workout |
| OK in standby | Wake to the home screen |

The start screen offers `WORKOUT` and `SETTINGS`. Choose a workout with the
arrows and OK, or choose `BACK` to return home. In settings, use the arrows to
choose an item and OK to edit it; arrows change the value and OK finishes
editing. Select `BACK` to return home. Brightness, sound, entry and exit
distances, minimum occupied zones, and both debounce times are saved immediately.
Values that violate sensor constraints are rejected, and save errors appear on
screen and in the log. Settings are stored in `/var/lib/touchline/settings.json`
by default; use `--settings-file` to choose another writable path. Saved settings
override corresponding sensor command-line defaults. Deleting that file resets
settings on the next launch. Entry and exit distances must satisfy
`0 < entry < exit <= 4000` mm; debounce values range from 0.1 to 5 seconds.
The minimum occupied zones cannot exceed `--min-valid` (default 8).

`EXTRA REST` moves the due time to the later of now or the existing send-off,
then adds the current set's configured extra-rest duration. It works while
waiting for departure, not while swimming. To mark a set complete, open the
menu, select `COMPLETE SET`, then confirm with OK. Press either arrow to cancel
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
3. Connect and verify the three buttons and the I2C sensor. Run with the BCM
   numbers you verified (replace the placeholders):

   ```sh
   sudo .venv/bin/python main.py --prev-pin PREV_BCM --next-pin NEXT_BCM --ok-pin OK_BCM
   ```

   Use the explicit `.venv/bin/python` path even when the environment is
   activated: `sudo python` may select the system interpreter instead.
   The matrix driver often requires elevated privileges. Run from this
   directory with the Python environment containing all the dependencies.
   The application keeps privileges for I2C access. Check the terminal or
   service logs for sensor and audio errors. Stop with Ctrl+C.

Install VLC's native library with `sudo apt install libvlc5 vlc-plugin-base`
and place your own MP3 files at `sounds/start.mp3` and `sounds/wall.mp3` in
the application directory. These files are not included. `--sounds-dir` selects
another directory. Sound is enabled by default and can be disabled in settings.
Audio errors and missing files are logged; they do not stop the timer. Configure
and test the Pi's audio output for the account running the application, including
when using sudo.

### Sensor connection troubleshooting

`Sensor initialized` means only that startup succeeded; readings must still be
received and validated. Incomplete frames and I/O errors are logged, the sensor
state is cleared, and reconnection is attempted. Repeated `Errno 5` errors can
have physical causes that software cannot determine: with power off, check
sensor power, ground, SDA/SCL wiring and connectors, compatible logic levels,
and appropriate I2C pull-ups for the sensor breakout. Enable I2C and verify the
device is visible before running the calibration diagnostic. Check the Pi's I2C
configuration and sensor documentation; avoid changing the bus speed blindly.
Do not treat reconnection as proof that the hardware is stable.

## Poolside calibration

Use the existing diagnostic, for example
`sudo .venv/bin/python tofmatrix.py --sensor-only`, to inspect the 8x8 valid
distance readings in millimeters for the empty approach area and for a swimmer
at the wall. A dash indicates an invalid or non-positive reading.
The diagnostic is a separate tool and does not run the workout.

Choose entry and exit distances that separate those readings with a hysteresis
gap (`--enter-mm` must be less than `--exit-mm`). The defaults, 1000 and
1200 mm, are **examples**, not universal water-level thresholds. Configure
`--min-zones`, `--min-valid`, `--enter-debounce`, `--exit-debounce`,
`--sensor-timeout`, and `--hz` as needed; see `python main.py --help`.
The occupied test counts valid zones at or below entry distance. A clear test
requires fewer than `min-zones` valid readings below exit distance. Frames with
fewer than `min-valid` valid readings cannot trigger transitions; prolonged
invalid or missing data produces a sensor error and reconnection attempts.
Invalid frames interrupt an in-progress debounce.

Test a stationary swimmer, brief splashes, complete departures and repeated
approaches, with no swimmer and with real pool conditions. Confirm the
displayed progress against observed events and adjust placement, thresholds and
debounce. A quiet water surface must produce enough valid *far* readings to
identify departure. All 64 zones are used; positioning must avoid other lanes
and fixed nearby structures. There is no automatic calibration or guaranteed
operation through an enclosure.

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
