# Clock GPS

A modular, low-power ESP32 clock and sensor platform written in MicroPython.
It starts as a clock using network time (NTP) and a weather sensor, and is
designed to grow toward GPS time, additional sensor modules, MQTT commands,
and future home-automation integrations.

The authoritative project specification is [`SPECIFICATION.md`](SPECIFICATION.md).
Where this README and the specification disagree, the specification wins.

- **Owner / repository:** `sydkahn/clock-gps`
- **Target board:** Original ESP32 (`ESP32-D0WDQ6`, revision 1.0, 4 MB flash)
- **Language:** MicroPython
- **Development computer:** Windows (host tools use Python 3)

## Current status

- **Phase 1 (foundation)** — complete.
- **Phase 2 (MicroPython over USB)** — MicroPython v1.29.0 was installed on
  the board by the owner (outside this repository). This project does not
  flash or modify hardware.
- **Phase 3 (Wi-Fi and NTP)** — core modules implemented and unit-tested on
  the host: Wi-Fi connection and NTP time synchronization.
- **Phase 6 (weather sensor and integration)** — the BME280 temperature,
  pressure, and humidity module is implemented and unit-tested on the host,
  and is now wired into `main.py`: the device loads configuration, connects
  Wi-Fi, synchronizes time, and reads and reports the weather on a configurable
  interval. A read-only web dashboard presents the pressure trend and current
  readings on the local network. The estimated sea-level pressure has still not
  been validated against an independent weather observation.

Implemented so far:

- Repository layout for device code, host tools, tests, and docs.
- A safe `.gitignore` that excludes real secrets.
- `device/credentials.example.py` with placeholders only.
- An application entry point (`boot.py`, `main.py`) that loads and validates
  configuration, connects Wi-Fi, synchronizes time, and reads and reports the
  weather sensor on a configurable interval, isolating and reporting failures.
- Configuration and credential validation (`device/config.py`).
- Timekeeping service with explicit MicroPython→Unix epoch conversion and an
  NTP synchronization interface (`device/clock/time_service.py`).
- Wi-Fi connection module that reads credentials from the configuration
  system and never exposes passwords (`device/connectivity/wifi.py`).
- A BME280 weather-sensor module (`device/sensors/bme280.py` driver and
  `device/sensors/weather.py`) reporting temperature in °F, relative humidity,
  station pressure in hPa and inHg, an estimated sea-level pressure, and a
  ~3-hour pressure trend, with small pressure-history persistence.
- A read-only local web dashboard (`device/connectivity/dashboard.py`) that
  shows the pressure trend, temperature in °F, humidity, the last reading
  time, and Wi-Fi/sensor status, with a JSON status endpoint and a rate-limited
  "refresh now" request. It serves requests from the main loop, never reads a
  sensor itself, and shows no absolute pressure and no credentials.
- A modular sensor interface and failure-isolating manager
  (`device/sensors/`).
- Import-safe placeholder modules for later phases (power, updates, MQTT).
- Host-side tests runnable with the standard library only.

Not implemented yet: MQTT (Phase 4), application OTA (Phase 5), a display,
power management (Phase 7), and GPS (Phase 8). See the phase list in
`SPECIFICATION.md`.

## Repository layout

```text
clock-gps/
├── README.md
├── SPECIFICATION.md
├── CHANGELOG.md
├── .gitignore
├── device/                 # MicroPython code that runs on the ESP32
│   ├── boot.py
│   ├── main.py
│   ├── config.py
│   ├── version.py
│   ├── credentials.example.py
│   ├── clock/time_service.py
│   ├── connectivity/       # wifi.py, dashboard.py; mqtt_client.py (placeholder)
│   ├── sensors/            # base.py, manager.py, bme280.py, weather.py
│   ├── power/              # power_manager.py (placeholder)
│   └── updates/            # ota.py (placeholder)
├── tools/                  # host-side tools (placeholders)
│   ├── deploy.py
│   └── monitor.py
├── tests/                  # host-side tests (standard library only)
└── docs/                   # HARDWARE, INSTALLATION, OTA, POWER, MQTT
```

Device code and host tooling are deliberately separate. Only files under
`device/` are destined for the ESP32.

## Development setup (Windows 11)

Required tools:

- **Python 3** (developed and tested with 3.12). Standard library only for
  tests — no third-party packages are required.
- **Git**.
- A terminal (PowerShell is fine).

MicroPython firmware, `esptool`, and `mpremote` are **not** installed or used
yet. They are intentionally deferred to Phase 2, and the correct MicroPython
build and flash layout must be confirmed before any flashing. Do not flash or
erase the board.

### Configure credentials

The device reads secrets from `device/credentials.py`, which is excluded from
Git. Create it from the example and fill in real values:

```powershell
Copy-Item device\credentials.example.py device\credentials.py
```

Never commit `device/credentials.py`. The `tests/test_gitignore.py` test
verifies that it stays ignored.

### Run the tests

From the project root:

```powershell
python -m unittest discover -s tests -v
```

No hardware or network access is required. The tests use the standard library
only and cover:

- configuration and credential validation (`tests/test_config.py`);
- MicroPython→Unix epoch conversion and NTP sync success/failure
  (`tests/test_time_service.py`);
- Wi-Fi connection, timeouts, and that passwords never appear in status
  (`tests/test_wifi.py`);
- BME280 calibration parsing, compensation, and I2C error handling
  (`tests/test_bme280.py`);
- weather conversions, sea-level estimation, pressure-trend detection,
  history persistence and corruption, error handling, and `SensorManager`
  compatibility (`tests/test_weather.py`);
- the `main.py` startup and reading loop, failure isolation, retry pacing,
  trend reporting, dashboard wiring, timestamped readings, and Ctrl-C
  shutdown (`tests/test_main.py`);
- the read-only web dashboard: request parsing/routing, response formatting,
  the pressure-free JSON whitelist, the reading timestamp, and the cooperative
  serving loop (`tests/test_dashboard.py`);
- sensor failure isolation (`tests/test_sensor_manager.py`);
- that real credentials stay ignored by Git (`tests/test_gitignore.py`).

## Configuration

Non-secret settings live in `device/config.py` (`Config`): `device_id`,
`ntp_host`, `ntp_interval_s`, `ntp_timeout_s`, `telemetry_interval_s`, and the
weather settings `elevation_ft` (ground elevation above sea level, default
`627` feet), `pressure_trend_window_s` (trend window, default `10800` seconds,
about three hours), and `pressure_trend_threshold_hpa` (trend threshold,
default `1.0` hPa), plus the dashboard settings `web_enabled` (default
`True`), `web_port` (default `80`), and `web_refresh_min_s` (minimum seconds
between accepted manual refreshes, default `10`), and `utc_offset_hours` (the
display-only local UTC offset in hours, default `-5` for Eastern Standard
Time). Secrets (Wi-Fi and, later,
MQTT) come from the git-ignored
`device/credentials.py`, loaded through `config.load()`. `config.load()`
raises `ConfigurationError` with a secret-free message when credentials are
missing or invalid.

### Timekeeping and the MicroPython epoch

This ESP32 MicroPython build uses **2000-01-01** as its epoch, confirmed on
hardware with `time.gmtime(0) == (2000, 1, 1, 0, 0, 0, 5, 1)`. Its
`time.time()` therefore returns seconds since 2000, not since 1970.

All timestamps published by the application are Unix-epoch seconds (UTC).
`device/clock/time_service.py` performs the conversion explicitly
(`micropython_to_unix`, `unix_to_micropython`) and rejects an NTP "success"
that does not produce a plausible time, so a MicroPython timestamp is never
mistaken for a Unix timestamp. The conversion is covered by host tests.

```python
from clock.time_service import TimeService

time_service = TimeService()
if not time_service.sync_ntp(host="pool.ntp.org", timeout_s=10):
    print("NTP failed:", time_service.status()["last_error"])
else:
    print("UTC epoch:", time_service.now())
```

### Weather sensor, units, and the sea-level estimate

The BME280 module reports a single reading dict with documented units:

- `temperature_f` (for display) and `temperature_c`;
- `humidity_pct` (relative humidity, percent);
- `pressure_station_hpa` and `pressure_station_inhg` — the **actual** pressure
  measured at the device;
- `pressure_sea_level_hpa` and `pressure_sea_level_inhg` — an **estimate**;
- `pressure_trend` — `rising`, `falling`, `steady`, or
  `waiting_for_history`, plus `pressure_trend_delta_hpa`.

Station pressure and sea-level pressure are always reported separately and are
never substituted for one another.

> **The sea-level value is an unvalidated estimate.** It is derived from the
> station pressure, the station temperature, and the configured elevation
> using the standard barometric reduction. It has **not** been checked against
> an independent weather observation, so treat it as approximate until that
> comparison is done.

The trend compares station pressure over approximately three hours (rounded to
the sample nearest the window, within a small tolerance). A rise of at least
`pressure_trend_threshold_hpa` (default 1.0 hPa) is `rising`, a fall of at
least that much is `falling`, and anything smaller is `steady`. When there is
not enough valid history — or valid time is unavailable — the trend is
`waiting_for_history`; a trend is never invented and missing data is never
replaced with zero. A small pressure history is persisted across restarts in a
versioned JSON file, with writes rate-limited to spare the flash.

### Startup and reading loop

`device/main.py` wires the modules together. On startup it loads and validates
configuration and credentials, connects Wi-Fi, synchronizes time over NTP,
initializes the BME280 (SDA GPIO 16, SCL GPIO 17, address `0x76`), and then
prints one weather line per `telemetry_interval_s` (default `300` seconds).
Each line is prefixed with the reading's local time (12-hour, with AM/PM)
computed from the NTP-synchronized UTC clock and the configured
`utc_offset_hours`; if the clock is not synchronized the prefix is `TIME NOT
SET` rather than a guessed time. For example:

```text
[clock-gps] 2026-10-18 02:03:12 PM | temp 68.0 F | humidity 50.0 % | station 29.235 inHg | sea-level 29.892 inHg (estimated) | trend waiting_for_history
```

Stored and published timestamps remain Unix-epoch seconds in UTC; only the
displayed time is shifted by `utc_offset_hours`. The offset is fixed, so it
does not follow daylight saving and must be changed by hand when the local DST
rule changes.

A failed sensor read, an unavailable Wi-Fi network, or a failed NTP sync is
reported and retried later rather than stopping the loop, and neither Wi-Fi
reconnection nor NTP synchronization runs as a busy loop (Wi-Fi retries and
NTP failures back off; a successful NTP sync is not repeated before
`ntp_interval_s`). Pressing Ctrl-C in Thonny stops the loop cleanly.

### Web dashboard

When `web_enabled` is true the device also serves a small read-only dashboard
from the same loop (default port `80`, so it opens by browsing the device's IP
address). It shows the pressure **trend** (`rising`, `falling`, `steady`, or
`waiting_for_history`) as the prominent element, plus temperature in °F,
humidity, the time of the last reading, and Wi-Fi and sensor status. Absolute
pressure is deliberately not shown on the page.

Routes:

- `GET /` — the HTML page;
- `GET /status.json` — machine-readable status (current server time and the
  last reading's time are separate fields and are never confused; the reading
  time is formatted in the same local 12-hour style as the console);
- `POST /api/refresh` — queues one immediate reading (rate-limited by
  `web_refresh_min_s`); other methods and paths are rejected;
- `GET /favicon.ico` — empty `204`.

The dashboard is a presentation interface only. It is handed each reading after
the sensor loop takes it, never reads a sensor itself, and never triggers a
second reading path: a refresh request is queued back to the main loop, which
takes the reading and restarts the interval from it. Requests are served during
the wait between scheduled readings, so the five-minute schedule is preserved.
If the dashboard is disabled, or cannot bind its port, the loop falls back to a
plain sleep and behaves exactly as before. MQTT remains the only
home-automation interface; the dashboard is LAN-local, is bound to `0.0.0.0`,
and must not be exposed to the public internet.

## Safety and secrets

- No real Wi-Fi, MQTT, or other secrets are committed. Only placeholders in
  `device/credentials.example.py`.
- Secrets are never printed in logs or error messages.
- No firmware flashing, erasing, or hardware changes happen without an
  explicit step and the user's approval (see `SPECIFICATION.md` sections 1
  and 13).

## Unresolved hardware questions

These remain open and must not be guessed (see `SPECIFICATION.md` section 14):

- GPS receiver model and interface.
- Display hardware, battery chemistry/capacity/charging, and whether an
  external RTC is needed.
- Proxmox MQTT broker address, port, authentication, and TLS setup.

The weather sensor is no longer open: it is a **Bosch BME280** over I2C (see
[`docs/HARDWARE.md`](docs/HARDWARE.md)), which resolves the specification's
"380 weather chip" question without changing `SPECIFICATION.md`.
