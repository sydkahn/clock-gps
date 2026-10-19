"""Tests for device/config.py configuration and credential validation.

These run on the development computer and use only the standard library.
"""

import sys
import types
import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
import config


class PlaceholderTests(unittest.TestCase):
    def test_placeholder_detection(self):
        self.assertTrue(config.is_placeholder(None))
        self.assertTrue(config.is_placeholder("<your-wifi-ssid>"))
        self.assertTrue(config.is_placeholder("   "))
        self.assertFalse(config.is_placeholder("MyNetwork"))
        self.assertFalse(config.is_placeholder(1883))


class DeviceIdTests(unittest.TestCase):
    def test_valid_ids(self):
        for value in ("clock-gps-01", "esp32_a", "abc123"):
            self.assertIsNone(config.validate_device_id(value), value)

    def test_empty_and_invalid_ids(self):
        self.assertIsNotNone(config.validate_device_id(""))
        self.assertIsNotNone(config.validate_device_id("has space"))
        self.assertIsNotNone(config.validate_device_id("bad/slash"))


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        app_config = config.Config()
        self.assertEqual([], app_config.validate())
        self.assertTrue(app_config.is_valid())

    def test_invalid_device_id_is_reported(self):
        problems = config.Config(device_id="bad/id").validate()
        self.assertTrue(any("device_id" in p for p in problems))

    def test_placeholder_ntp_host_is_reported(self):
        problems = config.Config(ntp_host="<ntp-host>").validate()
        self.assertTrue(any("ntp_host" in p for p in problems))

    def test_intervals_must_be_large_enough(self):
        problems = config.Config(telemetry_interval_s=1).validate()
        self.assertTrue(any("telemetry_interval_s" in p for p in problems))

    def test_non_integer_interval_is_reported(self):
        problems = config.Config(ntp_timeout_s="soon").validate()
        self.assertTrue(any("ntp_timeout_s" in p for p in problems))

    def test_topic_composition(self):
        app_config = config.Config(device_id="clock-gps-01")
        self.assertEqual("clock-gps/clock-gps-01/telemetry",
                         app_config.topic("telemetry"))


class CredentialTests(unittest.TestCase):
    def test_placeholder_credentials_are_rejected(self):
        credentials = config.Credentials.from_module(types.SimpleNamespace())
        problems = credentials.validate()
        self.assertTrue(any("WIFI_SSID" in p for p in problems))
        self.assertTrue(any("WIFI_PASSWORD" in p for p in problems))

    def test_credentials_error_does_not_leak_values(self):
        credentials = config.Credentials(
            wifi_ssid="<placeholder>", wifi_password="<placeholder>")
        problems = credentials.validate()
        joined = "; ".join(problems)
        self.assertNotIn("<placeholder>", joined)

    def test_complete_credentials_pass(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2")
        self.assertEqual([], credentials.validate())

    def test_mqtt_optional_until_configured(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2")
        self.assertFalse(credentials.has_mqtt())

    def test_mqtt_detected_when_host_set(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2",
            mqtt_host="broker.local")
        self.assertTrue(credentials.has_mqtt())
        self.assertEqual([], credentials.validate())

    def test_invalid_mqtt_port_is_reported(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2",
            mqtt_host="broker.local", mqtt_port=70000)
        self.assertTrue(any("MQTT_PORT" in p for p in credentials.validate()))


class LoadTests(unittest.TestCase):
    def test_load_with_valid_module(self):
        module = types.SimpleNamespace(
            WIFI_SSID="MyNetwork", WIFI_PASSWORD="hunter2")
        app_config = config.load(credentials_module=module)
        self.assertIsNotNone(app_config.credentials)
        self.assertEqual("MyNetwork", app_config.credentials.wifi_ssid)

    def test_load_with_incomplete_module_raises_without_values(self):
        module = types.SimpleNamespace(WIFI_SSID="<ssid>", WIFI_PASSWORD="<pw>")
        with self.assertRaises(config.ConfigurationError) as ctx:
            config.load(credentials_module=module)
        self.assertNotIn("<pw>", str(ctx.exception))

    def test_missing_credentials_module_reports_helpful_error(self):
        saved = sys.modules.get("credentials", "MISSING")
        sys.modules["credentials"] = None  # forces ImportError on import
        try:
            with self.assertRaises(config.ConfigurationError) as ctx:
                config.load_credentials()
            self.assertIn("credentials.example.py", str(ctx.exception))
        finally:
            if saved == "MISSING":
                sys.modules.pop("credentials", None)
            else:
                sys.modules["credentials"] = saved


class WeatherConfigTests(unittest.TestCase):
    def test_weather_defaults_are_valid(self):
        app_config = config.Config()
        self.assertEqual(627, app_config.elevation_ft)
        self.assertEqual(10800, app_config.pressure_trend_window_s)
        self.assertEqual(1.0, app_config.pressure_trend_threshold_hpa)
        self.assertEqual(-0.373, app_config.pressure_calibration_offset_inhg)
        self.assertEqual([], app_config.validate())

    def test_elevation_out_of_range_is_reported(self):
        problems = config.Config(elevation_ft=40000).validate()
        self.assertTrue(any("elevation_ft" in p for p in problems))

    def test_elevation_non_numeric_is_reported(self):
        problems = config.Config(elevation_ft="high").validate()
        self.assertTrue(any("elevation_ft" in p for p in problems))

    def test_below_sea_level_elevation_is_allowed(self):
        self.assertEqual([], config.Config(elevation_ft=-200).validate())

    def test_pressure_calibration_offset_is_bounded(self):
        self.assertEqual([], config.Config(
            pressure_calibration_offset_inhg=-0.373).validate())
        for value in (-2.1, 2.1, "invalid"):
            problems = config.Config(
                pressure_calibration_offset_inhg=value).validate()
            self.assertTrue(any("pressure_calibration_offset_inhg" in p
                                for p in problems), value)

    def test_non_positive_threshold_is_reported(self):
        problems = config.Config(pressure_trend_threshold_hpa=0).validate()
        self.assertTrue(any("threshold" in p for p in problems))

    def test_too_small_trend_window_is_reported(self):
        problems = config.Config(pressure_trend_window_s=60).validate()
        self.assertTrue(any("pressure_trend_window_s" in p for p in problems))


class WebConfigTests(unittest.TestCase):
    def test_web_defaults_are_valid(self):
        app_config = config.Config()
        self.assertTrue(app_config.web_enabled)
        self.assertEqual(80, app_config.web_port)
        self.assertEqual(10, app_config.web_refresh_min_s)
        self.assertEqual([], app_config.validate())

    def test_dashboard_can_be_disabled(self):
        self.assertEqual([], config.Config(web_enabled=False).validate())

    def test_non_bool_web_enabled_is_reported(self):
        problems = config.Config(web_enabled="yes").validate()
        self.assertTrue(any("web_enabled" in p for p in problems))

    def test_invalid_web_port_is_reported(self):
        for port in (0, 70000, "http"):
            problems = config.Config(web_port=port).validate()
            self.assertTrue(any("web_port" in p for p in problems), port)

    def test_too_small_refresh_interval_is_reported(self):
        problems = config.Config(web_refresh_min_s=1).validate()
        self.assertTrue(any("web_refresh_min_s" in p for p in problems))


class UtcOffsetConfigTests(unittest.TestCase):
    def test_default_is_eastern_standard(self):
        app_config = config.Config()
        self.assertEqual(-5, app_config.utc_offset_hours)
        self.assertEqual([], app_config.validate())

    def test_fractional_offset_is_allowed(self):
        self.assertEqual([], config.Config(utc_offset_hours=5.5).validate())

    def test_out_of_range_offset_is_reported(self):
        for value in (-13, 15):
            problems = config.Config(utc_offset_hours=value).validate()
            self.assertTrue(any("utc_offset_hours" in p for p in problems), value)

    def test_non_numeric_offset_is_reported(self):
        problems = config.Config(utc_offset_hours="east").validate()
        self.assertTrue(any("utc_offset_hours" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
