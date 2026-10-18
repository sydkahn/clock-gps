# Installation and development environment

This document covers the development computer. MicroPython v1.29.0 is
already installed on the board (done by the owner); this project does not
flash or modify hardware.

## Development computer (Windows 11)

Required tools:

| Tool | Version used | Notes |
| --- | --- | --- |
| Python | 3.12 | Tests use the standard library only; no `pip install` needed. |
| Git | 2.54 (any recent) | Version control. |
| PowerShell | bundled | Terminal used for the commands below. |

Not required by the tests: MicroPython firmware, `esptool`, `mpremote`. The
board already runs MicroPython v1.29.0. Any future flashing must still be an
explicit, approved step.

## First-time setup

```powershell
git clone https://github.com/sydkahn/clock-gps.git
cd clock-gps
Copy-Item device\credentials.example.py device\credentials.py
# Edit device\credentials.py with real values; it is git-ignored.
```

## Running the tests

From the project root:

```powershell
python -m unittest discover -s tests -v
```

To run a single file:

```powershell
python -m unittest tests.test_config -v
```

The tests require no hardware or network access. They cover configuration
and credential validation, MicroPython→Unix epoch conversion, NTP sync
success and failure, Wi-Fi connection and timeout handling (with fakes), and
that real credentials stay ignored by Git.

## MicroPython epoch

This board's MicroPython build uses 2000-01-01 as its epoch
(`time.gmtime(0)` returns `(2000, 1, 1, 0, 0, 0, 5, 1)`). `time.time()`
returns seconds since 2000. Always convert to Unix epoch seconds before
storing or publishing a timestamp; see `device/clock/time_service.py`
(`micropython_to_unix` / `unix_to_micropython`).

## Serial port detection

COM port numbers change between connections. Any host tool must enumerate
available ports and detect the board rather than hard-coding `COM6`.

## Board recovery (Phase 2)

MicroPython v1.29.0 is installed on the board. Recovery over USB
(re-installing MicroPython) is still an explicit, approved step; the exact
firmware build and partition layout should be recorded before repeating an
install. No flashing or erasing is done as part of normal development.
