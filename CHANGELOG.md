# Changelog

All notable changes to Clock GPS are recorded here. The project follows the
phased plan in `SPECIFICATION.md`.

## [0.5.0] - Phase 6: read-only web dashboard

### Added

- `device/connectivity/dashboard.py`: a lightweight, read-only HTTP server
  using MicroPython's built-in `socket`/`select` (imported lazily so the module
  stays host-testable). It serves a single self-contained page (`GET /`), a
  JSON status endpoint (`GET /status.json`), a rate-limited refresh request
  (`POST /api/refresh`), and an empty `204` for `GET /favicon.ico`; anything
  else is a `400`/`404`/`405`. The page shows the pressure **trend** as the
  prominent element, temperature in °F, humidity, the last reading time, and
  Wi-Fi/sensor status. Absolute pressure is excluded from both the page and the
  JSON by a field whitelist, and no credentials are exposed.
- `device/clock/time_service.py`: `format_timestamp`, a small, injectable
  helper that formats Unix-epoch seconds as a local 12-hour
  `YYYY-MM-DD hh:mm:ss AM/PM` string, applying a display-only UTC offset and
  returning `None` when no time is set.
- Configuration (`device/config.py`): `web_enabled` (default `True`),
  `web_port` (default `80`), `web_refresh_min_s` (default `10`), and
  `utc_offset_hours` (display-only local UTC offset in hours, default `-5` for
  Eastern Standard Time), with validation and backward-compatible defaults.
- Tests: `tests/test_dashboard.py` (request parsing/routing, response
  formatting, the pressure-free JSON whitelist, the reading timestamp, and the
  cooperative serving loop with fakes); `tests/test_time_service.py` extended
  for `format_timestamp` (morning, afternoon, noon, midnight, and UTC-to-local
  conversion); `tests/test_config.py` extended for the web and offset settings;
  `tests/test_main.py` extended for dashboard wiring, 12-hour timestamped
  readings, and the refresh/schedule interaction.

### Changed

- `device/main.py`: console readings are prefixed with the reading's local time
  (12-hour, with AM/PM) computed from the NTP-synchronized clock and the
  configured `utc_offset_hours`, or `TIME NOT SET` when the clock is not
  synchronized (no timestamp is invented). The reading loop now starts the
  dashboard, hands it each reading after it is taken (`update`), and services
  requests during the wait between readings (`_wait`). A refresh request is
  queued to the loop, which takes the reading through the normal path and
  restarts the interval; the dashboard never reads a sensor or creates a second
  reading loop. If the dashboard is disabled or cannot start, `_wait` falls
  back to the previous plain sleep, preserving existing behavior.
- `device/version.py` bumped to `0.5.0`.

### Notes

- `/status.json` reports the current server time and the last reading's time as
  separate fields, so server time is never presented as reading time. Both the
  console and `last_reading_local` use the same 12-hour local formatting.
- Only the *displayed* time is shifted by `utc_offset_hours`; stored and
  published timestamps remain Unix-epoch seconds in UTC. The offset is a fixed
  number and does not follow daylight saving.
- The dashboard is a LAN-local presentation interface bound to `0.0.0.0` on
  port `80`; it must not be exposed to the public internet. MQTT remains the
  only home-automation interface (`SPECIFICATION.md` §8.1), which has no
  dashboard section; this feature is a presentation addition, not a
  home-automation interface, and `SPECIFICATION.md` is unchanged.
- `select.poll()`, socket timeouts, one request per connection, and a bounded
  request read keep the server from blocking the reading schedule.
- No firmware was flashed, nothing was deployed to the ESP32, and the physical
  device was not modified by this project.

## [0.4.0] - Phase 6: application integration

### Added

- `device/main.py` now runs the application instead of stopping at a startup
  banner. It loads and validates configuration and credentials, connects
  Wi-Fi through `connectivity.wifi`, synchronizes time through
  `clock.time_service`, initializes the BME280 (SDA GPIO 16, SCL GPIO 17,
  address `0x76`) through the sensor manager, and then reads and reports the
  weather on a configurable interval (`telemetry_interval_s`).
- Each reading cycle prints temperature in °F, relative humidity, station
  pressure and estimated sea-level pressure in inHg (clearly marked an
  estimate), and the pressure-trend status. Failures are reported explicitly;
  a failed sensor, Wi-Fi connection, or NTP sync does not stop the loop, and
  retries are rate-limited (Wi-Fi/NTP backoff, NTP resync at `ntp_interval_s`).
  Ctrl-C stops the loop cleanly, and the existing pressure-history
  persistence is preserved.
- `tests/test_main.py`: mocked integration tests covering startup wiring,
  periodic reads, sensor/Wi-Fi/NTP failure isolation, retry pacing, trend
  computation across the window, Ctrl-C shutdown, and that the Wi-Fi SSID and
  password are never printed.

### Changed

- Renamed the `device/network/` package to `device/connectivity/` and updated
  imports, tests, and documentation. On the ESP32 the MicroPython built-in
  `network` module is non-extensible, so it always shadows a filesystem
  package of the same name; `import network.wifi` therefore failed on the
  device even though it worked in host tests. `WifiManager` still imports the
  built-in `network` module (lazily) for the radio itself, so Wi-Fi behavior is
  unchanged. This layout adjustment is permitted by `SPECIFICATION.md` §4.2.
- `device/version.py` bumped to `0.4.0`.

### Notes

- MQTT, a display, GPS, and power management remain unimplemented and are not
  wired in.
- `SPECIFICATION.md` is unchanged; the `network/` → `connectivity/` layout
  adjustment is permitted by §4.2.
- No firmware was flashed and the ESP32 was not modified by this project.

## [0.3.0] - Phase 6 (partial): BME280 weather sensor

### Added

- `device/sensors/bme280.py`: BME280 temperature/pressure/humidity driver over
  I2C (SDA GPIO 16, SCL GPIO 17, address `0x76` with `0x77` accepted as an
  alternative). Verifies the chip-id register (`0x60`) before use, loads the
  calibration blocks, and uses the Bosch integer compensation routines. The
  MicroPython `machine` module is imported lazily so the module stays
  host-testable, and an I2C bus can be injected for tests.
- `device/sensors/weather.py`: `WeatherSensor` (a `Sensor`) plus pure,
  testable helpers and small classes:
  - Celsius→Fahrenheit, hPa/inHg, and Pascal→inHg conversions;
  - sea-level pressure estimation from station pressure, station temperature,
    and configured elevation (returned with `sea_level_estimated: True`);
  - `TrendTracker` for the ~3-hour station-pressure trend
    (`rising` / `falling` / `steady` / `waiting_for_history`), which discards
    corrupt, out-of-range, duplicate, non-monotonic, stale, and future
    samples and never invents a trend or substitutes zero for missing data;
  - `PressureHistoryStore`, a versioned JSON history persisted across
    restarts with rate-limited writes to spare the flash.
- Configuration (`device/config.py`): `elevation_ft` (default `627` feet),
  `pressure_trend_window_s` (default `10800` seconds), and
  `pressure_trend_threshold_hpa` (default `1.0` hPa), with validation and
  backward-compatible defaults.
- Tests (standard library only): `tests/test_bme280.py` (calibration parsing,
  compensation, and I2C error handling with a fake bus) and
  `tests/test_weather.py` (conversions, sea-level estimation, trend cases,
  history persistence/corruption/restart recovery, clock handling, malformed
  readings, and `SensorManager` compatibility). `tests/test_config.py`
  extended for the new settings.

### Changed

- `device/version.py` bumped to `0.3.0`.
- `docs/HARDWARE.md` and `README.md` identify the weather sensor as a BME280
  and document units and the unvalidated sea-level estimate.

### Notes

- `SPECIFICATION.md` is unchanged; the former "380 weather chip" question is
  resolved as a BME280 without editing the specification.
- Station pressure and estimated sea-level pressure are reported under
  separate keys and are never substituted for one another.
- The estimated sea-level pressure has **not** been validated against an
  independent weather observation.
- The sensor is not yet wired into `main.py`.
- No firmware was flashed and the ESP32 was not modified by this project.

## [0.2.0] - Phase 3: Wi-Fi and NTP modules

### Added

- `device/clock/time_service.py`: explicit MicroPython (2000) to Unix (1970)
  epoch conversion (`micropython_to_unix`, `unix_to_micropython`) with a
  plausibility guard, plus an NTP synchronization interface
  (`TimeService.sync_ntp`). Tracks validity, source, last successful sync,
  and a secret-free last-attempt status. Hardware imports are lazy so the
  module stays host-testable.
- `device/network/wifi.py` (renamed to `device/connectivity/wifi.py` in
  [0.4.0]): `WifiManager` connects the station interface
  using credentials from `config.py`, handles timeouts and exceptions
  without crashing, never prints or stores passwords in status, and imports
  the MicroPython `network` module lazily.
- Tests (standard library only): `tests/test_time_service.py` extended with
  epoch-conversion and NTP success/failure cases; new `tests/test_wifi.py`
  covering successful connection, timeout, exception handling, and
  password-free status using fakes.
- Documentation: README configuration and timekeeping sections;
  `docs/INSTALLATION.md` testing and epoch notes; `docs/HARDWARE.md`
  confirmed firmware/epoch.

### Changed

- `device/version.py` bumped to `0.2.0`.

### Notes

- The Wi-Fi and NTP modules are ready but not yet wired into `main.py`.
- MQTT, GPS, OTA, sensors, and power management remain unimplemented.
- No firmware was flashed and the ESP32 was not modified by this project.

## [0.1.0] - Phase 1: repository and safe foundation

### Added

- Repository layout for device code, host tools, tests, and documentation.
- `.gitignore` that excludes real credentials while allowing
  `credentials.example.py`.
- `device/credentials.example.py` with placeholders only.
- Minimal application entry point: `device/boot.py`, `device/main.py`,
  `device/version.py`.
- `device/config.py` with configuration and credential validation that never
  exposes secret values.
- `device/clock/time_service.py`, a hardware-independent timekeeping
  interface ready for NTP and GPS sources.
- `device/sensors/base.py` (common sensor interface) and
  `device/sensors/manager.py` (failure-isolating sensor manager).
- Import-safe placeholder modules for Phase 2–7 areas: network, power, and
  updates.
- Host-side placeholder tools `tools/deploy.py` and `tools/monitor.py`.
- Host-side tests (standard library only) for configuration validation,
  timekeeping, sensor failure isolation, and Git credential exclusion.
- Documentation: `README.md` and `docs/` (HARDWARE, INSTALLATION, OTA,
  POWER, MQTT).

### Notes

- No firmware was installed and the ESP32 was not connected, flashed, or
  modified.
- No sensor model was assumed; the weather sensor remains an open question.
