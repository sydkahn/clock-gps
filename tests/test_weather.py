"""Tests for device/sensors/weather.py.

Covers conversions, sea-level estimation, pressure-trend detection, history
persistence, error handling, and SensorManager compatibility. No hardware is
required: the driver and time source are injected.
"""

import os
import tempfile
import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
import config
from clock.time_service import TimeService
from sensors.base import (STATUS_ERROR, STATUS_OK, STATUS_UNAVAILABLE, Sensor,
                          SensorError)
from sensors.manager import SensorManager
from sensors.weather import (
    PressureHistoryStore,
    TREND_FALLING,
    TREND_RISING,
    TREND_STEADY,
    TREND_WAITING,
    TrendTracker,
    WeatherSensor,
    celsius_to_fahrenheit,
    classify_trend,
    elevation_ft_to_m,
    hpa_to_inhg,
    pa_to_inhg,
    sea_level_pressure_hpa,
)

WINDOW = 10800  # three hours

_UNSET = object()


class FakeDriver:
    def __init__(self, temperature_c=20.0, pressure_pa=99000.0,
                 humidity_pct=50.0, error=None, raw=_UNSET):
        self.temperature_c = temperature_c
        self.pressure_pa = pressure_pa
        self.humidity_pct = humidity_pct
        self.error = error
        self.raw = raw
        self.initialize_calls = 0
        self.read_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        if self.error is not None:
            raise self.error

    def read(self):
        self.read_calls += 1
        if self.error is not None:
            raise self.error
        if self.raw is not _UNSET:
            return self.raw
        return {
            "temperature_c": self.temperature_c,
            "pressure_pa": self.pressure_pa,
            "humidity_pct": self.humidity_pct,
        }


class FakeStore:
    def __init__(self, records=None, fail_save=False):
        self.records = list(records or [])
        self.fail_save = fail_save
        self.saves = 0
        self.saved = None

    def load(self):
        return list(self.records)

    def save(self, samples):
        self.saves += 1
        if self.fail_save:
            return False
        self.saved = list(samples)
        return True


class GoodSensor(Sensor):
    name = "other"

    def initialize(self):
        return None

    def read(self):
        return 123


def valid_time(seconds):
    service = TimeService()
    service.set_time(seconds, "ntp")
    return service


class ConversionTests(unittest.TestCase):
    def test_celsius_to_fahrenheit(self):
        self.assertEqual(32.0, celsius_to_fahrenheit(0.0))
        self.assertEqual(212.0, celsius_to_fahrenheit(100.0))
        self.assertAlmostEqual(98.6, celsius_to_fahrenheit(37.0), places=6)
        self.assertAlmostEqual(68.0, celsius_to_fahrenheit(20.0), places=6)

    def test_pressure_to_inches_of_mercury(self):
        self.assertAlmostEqual(29.9213, pa_to_inhg(101325.0), places=3)
        self.assertAlmostEqual(29.9213, hpa_to_inhg(1013.25), places=3)
        # 1000 hPa is a common station pressure.
        self.assertAlmostEqual(29.530, hpa_to_inhg(1000.0), places=3)

    def test_elevation_conversion(self):
        self.assertAlmostEqual(191.1096, elevation_ft_to_m(627), places=3)


class SeaLevelTests(unittest.TestCase):
    def test_zero_elevation_matches_station(self):
        self.assertEqual(1000.0, sea_level_pressure_hpa(1000.0, 15.0, 0.0))

    def test_positive_elevation_raises_estimate(self):
        station = 990.6
        estimate = sea_level_pressure_hpa(station, 15.0,
                                          elevation_ft_to_m(627))
        self.assertGreater(estimate, station)
        self.assertTrue(1012.0 <= estimate <= 1014.5, estimate)

    def test_negative_elevation_lowers_estimate(self):
        station = 1015.0
        estimate = sea_level_pressure_hpa(station, 15.0, -100.0)
        self.assertLess(estimate, station)

    def test_implausible_temperature_is_rejected(self):
        with self.assertRaises(ValueError):
            sea_level_pressure_hpa(1000.0, -400.0, 200.0)


class TrendClassificationTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        self.assertEqual(TREND_RISING, classify_trend(1.0, 1.0))
        self.assertEqual(TREND_FALLING, classify_trend(-1.0, 1.0))
        self.assertEqual(TREND_STEADY, classify_trend(0.99, 1.0))
        self.assertEqual(TREND_STEADY, classify_trend(-0.99, 1.0))
        self.assertEqual(TREND_WAITING, classify_trend(None, 1.0))


class TrendTrackerTests(unittest.TestCase):
    def test_insufficient_history(self):
        tracker = TrendTracker(window_s=WINDOW)
        self.assertEqual((TREND_WAITING, None), tracker.trend(0))
        tracker.add(0, 1000.0)
        self.assertEqual((TREND_WAITING, None), tracker.trend(0))

    def test_rising(self):
        tracker = TrendTracker(window_s=WINDOW)
        tracker.add(0, 1000.0)
        tracker.add(WINDOW, 1002.0)
        self.assertEqual((TREND_RISING, 2.0), tracker.trend(WINDOW))

    def test_falling(self):
        tracker = TrendTracker(window_s=WINDOW)
        tracker.add(0, 1002.0)
        tracker.add(WINDOW, 1000.0)
        self.assertEqual((TREND_FALLING, -2.0), tracker.trend(WINDOW))

    def test_steady(self):
        tracker = TrendTracker(window_s=WINDOW)
        tracker.add(0, 1000.0)
        tracker.add(WINDOW, 1000.5)
        self.assertEqual((TREND_STEADY, 0.5), tracker.trend(WINDOW))

    def test_gap_outside_tolerance_waits(self):
        tracker = TrendTracker(window_s=WINDOW, tolerance_s=1800)
        tracker.add(0, 1000.0)
        tracker.add(3600, 1002.0)  # only one hour apart
        self.assertEqual((TREND_WAITING, None), tracker.trend(3600))

    def test_non_monotonic_and_duplicate_are_ignored(self):
        tracker = TrendTracker(window_s=WINDOW)
        self.assertTrue(tracker.add(1000, 1000.0))
        self.assertFalse(tracker.add(1000, 1005.0))  # duplicate timestamp
        self.assertFalse(tracker.add(500, 999.0))    # going backwards
        self.assertEqual([(1000, 1000.0)], tracker.samples())

    def test_stale_samples_are_pruned(self):
        tracker = TrendTracker(window_s=WINDOW, max_age_s=20000)
        tracker.add(0, 1000.0)
        tracker.add(10000, 1001.0)
        tracker.add(30000, 1002.0)
        self.assertEqual([(10000, 1001.0), (30000, 1002.0)], tracker.samples())

    def test_clock_jump_forward_waits(self):
        tracker = TrendTracker(window_s=WINDOW, tolerance_s=1800)
        tracker.add(0, 1000.0)
        tracker.add(WINDOW, 1002.0)
        self.assertEqual((TREND_WAITING, None), tracker.trend(30000))

    def test_load_discards_corrupt_and_out_of_range(self):
        tracker = TrendTracker(window_s=WINDOW)
        records = [
            [WINDOW, 1002.0],
            [0, 1000.0],
            [0, 1000.0],           # duplicate
            ["x", "y"],            # unparsable
            None,                  # malformed entry
            [5000, 99999.0],       # out of range
            [9000, 1001.0],
        ]
        self.assertEqual(3, tracker.load(records))
        self.assertEqual([(0, 1000.0), (9000, 1001.0), (WINDOW, 1002.0)],
                         tracker.samples())


class PressureHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.json")

    def test_save_and_load_round_trip(self):
        store = PressureHistoryStore(self.path)
        self.assertTrue(store.save([(0, 1000.0), (WINDOW, 1002.5)]))
        self.assertEqual([[0, 1000.0], [WINDOW, 1002.5]], store.load())

    def test_missing_file_returns_empty(self):
        store = PressureHistoryStore(os.path.join(self.dir, "absent.json"))
        self.assertEqual([], store.load())

    def test_corrupt_content_returns_empty(self):
        store = PressureHistoryStore(self.path)
        with open(self.path, "w") as handle:
            handle.write("{not valid json")
        self.assertEqual([], store.load())

    def test_wrong_version_returns_empty(self):
        store = PressureHistoryStore(self.path)
        with open(self.path, "w") as handle:
            handle.write('{"v": 99, "samples": [[0, 1000.0]]}')
        self.assertEqual([], store.load())

    def test_non_list_samples_returns_empty(self):
        store = PressureHistoryStore(self.path)
        with open(self.path, "w") as handle:
            handle.write('{"v": 1, "samples": "nope"}')
        self.assertEqual([], store.load())


class WeatherSensorTests(unittest.TestCase):
    def make_sensor(self, driver, time_service=None, store=None,
                    persist_interval_s=0, elevation_ft=627, config_obj=None):
        if config_obj is None:
            config_obj = config.Config(
                elevation_ft=elevation_ft,
                pressure_trend_window_s=WINDOW,
                pressure_trend_threshold_hpa=1.0)
        sensor = WeatherSensor(config=config_obj, driver=driver,
                               time_service=time_service, store=store,
                               persist_interval_s=persist_interval_s)
        return sensor

    def test_reading_contains_documented_keys_and_units(self):
        sensor = self.make_sensor(FakeDriver(temperature_c=20.0,
                                             pressure_pa=99000.0,
                                             humidity_pct=50.0))
        sensor.initialize()
        reading = sensor.read()
        self.assertEqual(68.0, reading["temperature_f"])
        self.assertEqual(20.0, reading["temperature_c"])
        self.assertEqual(50.0, reading["humidity_pct"])
        self.assertAlmostEqual(990.0, reading["pressure_station_hpa"], places=2)
        self.assertAlmostEqual(29.235, reading["pressure_station_inhg"],
                               places=3)
        self.assertGreater(reading["pressure_sea_level_hpa"],
                           reading["pressure_station_hpa"])
        self.assertGreater(reading["pressure_sea_level_inhg"],
                           reading["pressure_station_inhg"])
        self.assertEqual(627, reading["elevation_ft"])
        self.assertTrue(reading["sea_level_estimated"])
        self.assertEqual(TREND_WAITING, reading["pressure_trend"])
        self.assertIsNone(reading["pressure_trend_delta_hpa"])

    def test_station_and_sea_level_are_separate(self):
        sensor = self.make_sensor(FakeDriver(pressure_pa=99000.0))
        sensor.initialize()
        reading = sensor.read()
        self.assertNotEqual(reading["pressure_station_hpa"],
                            reading["pressure_sea_level_hpa"])

    def test_calibration_offset_only_adjusts_sea_level_pressure(self):
        raw = FakeDriver(pressure_pa=99000.0)
        uncalibrated = self.make_sensor(
            raw, config_obj=config.Config(
                elevation_ft=627, pressure_calibration_offset_inhg=0.0))
        uncalibrated.initialize()
        base = uncalibrated.read()

        calibrated = self.make_sensor(
            raw, config_obj=config.Config(
                elevation_ft=627,
                pressure_calibration_offset_inhg=-0.373))
        calibrated.initialize()
        corrected = calibrated.read()

        self.assertEqual(base["pressure_station_hpa"],
                         corrected["pressure_station_hpa"])
        self.assertEqual(base["pressure_station_inhg"],
                         corrected["pressure_station_inhg"])
        self.assertAlmostEqual(-0.373,
                               corrected["pressure_sea_level_inhg"]
                               - base["pressure_sea_level_inhg"], places=3)

    def test_reading_status_is_ok_when_initialized(self):
        sensor = self.make_sensor(FakeDriver())
        self.assertEqual(STATUS_UNAVAILABLE, sensor.status())
        sensor.initialize()
        self.assertEqual(STATUS_OK, sensor.status())

    def test_read_before_initialize_raises(self):
        sensor = self.make_sensor(FakeDriver())
        with self.assertRaises(SensorError):
            sensor.read()

    def test_missing_time_waits_and_adds_no_history(self):
        sensor = self.make_sensor(FakeDriver())
        sensor.initialize()
        reading = sensor.read()
        self.assertEqual(TREND_WAITING, reading["pressure_trend"])
        self.assertEqual([], sensor.history)

    def test_invalid_time_waits(self):
        sensor = self.make_sensor(FakeDriver(), time_service=TimeService())
        sensor.initialize()
        reading = sensor.read()
        self.assertEqual(TREND_WAITING, reading["pressure_trend"])
        self.assertEqual([], sensor.history)

    def test_trend_across_three_hours(self):
        config_obj = config.Config(elevation_ft=627,
                                   pressure_trend_window_s=WINDOW,
                                   pressure_trend_threshold_hpa=1.0)
        driver = FakeDriver(pressure_pa=100000.0)  # 1000 hPa
        time_service = valid_time(0)
        sensor = self.make_sensor(driver, time_service=time_service,
                                  config_obj=config_obj)
        sensor.initialize()
        sensor.read()  # sample at t=0

        time_service.set_time(WINDOW, "ntp")
        driver.pressure_pa = 100250.0  # +2.5 hPa
        reading = sensor.read()
        self.assertEqual(TREND_RISING, reading["pressure_trend"])
        self.assertEqual(2.5, reading["pressure_trend_delta_hpa"])

    def test_driver_error_propagates(self):
        sensor = self.make_sensor(FakeDriver(error=SensorError("boom")))
        with self.assertRaises(SensorError):
            sensor.initialize()

    def test_malformed_readings_raise(self):
        for raw in (None, {"temperature_c": "x", "pressure_pa": 99000.0,
                           "humidity_pct": 50.0},
                    {"temperature_c": 20.0, "pressure_pa": 0.0,
                     "humidity_pct": 50.0},
                    {"temperature_c": 20.0, "pressure_pa": 99000.0,
                     "humidity_pct": 150.0}):
            sensor = self.make_sensor(FakeDriver(raw=raw))
            sensor.initialize()
            with self.assertRaises(SensorError):
                sensor.read()

    def test_persistence_gating_limits_writes(self):
        store = FakeStore()
        driver = FakeDriver(pressure_pa=100000.0)
        time_service = valid_time(0)
        sensor = self.make_sensor(driver, time_service=time_service,
                                  store=store, persist_interval_s=1000)
        sensor.initialize()
        sensor.read()  # t=0: first write
        self.assertEqual(1, store.saves)

        time_service.set_time(600, "ntp")
        sensor.read()  # +600 s: within interval, no write
        self.assertEqual(1, store.saves)

        time_service.set_time(1200, "ntp")
        sensor.read()  # +1200 s: write again
        self.assertEqual(2, store.saves)

    def test_restart_recovers_history_from_store(self):
        store = FakeStore(records=[[0, 1000.0]])
        driver = FakeDriver(pressure_pa=100200.0)  # 1002 hPa
        time_service = valid_time(WINDOW)
        sensor = self.make_sensor(driver, time_service=time_service,
                                  store=store)
        sensor.initialize()
        reading = sensor.read()
        self.assertEqual(TREND_RISING, reading["pressure_trend"])
        self.assertEqual(2.0, reading["pressure_trend_delta_hpa"])


class ManagerCompatibilityTests(unittest.TestCase):
    def test_manager_reads_weather_sensor(self):
        manager = SensorManager(time_service=valid_time(0))
        sensor = WeatherSensor(config=config.Config(elevation_ft=627),
                               driver=FakeDriver())
        manager.register(sensor)
        results = manager.initialize_all()
        self.assertEqual(STATUS_OK, results["weather"])

        records = manager.read_all()
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("weather", record["sensor"])
        self.assertEqual(STATUS_OK, record["status"])
        self.assertIsInstance(record["value"], dict)
        self.assertIn("temperature_f", record["value"])
        self.assertEqual(0, record["timestamp"])

    def test_weather_failure_does_not_stop_other_sensors(self):
        manager = SensorManager()
        manager.register(WeatherSensor(config=config.Config(),
                                       driver=FakeDriver(error=SensorError("x"))))
        manager.register(GoodSensor())
        manager.initialize_all()
        records = {r["sensor"]: r for r in manager.read_all()}
        self.assertEqual(STATUS_ERROR, records["weather"]["status"])
        self.assertEqual(STATUS_OK, records["other"]["status"])


if __name__ == "__main__":
    unittest.main()
