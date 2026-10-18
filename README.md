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

## Current status — Phase 1 (foundation) complete

Phase 1 established the safe repository and development foundation only. No
firmware has been installed and the ESP32 has not been connected, flashed,
erased, or modified in any way.

Implemented in this phase:

- Repository layout for device code, host tools, tests, and docs.
- A safe `.gitignore` that excludes real secrets.
- `device/credentials.example.py` with placeholders only.
- A minimal, hardware-independent application entry point (`boot.py`,
  `main.py`) that validates configuration and reports its version.
- Configuration and credential validation (`device/config.py`).
- A hardware-independent timekeeping interface (`device/clock/time_service.py`).
- A modular sensor interface and failure-isolating manager
  (`device/sensors/`).
- Import-safe placeholder modules for later phases (network, power, updates).
- Host-side tests runnable with the standard library only.

Not implemented yet: Wi-Fi, NTP, MQTT, OTA, sensors, power management, and
GPS. See the phase list in `SPECIFICATION.md`.

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
│   ├── network/            # wifi.py, mqtt_client.py (placeholders)
│   ├── sensors/            # base.py, manager.py
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

The tests exercise configuration/credential validation, the timekeeping
interface, and sensor failure isolation. None of them require hardware.

## Safety and secrets

- No real Wi-Fi, MQTT, or other secrets are committed. Only placeholders in
  `device/credentials.example.py`.
- Secrets are never printed in logs or error messages.
- No firmware flashing, erasing, or hardware changes happen without an
  explicit step and the user's approval (see `SPECIFICATION.md` sections 1
  and 13).

## Unresolved hardware questions

These remain open and must not be guessed (see `SPECIFICATION.md` section 14):

- The exact model and interface of the "380 weather chip".
- GPS receiver model and interface.
- Display hardware, battery chemistry/capacity/charging, and whether an
  external RTC is needed.
- Proxmox MQTT broker address, port, authentication, and TLS setup.

See [`docs/HARDWARE.md`](docs/HARDWARE.md) for details.
