"""Tests for device/clock/time_service.py time validity and source tracking."""

import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
from clock.time_service import TimeService


class TimeServiceTests(unittest.TestCase):
    def test_starts_invalid(self):
        service = TimeService()
        self.assertFalse(service.is_valid())
        self.assertIsNone(service.now())
        self.assertIsNone(service.source)

    def test_set_time_makes_time_valid(self):
        service = TimeService()
        service.set_time(1_700_000_000, "ntp")
        self.assertTrue(service.is_valid())
        self.assertEqual(1_700_000_000, service.now())
        self.assertEqual("ntp", service.source)

    def test_mark_invalid_clears_time(self):
        service = TimeService()
        service.set_time(1_700_000_000, "ntp")
        service.mark_invalid()
        self.assertFalse(service.is_valid())
        self.assertIsNone(service.now())
        self.assertIsNone(service.source)

    def test_none_timestamp_is_rejected(self):
        service = TimeService()
        with self.assertRaises(ValueError):
            service.set_time(None, "ntp")
        self.assertFalse(service.is_valid())

    def test_source_can_change_without_rewrite(self):
        # A later GPS source may take over; the interface does not change.
        service = TimeService()
        service.set_time(1_700_000_000, "ntp")
        service.set_time(1_700_000_005, "gps")
        self.assertEqual("gps", service.source)
        self.assertEqual(1_700_000_005, service.now())


if __name__ == "__main__":
    unittest.main()
