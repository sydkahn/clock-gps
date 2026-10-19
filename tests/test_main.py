"""Tests for device/main.py application integration.

Fakes stand in for Wi-Fi, the NTP/time source, and the BME280 driver, so no
hardware or network access is required. The loop's coordination behaviour is
exercised directly: startup wiring, periodic reads, failure isolation,
retry pacing, and clean Ctrl-C shutdown.
"""

import io
import unittest
from contextlib import redirect_stdout

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
import config
import main
from clock.time_service import UNIX_EPOCH_OFFSET_S, TimeService
from connectivity.wifi import STATE_CONNECTED, STATE_ERROR, WifiManager
from sensors import bme280
from sensors.base import STATUS_ERROR, STATUS_OK, SensorError
from sensors.manager import SensorManager
from sensors.weather import TREND_RISING, TREND_WAITING, WeatherSensor

SYNCED_UNIX = 1_700_000_000  # 2023-11-14T22:13:20Z
SYNCED_MP = SYNCED_UNIX - UNIX_EPOCH_OFFSET_S


class FakeClock:
    """Controllable monotonic clock (seconds)."""

    def __init__(self, start=0.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds
        return self.value


class FakeWifi:
    """Minimal stand-in for connectivity.wifi.WifiManager."""

    def __init__(self, connect_ok=True, ip="10.0.0.203",
                 initially_connected=False, last_error="network down"):
        self.connect_ok = connect_ok
        self._ip = ip
        self._connected = initially_connected
        self._last_error = last_error
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        self._connected = self.connect_ok
        return self.connect_ok

    def is_connected(self):
        return self._connected

    def ip_address(self):
        return self._ip if self._connected else None

    def status(self):
        return {
            "state": STATE_CONNECTED if self._connected else STATE_ERROR,
            "connected": self._connected,
            "ip": self._ip if self._connected else None,
            "credentials_configured": True,
            "last_error": None if self._connected else self._last_error,
        }


class FakeTimeModule:
    def __init__(self, value=0):
        self.value = value

    def time(self):
        return self.value


class FakeNtp:
    def __init__(self, update_to=None, time_module=None, error=None):
        self.host = None
        self.timeout = None
        self.calls = 0
        self._update_to = update_to
        self._time_module = time_module
        self._error = error

    def settime(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._time_module is not None and self._update_to is not None:
            self._time_module.value = self._update_to


def make_time_service(ok=True):
    """Return (TimeService, FakeNtp) whose NTP sync succeeds or fails."""
    time_module = FakeTimeModule(0)
    ntp = FakeNtp(update_to=(SYNCED_MP if ok else None),
                  time_module=time_module,
                  error=None if ok else OSError("ntp down"))
    return TimeService(ntp_module=ntp, time_module=time_module), ntp


class FakeDriver:
    """Stand-in for the BME280 driver."""

    def __init__(self, temperature_c=20.0, pressure_pa=99000.0,
                 humidity_pct=50.0, error=None):
        self.temperature_c = temperature_c
        self.pressure_pa = pressure_pa
        self.humidity_pct = humidity_pct
        self.error = error
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
        return {
            "temperature_c": self.temperature_c,
            "pressure_pa": self.pressure_pa,
            "humidity_pct": self.humidity_pct,
        }


class FakeDashboard:
    """Stand-in for connectivity.dashboard.Dashboard."""

    def __init__(self, enabled=True, refresh_results=None):
        self._enabled = enabled
        self._refresh_results = list(refresh_results or [])
        self.start_calls = 0
        self.stop_calls = 0
        self.updates = []
        self.waits = []

    def start(self):
        self.start_calls += 1
        return self._enabled

    def stop(self):
        self.stop_calls += 1

    @property
    def enabled(self):
        return self._enabled

    def update(self, records):
        self.updates.append(records)

    def service_until(self, deadline):
        self.waits.append(deadline)
        if self._refresh_results:
            return self._refresh_results.pop(0)
        return False


def make_app(time_service=None, wifi=None, driver=None, clock=None, sleep=None,
             config_obj=None, interval_s=None, dashboard=None, **kwargs):
    """Build an app with a single weather sensor using *driver*."""
    if config_obj is None:
        config_obj = config.Config()
    if wifi is None:
        wifi = FakeWifi()
    if clock is None:
        clock = FakeClock()
    if dashboard is None:
        dashboard = FakeDashboard(enabled=False)
    manager = SensorManager(time_service=time_service)
    manager.register(WeatherSensor(config=config_obj, driver=driver,
                                   time_service=time_service))
    app = main.ClockGpsApp(config_obj, wifi=wifi, time_service=time_service,
                           sensor_manager=manager, clock=clock, sleep=sleep,
                           interval_s=interval_s, dashboard=dashboard, **kwargs)
    return app, manager


def build_reading(**overrides):
    reading = {
        "temperature_f": 68.0,
        "temperature_c": 20.0,
        "humidity_pct": 50.0,
        "pressure_station_hpa": 990.0,
        "pressure_station_inhg": 29.235,
        "pressure_sea_level_hpa": 1012.26,
        "pressure_sea_level_inhg": 29.892,
        "elevation_ft": 627,
        "sea_level_estimated": True,
        "pressure_trend": TREND_WAITING,
        "pressure_trend_delta_hpa": None,
    }
    reading.update(overrides)
    return reading


class FormatReadingTests(unittest.TestCase):
    def test_reports_required_units_and_estimate_marker(self):
        text = main.format_reading(build_reading())
        self.assertIn("68.0 F", text)
        self.assertIn("50.0 %", text)
        self.assertIn("station 29.235 inHg", text)
        self.assertIn("sea-level 29.892 inHg (estimated)", text)
        self.assertIn(TREND_WAITING, text)

    def test_trend_delta_is_shown_when_available(self):
        text = main.format_reading(build_reading(
            pressure_trend=TREND_RISING, pressure_trend_delta_hpa=2.5))
        self.assertIn("rising", text)
        self.assertIn("+2.50 hPa", text)

    def test_station_and_sea_level_are_separate(self):
        text = main.format_reading(build_reading())
        self.assertIn("station", text)
        self.assertIn("sea-level", text)
        self.assertNotIn("station 29.892", text)


class WiringTests(unittest.TestCase):
    def test_bme280_wiring_matches_the_board(self):
        self.assertEqual(0x76, bme280.DEFAULT_ADDRESS)
        self.assertEqual(16, bme280.DEFAULT_SDA_PIN)
        self.assertEqual(17, bme280.DEFAULT_SCL_PIN)
        self.assertEqual(0x76, main.BME280_ADDRESS)
        self.assertEqual(16, main.BME280_SDA_PIN)
        self.assertEqual(17, main.BME280_SCL_PIN)

    def test_default_app_registers_the_weather_sensor(self):
        app = main.ClockGpsApp(config.Config(), wifi=FakeWifi(),
                               time_service=TimeService(), clock=FakeClock())
        names = [sensor.name for sensor in app._manager.sensors]
        self.assertEqual(["weather"], names)


class StartupTests(unittest.TestCase):
    def test_connects_wifi_and_synchronizes_time(self):
        time_service, ntp = make_time_service(ok=True)
        wifi = FakeWifi()
        app, _ = make_app(time_service=time_service, wifi=wifi,
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
        self.assertEqual(1, wifi.connect_calls)
        self.assertTrue(time_service.is_valid())
        self.assertEqual(1, ntp.calls)
        text = output.getvalue()
        self.assertIn("Wi-Fi connected", text)
        self.assertIn("time synchronized", text)

    def test_wifi_failure_is_logged_and_not_fatal(self):
        time_service, ntp = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service,
                          wifi=FakeWifi(connect_ok=False),
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
        self.assertIn("Wi-Fi unavailable", output.getvalue())
        self.assertFalse(time_service.is_valid())
        self.assertEqual(0, ntp.calls)  # no NTP without a connection

    def test_ntp_failure_is_logged_and_not_fatal(self):
        time_service, ntp = make_time_service(ok=False)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
        self.assertIn("NTP time unavailable", output.getvalue())
        self.assertEqual(1, ntp.calls)
        self.assertFalse(time_service.is_valid())

    def test_sensor_initialize_failure_is_isolated(self):
        time_service, _ = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(error=SensorError("absent")))
        output = io.StringIO()
        with redirect_stdout(output):
            results = app.setup()
        self.assertTrue(results["weather"].startswith(STATUS_ERROR))
        self.assertIn("sensor weather unavailable", output.getvalue())


class ReadingLoopTests(unittest.TestCase):
    def test_run_once_reports_a_weather_line(self):
        time_service, _ = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
            records = app.run_once()
        self.assertEqual(STATUS_OK, records[0]["status"])
        text = output.getvalue()
        self.assertIn("temp", text)
        self.assertIn("inHg", text)
        self.assertIn("trend", text)

    def test_read_failure_is_reported_not_raised(self):
        time_service, _ = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(error=SensorError("busy")))
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
            records = app.run_once()
        self.assertEqual(STATUS_ERROR, records[0]["status"])
        self.assertIsNone(records[0]["value"])
        self.assertIn("weather unavailable", output.getvalue())

    def test_loop_continues_after_a_read_failure(self):
        time_service, _ = make_time_service(ok=True)
        driver = FakeDriver()
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=driver)
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
            first = app.run_once()          # good reading
            driver.error = SensorError("gone")
            second = app.run_once()         # failing reading
        self.assertEqual(STATUS_OK, first[0]["status"])
        self.assertEqual(STATUS_ERROR, second[0]["status"])
        self.assertEqual(2, driver.read_calls)

    def test_trend_is_computed_across_the_window(self):
        time_service, _ = make_time_service(ok=True)
        driver = FakeDriver(pressure_pa=100000.0)  # 1000 hPa
        config_obj = config.Config(pressure_trend_window_s=10800)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=driver, config_obj=config_obj,
                          clock=FakeClock())
        with redirect_stdout(io.StringIO()):
            app.setup()
            app.run_once()                          # sample at SYNCED_UNIX

        time_service.set_time(SYNCED_UNIX + 10800, "ntp")
        driver.pressure_pa = 100250.0               # +2.5 hPa
        output = io.StringIO()
        with redirect_stdout(output):
            app.run_once()
        self.assertIn("rising", output.getvalue())
        self.assertIn("+2.50 hPa", output.getvalue())


class RetryPacingTests(unittest.TestCase):
    def test_wifi_retry_is_rate_limited(self):
        time_service, _ = make_time_service(ok=True)
        wifi = FakeWifi(connect_ok=False)
        clock = FakeClock()
        app, _ = make_app(time_service=time_service, wifi=wifi,
                          driver=FakeDriver(), clock=clock)
        with redirect_stdout(io.StringIO()):
            app.setup()                 # attempt 1
            app.run_once()              # within the backoff window
        self.assertEqual(1, wifi.connect_calls)

        clock.advance(30)
        with redirect_stdout(io.StringIO()):
            app.run_once()
        self.assertEqual(1, wifi.connect_calls)     # still backing off

        clock.advance(60)
        with redirect_stdout(io.StringIO()):
            app.run_once()
        self.assertEqual(2, wifi.connect_calls)     # retried once

    def test_ntp_retry_is_rate_limited(self):
        time_service, ntp = make_time_service(ok=False)
        clock = FakeClock()
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), clock=clock)
        with redirect_stdout(io.StringIO()):
            app.setup()                 # sync attempt 1
            app.run_once()              # within the backoff window
        self.assertEqual(1, ntp.calls)

        clock.advance(30)
        with redirect_stdout(io.StringIO()):
            app.run_once()
        self.assertEqual(1, ntp.calls)

        clock.advance(60)
        with redirect_stdout(io.StringIO()):
            app.run_once()
        self.assertEqual(2, ntp.calls)

    def test_ntp_resync_gated_by_configured_interval(self):
        time_service, ntp = make_time_service(ok=True)
        clock = FakeClock()
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), clock=clock,
                          config_obj=config.Config(ntp_interval_s=3600))
        with redirect_stdout(io.StringIO()):
            app.setup()
        self.assertEqual(1, ntp.calls)

        clock.advance(1800)             # half the interval
        with redirect_stdout(io.StringIO()):
            app.run_once()
        self.assertEqual(1, ntp.calls)

        clock.advance(1800)             # interval reached
        with redirect_stdout(io.StringIO()):
            app.run_once()
        self.assertEqual(2, ntp.calls)


class RunLoopTests(unittest.TestCase):
    def test_ctrl_c_stops_the_loop(self):
        time_service, _ = make_time_service(ok=True)
        sleep_calls = []

        def sleep(seconds):
            sleep_calls.append(seconds)
            raise KeyboardInterrupt

        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), sleep=sleep)
        output = io.StringIO()
        with redirect_stdout(output):
            result = app.run()
        self.assertEqual(0, result)
        self.assertEqual(1, len(sleep_calls))
        self.assertIn("stopped", output.getvalue())

    def test_interval_comes_from_configuration(self):
        time_service, _ = make_time_service(ok=True)
        sleep_calls = []

        def sleep(seconds):
            sleep_calls.append(seconds)
            raise KeyboardInterrupt

        config_obj = config.Config(telemetry_interval_s=123)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), sleep=sleep,
                          config_obj=config_obj)
        with redirect_stdout(io.StringIO()):
            app.run()
        self.assertEqual([123], sleep_calls)
        self.assertEqual(123, app.interval_s)


class FakeWLAN:
    def __init__(self):
        self._connected = False

    def active(self, value=None):
        return True

    def isconnected(self):
        return self._connected

    def connect(self, ssid, psk):
        self._connected = True

    def disconnect(self):
        self._connected = False

    def ifconfig(self):
        return ("10.0.0.203", "255.255.255.0", "10.0.0.1", "10.0.0.1")


class FakeNetwork:
    STA_IF = 0

    def __init__(self, wlan):
        self._wlan = wlan

    def WLAN(self, mode):
        return self._wlan


class WifiManagerIntegrationTests(unittest.TestCase):
    def test_app_does_not_print_ssid_or_password(self):
        credentials = config.Credentials(wifi_ssid="MyNetwork",
                                         wifi_password="hunter2")
        wifi = WifiManager(credentials,
                           network_module=FakeNetwork(FakeWLAN()),
                           clock=FakeClock(),
                           sleep=lambda seconds: None)
        time_service, _ = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service, wifi=wifi,
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
        text = output.getvalue()
        self.assertIn("Wi-Fi connected", text)
        self.assertIn("10.0.0.203", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("MyNetwork", text)


class DashboardWiringTests(unittest.TestCase):
    def test_setup_starts_the_dashboard(self):
        time_service, _ = make_time_service(ok=True)
        dash = FakeDashboard(enabled=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), dashboard=dash)
        with redirect_stdout(io.StringIO()):
            app.setup()
        self.assertEqual(1, dash.start_calls)

    def test_run_once_hands_records_to_the_dashboard(self):
        time_service, _ = make_time_service(ok=True)
        dash = FakeDashboard(enabled=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), dashboard=dash)
        with redirect_stdout(io.StringIO()):
            app.setup()
            records = app.run_once()
        self.assertEqual(1, len(dash.updates))
        self.assertIs(dash.updates[0], records)

    def test_disabled_dashboard_uses_plain_sleep(self):
        time_service, _ = make_time_service(ok=True)
        dash = FakeDashboard(enabled=False)
        sleep_calls = []

        def sleep(seconds):
            sleep_calls.append(seconds)
            raise KeyboardInterrupt

        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), dashboard=dash, sleep=sleep)
        with redirect_stdout(io.StringIO()):
            app.run()
        self.assertEqual([300], sleep_calls)
        self.assertEqual([], dash.waits)          # never serviced
        self.assertEqual(1, dash.stop_calls)

    def test_enabled_dashboard_is_serviced_during_the_wait(self):
        time_service, _ = make_time_service(ok=True)
        dash = FakeDashboard(enabled=True)
        clock = FakeClock()
        sleep_calls = []

        def sleep(seconds):
            sleep_calls.append(seconds)
            clock.advance(seconds)

        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(), dashboard=dash, clock=clock,
                          sleep=sleep)
        with redirect_stdout(io.StringIO()):
            app.setup()
            app._wait(300)
        self.assertEqual(1, len(dash.waits))
        # service_until returned False without consuming the interval, so the
        # loop fell back to a sleep of the remaining time.
        self.assertEqual([300], sleep_calls)

    def test_refresh_request_triggers_one_reading_and_restarts_interval(self):
        time_service, _ = make_time_service(ok=True)
        driver = FakeDriver()
        dash = FakeDashboard(enabled=True, refresh_results=[True])
        clock = FakeClock()

        def sleep(seconds):
            clock.advance(seconds)

        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=driver, dashboard=dash, clock=clock,
                          sleep=sleep)
        with redirect_stdout(io.StringIO()):
            app.setup()
            app._wait(300)
        # Exactly one extra reading, taken by the app loop, not the handler.
        self.assertEqual(1, driver.read_calls)
        self.assertEqual(1, len(dash.updates))

    def test_default_dashboard_uses_configuration(self):
        app = main.ClockGpsApp(config.Config(web_port=8080, web_enabled=True),
                               wifi=FakeWifi(), time_service=TimeService(),
                               clock=FakeClock())
        self.assertEqual(8080, app._dashboard.port)

    def test_disabled_config_leaves_dashboard_inactive(self):
        app = main.ClockGpsApp(config.Config(web_enabled=False),
                               wifi=FakeWifi(), time_service=TimeService(),
                               clock=FakeClock())
        self.assertFalse(app._dashboard.enabled)


class TimestampTests(unittest.TestCase):
    # SYNCED_UNIX is 2023-11-14T22:13:20Z.
    def test_reading_line_uses_twelve_hour_local_time(self):
        time_service, _ = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
            app.run_once()
        # Default offset is -5 (Eastern Standard), so 22:13:20Z is 5:13:20 PM.
        self.assertTrue(
            any(line.startswith("[clock-gps] 2023-11-14 05:13:20 PM | temp")
                for line in output.getvalue().splitlines()),
            output.getvalue())

    def test_configured_offset_applies_to_the_display(self):
        time_service, _ = make_time_service(ok=True)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver(),
                          config_obj=config.Config(utc_offset_hours=0))
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
            app.run_once()
        self.assertIn("[clock-gps] 2023-11-14 10:13:20 PM | temp",
                      output.getvalue())

    def test_unsynchronized_clock_shows_time_not_set(self):
        time_service, _ = make_time_service(ok=False)
        app, _ = make_app(time_service=time_service, wifi=FakeWifi(),
                          driver=FakeDriver())
        output = io.StringIO()
        with redirect_stdout(output):
            app.setup()
            app.run_once()
        self.assertIn("[clock-gps] TIME NOT SET | temp", output.getvalue())
        self.assertNotIn("1970-01-01", output.getvalue())


if __name__ == "__main__":
    unittest.main()
