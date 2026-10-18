"""Test helpers.

Makes the ``device/`` tree importable from host-side tests so that
hardware-independent modules can be tested on the development computer with
the standard library only.

Import this module before importing any ``device/`` module::

    import _support  # noqa: F401  (adjusts sys.path)
    import config
"""

import pathlib
import sys

DEVICE_DIR = pathlib.Path(__file__).resolve().parents[1] / "device"

if str(DEVICE_DIR) not in sys.path:
    sys.path.insert(0, str(DEVICE_DIR))
