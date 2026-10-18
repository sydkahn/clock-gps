"""Common sensor interface.

Every supported sensor is a separate module that subclasses :class:`Sensor`.
Sensor drivers must stay free of application logic: they must not publish to
MQTT, must not print readings as their primary output, and must not know
about the clock or power manager. They return data to the sensor manager,
which normalizes and timestamps it.

This module is hardware-independent and can be unit-tested on the
development computer.
"""

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"


class SensorError(Exception):
    """Raised by a sensor driver when a reading cannot be produced."""


class Sensor:
    """Base class for a sensor driver.

    Drivers override the methods relevant to their hardware. The default
    ``sleep`` and ``wake`` do nothing, which suits sensors without a
    low-power mode.

    Do not invent readings for missing or failed hardware; raise
    :class:`SensorError` (or let the underlying exception propagate) so the
    manager can report an explicit unavailable/error status instead of a
    valid-looking zero.
    """

    #: Short, stable name used in telemetry and status output.
    name = "unnamed"

    def initialize(self):
        """Configure the sensor and its hardware interface."""
        raise NotImplementedError

    def read(self):
        """Return a structured reading, or raise on failure."""
        raise NotImplementedError

    def status(self):
        """Return a status string describing availability."""
        return STATUS_OK

    def sleep(self):
        """Enter a low-power state when the hardware supports it."""
        return None

    def wake(self):
        """Leave the low-power state entered by :meth:`sleep`."""
        return None
