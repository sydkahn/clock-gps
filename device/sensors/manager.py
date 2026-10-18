"""Sensor manager.

Initializes and tracks installed sensors, reads them on demand, and isolates
failures so that one broken or absent sensor cannot stop the others. It
normalizes results into records that carry an explicit status and, when a
time source is supplied, a UTC timestamp.

The manager must not publish to MQTT itself; it returns collected data to
the communications layer.

This module is hardware-independent and can be unit-tested on the
development computer with fake sensors.
"""

from sensors.base import STATUS_ERROR, STATUS_OK


class SensorManager:
    """Tracks registered sensors and returns normalized readings."""

    def __init__(self, time_service=None):
        self._sensors = []
        self._time = time_service

    def register(self, sensor):
        """Add a sensor. Raises ValueError on a duplicate name."""
        for existing in self._sensors:
            if existing.name == sensor.name:
                raise ValueError("duplicate sensor name: %s" % sensor.name)
        self._sensors.append(sensor)

    @property
    def sensors(self):
        """Return the registered sensors."""
        return list(self._sensors)

    def initialize_all(self):
        """Initialize every sensor and return a name -> status mapping.

        A failing sensor records its error text and does not prevent the
        remaining sensors from initializing.
        """
        results = {}
        for sensor in self._sensors:
            try:
                sensor.initialize()
            except Exception as exc:  # noqa: BLE001 - isolate driver failures
                results[sensor.name] = "%s: %s" % (STATUS_ERROR, exc)
            else:
                results[sensor.name] = STATUS_OK
        return results

    def read_all(self):
        """Read every sensor and return a list of normalized records.

        Each record is a dict with keys ``sensor``, ``status``, ``value``
        and ``timestamp``. Failed sensors report ``status == "error"`` with
        an ``error`` string and ``value`` left as ``None`` rather than a
        misleading zero.
        """
        return [self._read_one(sensor) for sensor in self._sensors]

    def _read_one(self, sensor):
        record = {
            "sensor": sensor.name,
            "status": STATUS_OK,
            "value": None,
            "timestamp": self._timestamp(),
        }
        try:
            record["value"] = sensor.read()
        except Exception as exc:  # noqa: BLE001 - isolate driver failures
            record["status"] = STATUS_ERROR
            record["error"] = str(exc)
        return record

    def _timestamp(self):
        if self._time is not None and self._time.is_valid():
            return self._time.now()
        return None
