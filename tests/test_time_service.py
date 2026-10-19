"""Tests for device/clock/time_service.py.

Covers the MicroPython 2000-epoch conversion, NTP synchronization success and
failure handling, and time/source tracking. No hardware is required.
"""

import calendar
import datetime
import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
from clock.time_service import (
    MIN_PLAUSIBLE_UNIX_S,
    SOURCE_NTP,
    UNIX_EPOCH_OFFSET_S,
    TimeService,
    format_timestamp,
    is_plausible,
    micropython_to_unix,
    unix_to_micropython,
)

SYNCED_UNIX = 1_700_000_000  # 2023-11-14T22:13:20Z
SYNCED_MP = SYNCED_UNIX - UNIX_EPOCH_OFFSET_S


class TimeServiceTests(unittest.TestCase):
    def test_starts_invalid(self):
        service = TimeService()
        self.assertFalse(service.is_valid())
        self.assertFalse(service.synced)
        self.assertIsNone(service.now())
        self.assertIsNone(service.source)
        self.assertIsNone(service.last_sync_epoch)
        self.assertEqual(0, service.sync_count)

    def test_set_time_makes_time_valid(self):
        service = TimeService()
        service.set_time(SYNCED_UNIX, "ntp")
        self.assertTrue(service.is_valid())
        self.assertEqual(SYNCED_UNIX, service.now())
        self.assertEqual("ntp", service.source)

    def test_mark_invalid_clears_time(self):
        service = TimeService()
        service.set_time(SYNCED_UNIX, "ntp")
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
        service.set_time(SYNCED_UNIX, "ntp")
        service.set_time(SYNCED_UNIX + 5, "gps")
        self.assertEqual("gps", service.source)
        self.assertEqual(SYNCED_UNIX + 5, service.now())


class EpochConversionTests(unittest.TestCase):
    def test_offset_matches_calendar(self):
        expected = int(
            (datetime.datetime(2000, 1, 1) - datetime.datetime(1970, 1, 1))
            .total_seconds()
        )
        self.assertEqual(expected, UNIX_EPOCH_OFFSET_S)

    def test_micropython_epoch_zero_maps_to_2000(self):
        self.assertEqual(UNIX_EPOCH_OFFSET_S, micropython_to_unix(0))

    def test_known_conversion(self):
        self.assertEqual(SYNCED_UNIX, micropython_to_unix(SYNCED_MP))
        self.assertEqual(SYNCED_MP, unix_to_micropython(SYNCED_UNIX))

    def test_round_trip(self):
        self.assertEqual(SYNCED_UNIX,
                         micropython_to_unix(unix_to_micropython(SYNCED_UNIX)))

    def test_plausibility_guard(self):
        self.assertFalse(is_plausible(None))
        self.assertFalse(is_plausible(UNIX_EPOCH_OFFSET_S))  # 2000-01-01
        self.assertFalse(is_plausible(MIN_PLAUSIBLE_UNIX_S - 1))
        self.assertTrue(is_plausible(MIN_PLAUSIBLE_UNIX_S))
        self.assertTrue(is_plausible(SYNCED_UNIX))

    def test_set_micropython_time_converts(self):
        service = TimeService()
        service.set_micropython_time(SYNCED_MP)
        self.assertEqual(SYNCED_UNIX, service.now())
        self.assertEqual(SOURCE_NTP, service.source)


class FormatTimestampTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(format_timestamp(None))

    def test_morning(self):
        secs = calendar.timegm((2026, 10, 18, 9, 5, 0, 0, 0, 0))
        self.assertEqual("2026-10-18 09:05:00 AM", format_timestamp(secs))

    def test_afternoon(self):
        secs = calendar.timegm((2026, 10, 18, 15, 30, 0, 0, 0, 0))
        self.assertEqual("2026-10-18 03:30:00 PM", format_timestamp(secs))

    def test_midnight_is_twelve_am(self):
        secs = calendar.timegm((2026, 10, 18, 0, 0, 0, 0, 0, 0))
        self.assertEqual("2026-10-18 12:00:00 AM", format_timestamp(secs))

    def test_noon_is_twelve_pm(self):
        secs = calendar.timegm((2026, 10, 18, 12, 0, 0, 0, 0, 0))
        self.assertEqual("2026-10-18 12:00:00 PM", format_timestamp(secs))

    def test_evening_pads_hour(self):
        secs = calendar.timegm((2026, 10, 18, 23, 45, 6, 0, 0, 0))
        self.assertEqual("2026-10-18 11:45:06 PM", format_timestamp(secs))

    def test_utc_to_local_offset_can_change_the_day(self):
        # 02:00 UTC on the 18th is 21:00 on the 17th at UTC-5.
        secs = calendar.timegm((2026, 10, 18, 2, 0, 0, 0, 0, 0))
        self.assertEqual("2026-10-17 09:00:00 PM",
                         format_timestamp(secs, offset_hours=-5))

    def test_positive_offset(self):
        secs = calendar.timegm((2026, 10, 18, 23, 30, 0, 0, 0, 0))
        self.assertEqual("2026-10-19 08:30:00 AM",
                         format_timestamp(secs, offset_hours=9))

    def test_fractional_offset(self):
        secs = calendar.timegm((2026, 10, 18, 6, 0, 0, 0, 0, 0))
        self.assertEqual("2026-10-18 11:30:00 AM",
                         format_timestamp(secs, offset_hours=5.5))

    def test_offset_is_applied_to_the_instant_passed_to_gmtime(self):
        seen = []

        def gmtime(secs):
            seen.append(secs)
            return (2026, 10, 18, 14, 3, 12, 0, 0)

        result = format_timestamp(1000, offset_hours=-5, gmtime=gmtime)
        self.assertEqual([1000 - 5 * 3600], seen)
        self.assertEqual("2026-10-18 02:03:12 PM", result)


class FakeTimeModule:
    """Stand-in for the MicroPython ``time`` module."""

    def __init__(self, micropython_seconds=0):
        self.value = micropython_seconds

    def time(self):
        return self.value


class FakeNtpModule:
    """Stand-in for the MicroPython ``ntptime`` module."""

    def __init__(self, update_to=None, time_module=None, error=None):
        self.host = None
        self.timeout = None
        self.settime_calls = 0
        self._update_to = update_to
        self._time_module = time_module
        self._error = error

    def settime(self):
        self.settime_calls += 1
        if self._error is not None:
            raise self._error
        if self._time_module is not None and self._update_to is not None:
            self._time_module.value = self._update_to


class NtpSyncTests(unittest.TestCase):
    def test_successful_sync_records_unix_time(self):
        time_module = FakeTimeModule(0)
        ntp = FakeNtpModule(update_to=SYNCED_MP, time_module=time_module)
        service = TimeService(ntp_module=ntp, time_module=time_module)

        self.assertTrue(service.sync_ntp(host="pool.ntp.org", timeout_s=10))
        self.assertEqual(SYNCED_UNIX, service.now())
        self.assertEqual(SOURCE_NTP, service.source)
        self.assertEqual(SYNCED_UNIX, service.last_sync_epoch)
        self.assertEqual("pool.ntp.org", ntp.host)
        self.assertEqual(10, ntp.timeout)

        status = service.status()
        self.assertTrue(status["synced"])
        self.assertTrue(status["last_sync_ok"])
        self.assertIsNone(status["last_error"])
        self.assertEqual(1, status["sync_count"])

    def test_ntp_failure_does_not_claim_sync(self):
        time_module = FakeTimeModule(0)
        ntp = FakeNtpModule(error=OSError("timed out"), time_module=time_module)
        service = TimeService(ntp_module=ntp, time_module=time_module)

        self.assertFalse(service.sync_ntp(host="pool.ntp.org", timeout_s=5))
        self.assertFalse(service.is_valid())
        self.assertIsNone(service.now())
        self.assertIsNone(service.source)

        status = service.status()
        self.assertFalse(status["synced"])
        self.assertFalse(status["last_sync_ok"])
        self.assertIn("OSError", status["last_error"])
        self.assertIsNone(status["last_sync_epoch"])

    def test_silent_non_update_is_rejected(self):
        # settime() returns without error but the clock still reads 0, i.e.
        # 2000-01-01. That must not be accepted as synchronized time.
        time_module = FakeTimeModule(0)
        ntp = FakeNtpModule(update_to=None, time_module=time_module)
        service = TimeService(ntp_module=ntp, time_module=time_module)

        self.assertFalse(service.sync_ntp())
        self.assertFalse(service.is_valid())
        self.assertIn("plausible", service.last_error)

    def test_failure_preserves_previous_valid_time(self):
        time_module = FakeTimeModule(0)
        ntp = FakeNtpModule(update_to=SYNCED_MP, time_module=time_module)
        service = TimeService(ntp_module=ntp, time_module=time_module)
        self.assertTrue(service.sync_ntp())

        ntp._error = OSError("network down")
        self.assertFalse(service.sync_ntp())

        self.assertTrue(service.is_valid())
        self.assertEqual(SYNCED_UNIX, service.now())
        status = service.status()
        self.assertTrue(status["synced"])
        self.assertFalse(status["last_sync_ok"])
        self.assertIn("OSError", status["last_error"])

    def test_missing_ntp_module_is_handled(self):
        try:
            import ntptime  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("ntptime is importable; cannot exercise import failure")

        service = TimeService(time_module=FakeTimeModule(0))
        self.assertFalse(service.sync_ntp())
        self.assertFalse(service.is_valid())
        self.assertIsNotNone(service.last_error)


if __name__ == "__main__":
    unittest.main()
