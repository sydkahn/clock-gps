"""Host-side application deployment tool.

Placeholder for Phase 5. This tool deliberately does not flash, erase, or
otherwise modify the ESP32, and it must never hard-code a COM port. The
implementation is deferred until the MicroPython build, filesystem layout,
and application OTA mechanism have been selected.

Run from the project root: ``python tools/deploy.py``.
"""

import sys


def main():
    print("deploy.py is not implemented yet (Phase 5: application OTA).",
          file=sys.stderr)
    print("No hardware was contacted. See docs/OTA.md.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
