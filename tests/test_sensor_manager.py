"""Tests for the modular sensor framework and failure isolation.

Uses fake sensors so no hardware is required.
"""

import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
from clock.time_service import TimeService
from sensors.base import STATUS_ERROR, STATUS_OK, Sensor, SensorError
from sensors.manager import SensorManager


class FakeSensor(Sensor):
    def __init__(self, name, value=21.5, fail_read=False, fail_init=False):
        self.name = name
        self._value = value
        self._fail_read = fail_read
        self._fail_init = fail_init

    def initialize(self):
        if self._fail_init:
            raise SensorError("not present")

    def read(self):
        if self._fail_read:
            raise SensorError("read failed")
        return self._value

    def status(self):
        return STATUS_OK


class SensorManagerTests(unittest.TestCase):
    def test_reading_a_working_sensor(self):
        manager = SensorManager()
        manager.register(FakeSensor("temperature", 21.5))
        records = manager.read_all()
        self.assertEqual(1, len(records))
        self.assertEqual(STATUS_OK, records[0]["status"])
        self.assertEqual(21.5, records[0]["value"])
        self.assertIsNone(records[0]["timestamp"])

    def test_one_failed_sensor_does_not_stop_others(self):
        manager = SensorManager()
        manager.register(FakeSensor("temperature", 21.5))
        manager.register(FakeSensor("pressure", fail_read=True))
        manager.register(FakeSensor("humidity", 40.0))
        records = {r["sensor"]: r for r in manager.read_all()}

        self.assertEqual(STATUS_OK, records["temperature"]["status"])
        self.assertEqual(STATUS_OK, records["humidity"]["status"])
        self.assertEqual(STATUS_ERROR, records["pressure"]["status"])

    def test_failed_sensor_reports_none_not_zero(self):
        manager = SensorManager()
        manager.register(FakeSensor("pressure", fail_read=True))
        record = manager.read_all()[0]
        self.assertIsNone(record["value"])
        self.assertIn("error", record)

    def test_initialize_failure_is_isolated(self):
        manager = SensorManager()
        manager.register(FakeSensor("temperature", 21.5))
        manager.register(FakeSensor("pressure", fail_init=True))
        results = manager.initialize_all()
        self.assertEqual(STATUS_OK, results["temperature"])
        self.assertTrue(results["pressure"].startswith(STATUS_ERROR))

    def test_duplicate_sensor_name_is_rejected(self):
        manager = SensorManager()
        manager.register(FakeSensor("temperature"))
        with self.assertRaises(ValueError):
            manager.register(FakeSensor("temperature"))

    def test_timestamp_attached_when_time_is_valid(self):
        time_service = TimeService()
        time_service.set_time(1_700_000_000, "ntp")
        manager = SensorManager(time_service=time_service)
        manager.register(FakeSensor("temperature", 21.5))
        self.assertEqual(1_700_000_000, manager.read_all()[0]["timestamp"])

    def test_no_timestamp_when_time_invalid(self):
        manager = SensorManager(time_service=TimeService())
        manager.register(FakeSensor("temperature", 21.5))
        self.assertIsNone(manager.read_all()[0]["timestamp"])


if __name__ == "__main__":
    unittest.main()
