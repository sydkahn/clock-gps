"""Host-side serial monitor.

Placeholder for Phase 2. The serial port must be detected at runtime rather
than hard-coded (COM numbers change between connections), so this tool is
deferred until the firmware is installed and the REPL is confirmed.

Run from the project root: ``python tools/monitor.py``.
"""

import sys


def main():
    print("monitor.py is not implemented yet (Phase 2: MicroPython over USB).",
          file=sys.stderr)
    print("No hardware was contacted. See docs/INSTALLATION.md.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
