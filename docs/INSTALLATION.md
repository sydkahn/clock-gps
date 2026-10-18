# Installation and development environment

This document covers the development computer. Installing MicroPython on the
board is Phase 2 and is intentionally not done yet.

## Development computer (Windows 11)

Required tools:

| Tool | Version used | Notes |
| --- | --- | --- |
| Python | 3.12 | Tests use the standard library only; no `pip install` needed. |
| Git | 2.54 (any recent) | Version control. |
| PowerShell | bundled | Terminal used for the commands below. |

Not yet required (Phase 2+): MicroPython firmware, `esptool`, `mpremote`.
The correct firmware build and flash layout must be confirmed before any
flashing.

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

The tests require no hardware. They cover configuration and credential
validation, the timekeeping interface, sensor failure isolation, and that
real credentials stay ignored by Git.

## Serial port detection

COM port numbers change between connections. Any host tool must enumerate
available ports and detect the board rather than hard-coding `COM6`.

## Board recovery (Phase 2)

Recovery instructions for re-installing MicroPython over USB will be written
in Phase 2, once the firmware build and partition layout are confirmed. Until
then, no flashing or erasing is performed.
